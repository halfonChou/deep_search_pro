# DeepSearch Pro 架构评审

> 评审范围：`app/`（40 个源文件）、`prompts/prompts.yml`、`docs/`、`tests/`、`web/app.py`、构建与依赖配置。
> 评审视角：资深架构师 / 生产可交付性。
> 日期：2026-08-14

---

## 0. 一句话结论

**架构骨架是对的，"为什么这么写"的思考质量远超同类个人项目；但护栏的作用域只覆盖了主图，子 Agent 基本裸奔，加上两个确定性 bug 和缺失的依赖清单，离"可交付"还差三件事。**

总分 **7.3 / 10**（明细见 §5）。

值得先说的优点，因为它们决定了后面所有建议都是"往上加"而不是"重写"：

- 中间件顺序有**明确且正确**的依据（观测最外层、SQL 拦截在重试外层、预算在重试之前），并且集中在一处装配 —— 这是很多商业项目都没做到的。
- 三层上下文（卸载 → 摘要 → 裁剪）+ 三层文件系统（`/scratch` L0 / checkpoint L1 / `data/session` L2）的分层是清晰的，"搜索原文绝不落 L2"这条规则抓住了要点。
- `schema_cache` 用一条 `information_schema` 查询换掉两轮大模型往返 —— 这是本项目**性价比最高的一处优化**，思路完全正确。
- 代码注释记录的是"踩过的坑和为什么不能改回去"（`_final_answer`、`GraphBubbleUp` 放行、`clear_history` vs `drop`、`count_zero_result`），这类注释的价值比代码本身高。
- `rag_tools` 里那句自我总结 —— *"凡是能用一行 if 写死的约束，就不该交给模型去权衡"* —— 是整个项目最有价值的一句话。**下面 Loop 章节的一半建议，都只是把这句话贯彻到你还没贯彻的地方。**

---

## 1. 必修：确定性缺陷

这四条不是风格问题，是"跑起来就错"或"并发就错"。

### 1.1 `/files/upload` 100% 抛 NameError

`app/api/routes_files.py:165`

```python
size, chunks = 0, []
while chunk := await file.read(1 << 20):
    size += len(chunk)
    ...
    chunks.append(chunk)
...
target.write_bytes(content)      # ← content 从未定义
return {"filename": file.filename, "size": len(content)}
```

分块读进了 `chunks`，写盘却用了不存在的 `content`。上传接口目前必然 500。
ruff 的 `F` 规则能直接抓到（`F821 Undefined name 'content'`），而 `pyproject.toml` 里 `F` 是开着的 —— 说明 **ruff 没有进 CI，也没有 pre-commit**。

修：`target.write_bytes(b"".join(chunks))`，返回 `size`。

### 1.2 `TaskService._evict()` 会把正在运行的任务记录删掉

`app/services/task_service.py:107`

```python
for tid, rec in list(self._task.items()):
    if rec.finished_at is None or now - rec.finished_at > _RECORD_TTL:
        del self._task[tid]
```

条件写反了。`finished_at is None` 意味着**任务还在跑**，这里却把它删了。`_evict()` 由 `_on_done` 调用，所以后果是：

> **任意一个任务结束时，所有其他正在运行的任务记录被清空。**

连带失效的三件事：

| 功能 | 表现 |
|---|---|
| `submit()` 幂等 | 记录没了 → 同一个 `thread_id` 可以被重复起任务，两个 Task 同时写同一个 checkpoint |
| `status()` | 正在跑的任务返回 `not_found`，前端以为挂了 |
| `cancel()` | 找不到 record，取消静默失败 |

`max_concurrent_tasks=5` 的场景下这是必现的。修：

```python
if rec.finished_at is not None and now - rec.finished_at > _RECORD_TTL:
```

### 1.3 `EventBus.publish` 在迭代 set 时 await

`app/infra/event_bus.py:31`

```python
for q in queue:          # queue 是 set
    ...
    await q.put(event)   # 这里让出控制权
```

`await` 期间如果某个 WebSocket 断开，`subscribe` 的 `finally` 会 `discard` 掉它的队列 → `RuntimeError: Set changed size during iteration`，这条事件之后的订阅者全部收不到。

前端刷新页面就可能触发。修：`for q in list(queue):`。

### 1.4 `plan_update` 事件双发

两处都在发同一种事件，且各自维护独立的去重签名（互相看不见）：

- `EventEmitMiddleware.aafter_model`（`observability.py:105`）
- `run_agent_stream` 的 updates 分支（`stream.py:189`）

前端会收到重复的计划更新。留一处就行 —— 建议留中间件那一处（能拿到 runtime，也更靠近状态变更），把 `stream.py` 里的删掉。

### 1.5 checkpointer 连接从不关闭

`build_checkpoint` 里 `aiosqlite.connect()` 出来的连接挂在 `AsyncSqliteSaver` 上，lifespan 的关闭段只 close 了 `db`。进程退出时 WAL 不做 checkpoint，`.sqlite-wal` 会一直留着（你现在就有 4MB 的 WAL）。

修：把连接存到 `app.state`，关闭段 `await conn.close()`。

---

## 2. Loop 工程（Agent 循环）—— 本次评审的重点

你的循环由两部分组成：deepagents 的 ReAct 主循环 + `database-query` 的自定义 StateGraph。问题不在单点实现，在**作用域**和**约束落地的位置**。

### 2.1 【最严重】所有护栏只包住主 Agent，子 Agent 是裸奔的

`build_middleware_stack(deps)` 的返回值只传给了 `create_deep_agent(middleware=...)`。它包的是**主图的模型调用和工具调用**。而：

- `network-search` / `knowledge-base` 是 dict 声明的子 Agent，各自有自己的 `model` 和自己的 `middleware`（只挂了一个 `ToolCallLimitMiddleware`）。
- `database-query` 是**独立编译的 StateGraph**，主图中间件一层都不过 —— 这一点你在 `sql_tools.py` 顶部已经明确记录了（"实测确认过：子图里执行的 SQL 全都没有被补上 LIMIT"），并用工具内 assert 做了纵深防御。**但只补了 SQL 安全，其他四类护栏没补。**

逐项算一下漏掉了什么：

| 护栏 | 主 Agent | 两个 dict 子 Agent | database-query 子图 |
|---|---|---|---|
| `BudgetMiddleware`（token / 成本熔断） | ✅ | ❌ | ❌ |
| `ModelCallLimitMiddleware` | ✅ | ❌ | ❌ |
| `ToolCallLimitMiddleware`（全局） | ✅ | 仅单工具 | ❌ |
| `SummarizationMiddleware` | ✅ | ❌ | ❌ |
| `ContextEditingMiddleware` | ✅ | ❌ | ❌ |
| `SqlGuardMiddleware` | ✅ | — | ❌（工具内 assert 兜住） |
| `ToolRetryMiddleware` | ✅ | ❌ | ❌ |

**后果排序：**

1. **预算熔断名义存在、实际失效。** `BUDGET_MAX_TOKENS=200000` 只统计主 Agent。三个子 Agent 用 `qwen-plus` 各跑几轮，加上 `SummarizationMiddleware` 自己那次 `qwen-turbo` 调用，真实消耗可以是账面的 3～5 倍。一个"每次运行最多 1 美元"的系统，实际可能花 3 美元而不触发任何告警。这是**成本安全问题**，不是优化项。
2. **子图上下文只增不减。** `db_agent` 节点每次都 `[system, *state["messages"]]` 全量重发。SQL 反复重写 + 零结果试探时，messages 只增长，没有任何摘要或裁剪。目前靠 `MAX_SQL_ATTEMPTS=3` 勉强兜住，但 `count_zero_result` 只对"零结果"计数，**成功但数据不对的情况不计数**，循环可以比 3 轮长得多。
3. **子 Agent 的工具没有重试。** `internet_search` 自己实现了 2 次重试（好），`rag_search` 和所有 SQL 工具没有。

**建议（按投入排序）：**

```python
# app/middleware/stack.py 新增
def build_subagent_middleware(deps: AgentDeps, name: str) -> list:
    """子 Agent 的最小护栏集：预算 + 次数 + 摘要。
    和主栈共享同一个预算计数器 —— 关键在这里。"""
    s = deps.settings
    return [
        BudgetMiddleware(s, counter=deps.budget),   # ← 共享计数器
        ModelCallLimitMiddleware(run_limit=8, exit_behavior="end"),
        SummarizationMiddleware(
            model=build_chat_model(s, s.llm_model_cheap),
            trigger=("tokens", 30_000),
            keep=("messages", 12),
        ),
        ToolRetryMiddleware(max_retries=2, jitter=True),
    ]
```

预算计数器**不能继续放在 state 里**（`tokens_used` 在 `BudgetState` 上，子图 state schema 不同，天然隔离）。改成 per-thread 的进程内计数对象，挂在 `AgentDeps` 上、按 `thread_id` 分桶：

```python
@dataclass
class BudgetCounter:
    _by_thread: dict[str, tuple[int, float]] = field(default_factory=dict)
    def add(self, tid: str, tokens: int, cost: float) -> tuple[int, float]: ...
    def over(self, tid: str, s: Settings) -> str | None: ...
```

`database-query` 子图无法挂 middleware，就在 `db_agent` 节点里手动记账（`response.usage_metadata` 就在手上），超限时直接路由到 `give_up`。

> 这一条做完，整个项目的可信度会有质变：现在的中间件栈在文档里是"九层护栏"，实际是"主 Agent 的九层护栏 + 子 Agent 的一层"。

### 2.2 循环的收敛靠"次数硬闸"，缺"质量闸"

现在所有停机条件都是撞墙式的：`MAX_SQL_ATTEMPTS`、`model_call_run_limit`、`budget_max_tokens`。没有任何一处在问"结果对不对"。

最要命的是**引用落地性**。你的 prompt 里为此写了整整一节（"凡是要写进最终答复的数字/机构名/网址，必须先 read_file 读回全文核对"），非常正确 —— 但这是一条**概率性约束**，而它守护的是医药场景下最不能错的东西。

按你自己那句"能用一行 if 写死的约束就不该交给模型权衡"，这里应该有代码：

```python
# 建议：generate_markdown 之前插一个 grounding 检查
async def verify_grounding(report: str, scratch_texts: list[str]) -> list[str]:
    """抽出报告里所有数字 + URL，逐个在 /scratch 原文里找。
    找不到的返回列表 —— 这不是 LLM 判断，是字符串包含检查，确定性的。"""
    claims = re.findall(r"\d+(?:\.\d+)?%?|https?://\S+", report)
    corpus = "\n".join(scratch_texts)
    return [c for c in claims if c not in corpus]
```

不通过就把缺失清单塞回给模型让它改或标注"未取到"。成本几乎为零（纯字符串操作），拦住的是"报告里有个凭印象写的价格"这类**静默错误**。

同理，你在 `sql_safety` 注释里写的"下一步可以做的：跑一次 EXPLAIN 拿 rows 估算"也属于这类 —— 用一次毫秒级查询换掉一条静态规则。

### 2.3 并行派发靠 prompt 求模型自觉

`prompts.yml` 里【关键执行顺序】第 2、3 条花了约 400 token 反复强调"必须同一轮发出多个 task""禁止派一个等一个""有依赖的合并成一个子任务"，还带了正反例。

这是**用自然语言实现一个调度器**。它能工作，但：

- 每次运行都要为这段规则付 400 token 的输入成本，且它会和别的规则竞争注意力；
- 遵守率是概率性的，模型偶尔就是会串行派发，而你在事后无法区分"它判断有依赖"和"它没遵守"；
- `stream.py` 里靠 `"task" in node_name` 猜委托，所以**你也观测不到实际的并行度**。

更稳的形态：主 Agent 只负责产出**结构化计划**，扇出交给代码。

```python
class PlanStep(BaseModel):
    agent: Literal["network-search", "knowledge-base", "database-query"]
    task: str
    depends_on: list[int] = []

class Plan(BaseModel):
    steps: list[PlanStep]

# 主图：plan 节点 → 按 depends_on 分层 → 每层用 Send 扇出 → gather 节点
```

收益：并行度 100% 确定、耗时可预测（= 最慢那层之和）、省掉那 400 token 的规则和主 Agent 反复自我说服的思考、并行度可观测。代价：失去一点"临场加派一个助手"的灵活性 —— 可以保留一个 `task` 工具做逃生通道。

**这是 loop 层最大的一块可优化空间**，也是最能体现架构能力的改动。

### 2.4 token 流是混流的

```python
async for chunk in agent.astream(..., stream_mode=["updates", "messages"], version="v2"):
    if mode == "messages":
        token, _meta = data      # ← _meta 被丢掉了
```

`messages` 模式会推**所有节点**的 token，包括：三个子 Agent 的内部独白、`SummarizationMiddleware` 那次摘要调用的输出、`db_agent` 写 SQL 的过程。前端看到的"逐字输出"实际上是几路混在一起的，`final_text` 的兜底拼接也会串味。

`_meta` 里就有 `langgraph_node` 和 `tags`，接上就行：

```python
token, meta = data
if meta.get("langgraph_node") in MAIN_ANSWER_NODES:   # 或按 tags 过滤
    ...
```

顺带：`version="v2"` 是 `astream_events` 的参数，`astream` 不认，属于无效参数（当前被静默吞掉，将来可能报错）。

### 2.5 子 Agent 事件是靠节点名猜的，且不成对

```python
if node_name and ("task" in node_name or "subagent" in node_name):
    ... publish(type="subagent_call", data={"node": node_name})
```

`events.py` 定义了 12 种事件类型，实际发出的大约 8 种 —— `subagent_result`、`session_created`、`budget_warning` 基本没人发。而 `subagent_call` 是靠字符串匹配节点名猜出来的，拿不到"派给了谁、任务是什么、跑了多久"。

正确位置是 `EventEmitMiddleware.awrap_tool_call`：`task` 工具的 `args` 里就有子 Agent 名和任务描述，`handler` 返回时就有耗时和结果长度。改完可以成对发 `subagent_call` / `subagent_result`，前端才能画出真正的甘特图（也才能验证 §2.3 的并行度）。

`budget_warning` 同理：`BudgetMiddleware` 在 80% 阈值就该发一次预警，而不是等熔断。

### 2.6 `/scratch` 卸载把上下文压力搬到了 checkpoint 上

这是一个隐蔽但重要的权衡。`_offload.py` 用 `StateBackend` 把全文写进 `files` state 通道，而 **state 的每一次 checkpoint 都会把 `files` 整体序列化一遍**。

于是：一个 thread 跑 20 步、卸载了 5 个 30KB 的搜索原文（150KB），这 150KB 会被写进它之后的**每一个** checkpoint。存储增长是 O(步数 × 累计卸载量)。

证据就在你的仓库里：`data/checkpoints.sqlite` = **28MB**，`-wal` = **4MB**，而这只是开发期几十个会话。

上下文 token 是省了（这个目的达成了），但代价搬到了磁盘和序列化耗时上。而且**没有任何回收机制** —— checkpoint 表只增不删，`cleanup_expired` 只清 `data/session/` 目录，不碰 checkpoint。

建议：

1. 卸载改走**真实文件后端**（deepagents 的 `FilesystemBackend`，或 LangGraph 的 `BaseStore`），state 里只留路径字符串。改动很小 —— `_offload.py` 里换一个 backend 实例，`read_file` 那一侧 deepagents 会自动适配。
2. 加 checkpoint 回收：按 thread TTL 删 `checkpoints` / `writes` 表的行，跟 `_cleanup_loop` 一起跑（现在那个协程只清目录，正好扩一下）。
3. 生产环境把 checkpointer 换成 Postgres（`AsyncPostgresSaver`），单文件 SQLite + 单连接在多 worker 下会锁。

### 2.7 prompt 缓存和上下文压缩互相打架

`CacheStatsMiddleware` 是很好的加分项 —— 百炼的隐式缓存默认不可见，你把它测出来了。但目前它测到的命中率大概率不高，原因是结构性的：

- `SummarizationMiddleware` 一动手，历史消息被替换成摘要 → **前缀变了 → 之后全部 miss**。
- `ContextEditingMiddleware` 的 `ClearToolUsesEdit` 同理。
- `db_agent` 把 schema 拼在 system prompt 末尾（这一点做对了 —— 变动部分靠后），但主 Agent 的 `{{TODAY}}` 在 prompt **最开头**，跨天就整体 miss（影响不大，但结构上是反的）。

建议：
- 把 `{{TODAY}}` 这类运行时变量移到 system prompt **末尾**，前面那 4000 字的稳定规则才能进缓存。
- 摘要触发阈值（60K）相对 200K 预算偏低。优先靠 offload 控制体积（offload **不动前缀**，是缓存友好的），把摘要阈值抬到 100K+，让摘要成为"很少发生的事"而不是常规操作。
- 摘要发生后把摘要块拼在 system prompt 之后并**在本次运行内冻结**，避免每轮都重写。

### 2.8 最贵的工具没有去重缓存

`rag_search` 有 LRU 去重缓存（做得很好，包括"零命中也缓存"和"命中时照样返回内容但标注重复"这两个细节）。但 `internet_search` **没有** —— 而它是全项目最贵的工具，你专门给它配了 `search_tool_run_limit=5`。

同一 query 重复检索的概率不比 RAG 低（主 Agent 和子 Agent 可能各发一次相近的查询）。把 `rag_tools` 里那套 `_cache` / `_norm` / `_thread_id_of` 抽成一个通用装饰器，`internet_search`、`get_table_data`、`describe_table` 一起用。约 30 行代码，直接省钱。

### 2.9 审批只看 `tool_calls[0]`，第二条 SQL 可以绕过审批

`database_query.py` 里三处都只取第一个 tool call：

- `make_approval_node`: `tool_call = last.tool_calls[0]`
- `_precheck_ok(tool_call, ...)`: 只传了 `[0]`
- `route_after_db_agent`: `tool_call = last.tool_calls[0]`

但 `ToolNode` 会执行**全部** tool_calls。所以模型一轮里发两条 SQL 时：

- 第 1 条走完整流程（预检 → 风险评估 → 可能审批）；
- 第 2 条**既不过预检也不过审批**，直接被 ToolNode 执行。

工具内的 `assert_read_only` / `enforce_limit` 还兜着（纵深防御生效了，这是好事），但 `assess_sql_risk` 那层"SELECT * / 全表扫描 / 敏感表 → 人工审批"被完全绕过。敏感表配置在这条路径上等于不存在。

两种修法，建议都做：
1. `bind_tools(tools, parallel_tool_calls=False)` —— 一行，立即消除这个类别的问题；
2. 三处改成遍历 `last.tool_calls`，任一条命中就走对应分支（更彻底，也保留并行工具调用的能力）。

### 2.10 子图无 checkpointer，HITL 恢复路径缺集成测试

`g.compile()` 没传 checkpointer，靠父图的 checkpointer 冒泡保存子图状态。目前能跑，但 `approve_sql` 节点在 resume 时会**从头重跑**（你在注释里已经意识到这点并保证了无副作用，很好），而 `sql_attempts` / `schema_cache` 能否正确跨中断恢复，边界比较窄。

建议补一条集成测试：中断 → **重启进程** → `POST /decision` 恢复 → 断言 SQL 真的执行了且 `sql_attempts` 没被重置。这是最容易在演示时翻车的路径，也是最能证明"我真的懂 LangGraph 持久化"的测试。

---

## 3. 安全

### 3.1 `sql_table_allowlist` 对 `execute_sql_query` 完全不生效

`assert_table_allowed` 只在 `describe_table` / `get_table_data` 的 `table_name` **参数**上检查。`execute_sql_query` 走的是 `assert_read_only` + `enforce_limit`，**从不检查 SQL 里引用了哪些表**。

后果：raw SQL 可以查库里任意表，也可以 `SELECT * FROM information_schema.COLUMNS`（把整个库结构读出来）、`SELECT * FROM other_db.users`（跨库，只要连接用户有权限）。表白名单这个配置项在最需要它的地方是失效的。

你已经写好了 `referenced_tables(sql)`（目前只用于敏感表判定），接上去就行：

```python
def assert_sql_tables_allowed(sql: str, allowlist: list[str]) -> None:
    if not allowlist:
        return
    refs = referenced_tables(sql)
    illegal = refs - {t.lower() for t in allowlist} - _CTE_ALIASES(sql)
    if illegal:
        raise ValueError(f"SQL 引用了不在白名单内的表：{sorted(illegal)}")
```

同时显式拒绝 `information_schema` / `performance_schema` / `mysql` 三个系统库（`schema_cache` 自己探测时走的是独立通道，不受影响）。

### 3.2 WebSocket 路由没有鉴权

```python
app.include_router(files_router, dependencies=[Depends(require_token)])
app.include_router(task_router,  dependencies=[Depends(require_token)])
app.include_router(ws_router)      # ← 没有
```

只要知道（或猜到）`thread_id`，任何人都能订阅事件流。而事件流里带着 `tool_start` 的完整 `args`（包括 SQL 原文）、表数据摘要、报告内容。这是**未鉴权的数据泄露通道**。

WS 不能用 header 的话，走 query 参数 token 或首帧握手鉴权。

### 3.3 `thread_id` 是客户端自己给的字符串，无归属校验

`thread_id` 由调用方任意指定，服务端只做正则格式校验。谁猜到别人的 `thread_id` 就能：

- `GET /task/{tid}` 看状态
- `PUT /task/{tid}/todos` **覆盖写**别人的计划
- `GET /files/list?thread_id=...` 列文件、`/download` 下载报告
- `POST /task/{tid}/decision` **替别人批准一条 SQL**

最后这条最严重 —— HITL 审批可以被任意第三方代为批准，整套人工审批机制被绕过。

至少要做：token（或未来的用户身份）与 `thread_id` 绑定，服务端维护 `thread_id → owner` 映射并在每个路由上校验。现在是单一静态 Bearer token，等于所有人共享一个身份 —— 单用户 demo 可以，多人就不行。

### 3.4 `assert_read_only` 的正则方案有误伤也有漏放

- **误伤**：`_strip_strings` 只处理单引号。反引号包裹的列名 `` `update` ``、`` `create_time` `` 中 `` `update` `` 会被 tokenize 成 `UPDATE` 而被拒。
- **漏放**：双引号字符串（MySQL 在 `ANSI_QUOTES` 关闭时也接受）未剥离，可以藏关键字。
- 注释剥离在检查 `;` 之前 —— 这个顺序是**对的**，值得保留。

生产建议换 `sqlglot` 解析成 AST：判断语句类型、抽表名、检测多语句，一次解决 §3.1 和本节。可靠性比正则高一个量级，代价是一个依赖。

---

## 4. MCP：现在是 0 处，建议这样接

全项目搜索 `mcp` 零命中。这不是缺陷 —— 你的工具都是自研的，本来不需要 MCP。但如果要往这个方向做，有明确的该做和不该做。

### 4.1 不该 MCP 化的：SQL / HITL 这条链

你的安全模型是"中间件拦截 + 参数改写 + 图内审批 + 工具内纵深防御"四层叠起来的。MCP server 是**进程外的黑盒**：

- `SqlGuardMiddleware` 还能拦（它拦的是 tool_call，与工具实现无关）；
- 但 `enforce_limit` 的**参数改写**、`assess_sql_risk` 的**审批理由生成**、`offload_if_large` 的 `/scratch` 落盘，全都要在 MCP server 侧重新实现一遍；
- 更麻烦的是 HITL：`interrupt()` 依赖 LangGraph 的图内状态，跨进程边界后审批语义要自己设计。

**结论：把最需要精细控制的那条链推到进程外，收益（解耦）小于代价（安全逻辑重复实现）。保持现状。**

### 4.2 该 MCP 化的：可替换的外部能力

Tavily 搜索、未来的 PDF/OCR、行业数据源（药监局、药智网）、企业内部 Confianceluence/文档系统 —— 这些的共同特征是**供应商可换、协议标准化收益大**。

落点你已经预留好了：`AgentDeps.extra_tools`（`deps.py:27`）从建好那天起一直是空列表。这就是它的位置。

```python
# app/infra/mcp.py
from langchain_mcp_adapters.client import MultiServerMCPClient

async def build_mcp_tools(settings) -> list:
    client = MultiServerMCPClient({
        "search": {"transport": "stdio", "command": "npx", "args": [...]},
        "pharma-data": {"transport": "streamable_http", "url": settings.mcp_pharma_url},
    })
    return await client.get_tools()

# main.py lifespan：和 db / retriever 一样的模式
try:
    mcp_tools = await build_mcp_tools(settings)
except Exception as e:
    logger.warning("MCP 装配失败，跳过：%s", e)
    mcp_tools = []
```

### 4.3 接 MCP 的三个坑，提前设计

**坑一：工具描述膨胀。** 一个 MCP server 常带 20–40 个工具。全量注入会把主 Agent 的 tool schema 撑到几千 token（且每轮都付），更糟的是**显著降低选工具的准确率** —— 你现在三个子 Agent 的 description 是精心写过的、边界互斥的（"不能查企业内部数据，那些找 database-query"），MCP 原厂描述是给通用 agent 写的，混进来会破坏这个边界。

必须做：白名单过滤（只取真正需要的 3–5 个工具）+ **重写 description** 成你的语境。

**坑二：护栏不会自动覆盖。** MCP 工具进来后：

- `ToolCallLimitMiddleware(tool_name="internet_search", run_limit=5)` 是按**具体工具名**配的，换成 MCP 的 `tavily_search` 就不生效了 —— 限流静默失效；
- 没有 `offload_if_large`，一次搜索 6 万字符直接灌进上下文（你在 `search_tools.py` 注释里记录过这个坑，MCP 会把它带回来）;
- 没有超时控制，MCP server 卡住就整个 agent 卡住。

建议统一包一层：

```python
def wrap_mcp_tools(tools: list, settings: Settings) -> list:
    """给 MCP 工具补上本项目的三件套：超时 + 卸载 + 命名规范化。"""
    return [_wrap(t, settings) for t in tools]
```

并把限流改成按前缀/server 配，而不是按具体工具名。

**坑三：生命周期与降级。** MCP client 持有连接，必须进 lifespan 管理。而且要有"server 挂了就降级"的路径 —— 这个你**已经有现成的模式**：`knowledge_base.py` 里的 `_build_degraded_tools()`（retriever 不可用时返回一个"知识库当前不可用，请改用网络搜索"的假工具）。这套做法直接复用到 MCP 上就行，是本项目里一个真正优雅的设计。

### 4.4 反向：把自己暴露成 MCP server

投入很小、演示价值很高的一件事：把 `rag_search`（医药知识库）和 `list_past_reports`（历史报告索引）用 `mcp` Python SDK 包成一个 MCP server。这样 Claude Desktop、Cursor、或者别的 agent 可以直接查你的医药知识库。

约 100 行代码，但它把项目从"一个应用"变成"一个可被复用的能力"，是很好的收尾亮点。

---

## 5. 工程化与可交付性

### 5.1 【硬伤】没有依赖清单

- 根目录**没有** `requirements.txt`，但 README 第一步就是 `pip install -r requirements.txt`。
- `pyproject.toml` **没有** `[project.dependencies]`。
- 唯一的依赖清单在 `data/mydataS/requirements.txt`，而 `data/*` 被 `.gitignore` 排除了 —— **它不在 git 里**。

也就是说：**clone 这个仓库的人装不起来。**

更讽刺的是，那份 requirements 的文件头写的正是「本次修正解决的问题：deepagents 0.7.x ↔ langchain/langgraph 版本冲突」—— 你自己踩过版本冲突的坑，却把解决方案放在了唯一不会被提交的目录里。

修（优先级最高的非 bug 项）：把依赖收进 `pyproject.toml` 的 `[project.dependencies]`，**deepagents / langchain / langgraph 三者锁到具体版本**，并把那份 requirements 的坑记搬进注释。

### 5.2 其他

| 项 | 现状 | 建议 |
|---|---|---|
| CI / pre-commit | 无（`F821` 这种 ruff 能抓的 bug 进了主干） | GitHub Actions 跑 `ruff check` + `pytest`，10 行配置，收益立竿见影 |
| 健康检查 | 无 `/health` | db / retriever 连不上是**静默降级**（`db = None`），外部完全看不出来。加 `/health` 返回各依赖状态 |
| git 卫生 | 60+ 文件 `M` 未提交，最后一次 commit 是"自研 RAG 流水线"，代码已到 Day 11 | 密钥没进 git（`.gitignore` 写得很规范，这点做得好），但提交粒度应更细 |
| 仓库内容 | `data/mydataS/` 学习笔记、`data/面试叙述文档_*.md`（95KB）混在仓库里 | 移出仓库根，或单独一个 `notes/` 仓库 |
| `web/app.py` | 单文件 33KB Streamlit | 拆成 `components/` + `api_client.py` |
| README | 描述的 12 种事件、三层上下文都对得上代码 | 但"运行测试"只列了 2 个测试文件，实际有 20 个 —— 更新一下 |

---

## 6. 评分

| 维度 | 分数 | 理由 |
|---|:--:|---|
| **架构与分层** | 8.5 | agents / api / middleware / tools / services / infra / rag 职责清晰，`AgentDeps` 斩断循环依赖，Protocol 抽象（Embedder / VectorStore）用得准。dict + StateGraph 混合编排的取舍有依据。扣分在子图与主图的护栏边界没设计清楚 |
| **Agent 循环 / 上下文工程** | 7.5 | 三层上下文、schema 预探测、RAG 去重缓存都是一流的想法。扣分：护栏只覆盖主图、并行调度用 prompt 实现、token 流混流、offload 把压力搬到 checkpoint |
| **可靠性与护栏** | 6.5 | 中间件顺序论证正确、`GraphBubbleUp` 放行这种细节都抓到了。但预算/限流/摘要对子 Agent 全部失效，加上 `_evict` 和 `EventBus` 两个并发 bug |
| **安全** | 6.0 | SQL 只读校验（注释剥离顺序、字符串剥离、多语句检测）做得细，纵深防御意识强，审批疲劳的权衡是专业判断。扣分：表白名单对 raw SQL 失效、WS 无鉴权、`thread_id` 无归属校验（HITL 可被第三方代批）、`tool_calls[0]` 绕过审批 |
| **可观测性** | 8.0 | contextvars 结构化日志、EventBus 重放、`CacheStatsMiddleware`、两个观测中间件分层（外层测真实耗时 / 内层看重试次数）—— 这个分层是专业水准。扣分：事件类型定义了 12 种只发 8 种，子 Agent 委托靠猜节点名 |
| **性能与成本** | 7.0 | schema 预探测省两轮往返、offload、RAG 去重、`stream_usage=True`、异步 Tavily 都对。扣分：搜索无去重缓存、摘要与 prompt 缓存互斥、checkpoint 无回收 |
| **测试** | 7.5 | 20 个测试文件覆盖 config / db / hitl / rag / security / sql_guard / middleware / 集成，有 `conftest` 隔离临时目录 —— 个人项目里少见。扣分：无 CI，HITL 跨进程恢复未覆盖 |
| **工程化与可交付** | 5.5 | 依赖清单缺失是硬伤（clone 装不起来）；无 CI；无健康检查；仓库混着学习笔记 |
| **文档与注释** | 9.0 | 全项目最强项。注释写的是"为什么这么做、踩过什么坑、为什么别改回去"，`docs/architecture.md` 与代码一致。这类注释的工程价值高于代码本身 |

### **总分：7.3 / 10**

**定位**：作为个人项目属于上游水平 —— 架构思考的深度（尤其是中间件顺序论证、审批疲劳权衡、"能写死的约束别交给模型"）已经是有经验的工程师水平。

**离生产的距离**：三件事 —— ①护栏作用域扩到子 Agent（成本安全）、②依赖锁定 + CI（可交付）、③鉴权与 thread 归属（多用户安全）。

---

## 7. 建议的执行顺序

### P0（半天，先止血）
1. 修 `routes_files.py:165` 的 `content` NameError
2. 修 `TaskService._evict()` 的反向条件
3. `EventBus.publish` 改 `for q in list(queue)`
4. 依赖收进 `pyproject.toml` 并锁版本（deepagents / langchain / langgraph）
5. 加 GitHub Actions：`ruff check` + `pytest`

### P1（2–3 天，安全与成本兜住）
6. 预算计数器改成跨图共享，子 Agent 统一挂最小护栏集（§2.1）
7. `execute_sql_query` 接上表白名单 + 拒绝系统库（§3.1）
8. WS 加鉴权；`thread_id` 与身份绑定（§3.2 / §3.3）
9. `bind_tools(parallel_tool_calls=False)` + 三处遍历全部 tool_calls（§2.9）
10. 删掉重复的 `plan_update`；关闭 checkpointer 连接

### P2（1 周，把想法落地成代码）
11. grounding 校验节点：报告里的数字/URL 必须在 `/scratch` 原文中出现（§2.2）
12. 结构化计划 + `Send` 扇出，替换 prompt 里的并行派发规则（§2.3）
13. token 流按 `langgraph_node` 过滤；`task` 工具处发成对的 subagent 事件（§2.4 / §2.5）
14. offload 换真实文件后端；checkpoint 加 TTL 回收（§2.6）
15. 通用去重缓存装饰器，覆盖 `internet_search`（§2.8）
16. `sqlglot` 替换正则做 SQL 校验（§3.4）

### P3（有余力，加分项）
17. 接 MCP：只接可替换的外部能力，配 `wrap_mcp_tools` 护栏层（§4.2 / §4.3）
18. 把 `rag_search` / `list_past_reports` 暴露成 MCP server（§4.4）
19. checkpointer 换 Postgres；`/health` 端点；`web/app.py` 拆分
20. HITL 跨进程恢复的集成测试

---

*评审依据：完整阅读 `app/` 下全部源文件、`prompts/prompts.yml`、`docs/architecture.md` 与 `context_strategy.md`、`pyproject.toml`、`.gitignore`、`tests/conftest.py`，并对 `app/` 运行了 `ruff check --select F,E9,B`。缺陷 1.1 已由静态检查确认（F821），1.2–1.5 为代码走查确认。*
