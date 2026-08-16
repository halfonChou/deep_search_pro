# DeepSearch Pro · State 视角的分阶段导读

> 用一条主线重讲 Phase 2 的 11 天：**每一天，你到底往 state 里加了什么、改了什么、读了什么。**
> 所有字段都对应仓库里真实存在的代码，文末标了文件与行为出处。

---

## 0. 先分清四种"状态"，别混

项目里被叫做"状态"的东西有四种，生命周期和归属完全不同。这是理解后面所有内容的地基。

| 名字 | 载体 | 谁写 | 生命周期 | 进 checkpoint？ | 进上下文？ |
|---|---|---|---|---|---|
| **图 State** | `AgentState` / `DBQueryState` 的 TypedDict | 节点返回的 dict、中间件的 `Command(update=)` | 随 thread_id 存活 | ✅ 落 `data/checkpoints.sqlite` | messages/todos 全量进；files 只在 `read_file` 时进 |
| **RunContext** | `app/agents/context.py` 的 dataclass | 只在 `invoke(context=...)` 时传一次 | 单次调用 | ❌ 只读、不落盘 | ❌ 模型看不见 |
| **AgentDeps** | `app/agents/deps.py` | 启动时 lifespan 装配一次 | 整个进程 | ❌ | ❌ |
| **TaskRecord** | `TaskService._task` 内存字典 | `submit/_on_done` | 进程内，15 分钟 TTL | ❌ | ❌ |

**一句话判据：只有需要"跨轮次被模型看到、或崩溃后能恢复"的东西才配进图 State。** 其余三种都不该混进去。

- `thread_id` 是 RunContext 不是 State —— 它每次调用都由外部给定，让它进 State 反而会被 checkpoint 固化。
- `db` / `bus` / `settings` 是 AgentDeps 不是 State —— 它们不可序列化，塞进 State 会让 checkpointer 直接炸。
- 任务是 running 还是 cancelled 是 TaskRecord 不是 State —— 那是**进程**的状态，不是**对话**的状态。这两者会不一致（进程重启后 TaskRecord 没了，State 还在），而且**必须**允许不一致。

---

## 1. 全项目的 State 字段总表

### 主图 State（deepagents 的 `AgentState` + 你的扩展）

| 字段 | 类型 | reducer | 谁写入 | 引入日 |
|---|---|---|---|---|
| `messages` | `list[BaseMessage]` | `add_messages`（**同 id 覆盖，否则追加**） | 模型节点、ToolNode、SqlGuard 的拦截 ToolMessage、Budget 的熔断 AIMessage | Day 2 |
| `todos` | `list[{content,status}]` | 覆盖 | `TodoListMiddleware` 提供的 `write_todos` 工具 | Day 5 |
| `files` | `dict[path, content]` | 合并 | `write_file` 工具、`offload_if_large()` 经 `StateBackend.write` | Day 10 |
| `tokens_used` | `int` | 覆盖 | `BudgetMiddleware.awrap_model_call` 的 `Command(update=)` | Day 8 |
| `cost_usd` | `float` | 覆盖 | 同上 | Day 8 |
| `jump_to` | `"end"` | 控制信号 | `BudgetMiddleware.before_model` 熔断时 | Day 8 |

### 数据库子图 State（`DBQueryState(FilesystemState)`）

| 字段 | 作用 | 谁写 |
|---|---|---|
| `messages` | 子图内部的对话（**不回流到主图**） | `db_agent` / `db_tools` / `approve_sql` / `rewrite_sql` / `give_up` |
| `files` | 继承自 `FilesystemState`，让 `offload_if_large()` 在子图里也能落盘 | `sql_tools` 的大结果卸载 |
| `schema_cache` | `{表名: [字段名]}`，入口节点一次性灌进来 | `load_schema` 节点 |
| `sql_attempts` | 失败/零结果计数器，`>= 3` 就走 `give_up` | `rewrite_sql`（+1）、`count_result`（+1） |
| `pending_sql` | **声明了但全项目无人读写** —— 见 §4 待办 | — |

---

## 2. 逐日：这一天动了 state 的哪一块

### Day 1 — 把"不该进 state 的东西"先拿出去

这一天没有创建任何 state 字段，做的是**反向的事**：把原来靠 ContextVar 和闭包传递的 `thread_id` / `session_dir` 收进 `RunContext`，通过 `context_schema=RunContext` 注入。

state 视角的意义：**确立了"每请求变量走 context，不走 state"这条边界。**如果当初把 `session_dir` 塞进 state，它会随 checkpoint 被固化，同一个 thread 换个部署路径就全错。

工具侧的对应写法是 `runtime: ToolRuntime` 参数 —— `doc_tools.generate_markdown` 里的 `ctx = runtime.context` 就是这条链路的终点。

### Day 2 — 让 state 有了"存在"这回事

`AsyncSqliteSaver` 接进来之前，state 只活在一次 `invoke` 的内存里。接进来之后：

- 每个节点返回的增量都被 append 成一次 checkpoint 写入
- `thread_id` 成为 state 的主键（`config={"configurable":{"thread_id":...}}`）
- 第二次带同一个 `thread_id` 提问，`messages` 里已经有上一轮的全部历史

**这一天你要能答的是：节点返回 `{"messages": [response]}` 为什么不会覆盖掉历史？** 因为 `messages` 上标了 `Annotated[..., add_messages]` reducer —— 节点返回的永远是**增量**，怎么合并由 reducer 决定。后面 Day 7 的 "edit 审批用 `model_copy` 保留原 id 实现覆盖"，靠的正是 `add_messages` 同 id 覆盖这个语义。

### Day 3 — 第一次"读"state：事件从 state 增量里挖出来

`EventEmitMiddleware.aafter_model(state, runtime)` 拿到的就是当前 state 快照，它读 `state.get("todos")` 推 `plan_update`。

`stream.py` 走的是另一条路：`stream_mode=["updates","messages"]`，`updates` 给的是**每个节点的 state 增量 dict**，所以 `for node_name, update in data.items()` 里的 `update.get("todos")` 才有东西。

> ⚠️ 现状提醒：`plan_update` 事件在 `observability.py:aafter_model` 和 `stream.py` 里**各发了一次**，两边都有各自的去重签名但互不知情，前端可能收到重复计划事件。要么砍掉一处，要么在前端按 `todos` 签名去重。

### Day 4 — 把"进程状态"和"图状态"彻底切开

`TaskService` 这一天诞生。它维护的 `TaskRecord.state`（pending/running/done/cancelled/error）和图 State 是两套东西：

- 图 State 回答"这个对话进行到哪了"
- TaskRecord 回答"这个 asyncio.Task 还活着吗"

`decide()` 里那段兜底最能说明问题：进程重启后 `TaskRecord` 没了，但 checkpoint 里的中断还在，所以它**新建一个 TaskRecord 然后照样 resume** —— 图 State 是真相来源，TaskRecord 只是本地缓存。

同一天 `SessionService` 建立 L2 层（`data/session/<tid>/` + `index.jsonl`），这一层**永远不进 state**，模型只能通过 `list_past_reports` 拉到路径和一句话摘要。

### Day 5 — state 隔离：子 Agent 的 messages 不回流

声明式子 Agent（`network-search` / `knowledge-base`）在 deepagents 里各自跑独立的 state。关键机制是 `_EXCLUDED_STATE_KEYS` 排除了 `messages`：

- 子 Agent 内部烧掉的 10 轮对话，**主图 messages 里只留一条 task 工具的返回摘要**
- 但 `files` 通道**会**合并回来 —— 所以子 Agent 落到 `/scratch/` 的东西，主 Agent 之后能 `read_file` 读到

这就是"上下文隔离"的实现层面答案：不是靠 prompt 约束，是靠 state 通道的合并规则。`stream.py` 里 `_final_answer` 的注释也是这个道理 —— 不会串味，因为子 Agent 的消息压根不在主 state 里。

### Day 6 — 第一次自己定义 State

`DBQueryState(FilesystemState)` 是全项目唯一一处手写的 state schema。三点值得讲：

1. **继承 `FilesystemState` 而不是裸 `AgentState`** —— 不继承的话 state 里没有 `files` 通道，`offload_if_large()` 会在 `_backend.write()` 那里静默失败，退回截断（`_offload.py` 的 warning 文案就是专门为这个场景写的）。
2. **`schema_cache` 是"用 state 换模型调用"的典型** —— `load_schema` 节点用一条普通 SQL 查 `information_schema`，毫秒级、零模型开销，把结果灌进 state；`db_agent` 每轮把它拼进 system prompt。不这么做，模型得 `list_sql_table` → `describe_table` 两轮往返、四五十秒。
   注意它写在 state 里而不是模块级缓存：**per-thread 隔离，且能随 checkpoint 恢复**。真正的跨 thread 缓存在 `schema_cache.load_schema` 内部做三级（内存→磁盘→探测）。
3. **`sql_attempts` 是状态机的刹车片** —— 两个节点会 +1：`rewrite_sql`（SQL 被安全检查拦下）和 `count_result`（SQL 合法但查回 0 行）。第二处是后补的，注释里记了真实事故：11 条合法 SQL 全 0 行，计数器纹丝不动，模型无限试探。**限流的计数器必须覆盖所有失败形态，不只是报错那种。**

### Day 7 — HITL：state 快照 + interrupt 恢复

`interrupt()` 的本质是：**把当前 state 存成 checkpoint，抛 `GraphInterrupt` 冒到最外层，等外部带 `Command(resume=...)` 再从这个节点重跑。**

由此推出三条你必须能解释的设计：

- **`approve_sql` 节点必须无副作用** —— 恢复时整个节点从头重跑一遍，`interrupt()` 之前写库就写两次。
- **`GraphBubbleUp` 必须放行** —— `observability.py` 两个中间件都专门 `except GraphBubbleUp: raise`。中断不是失败，是控制流信号；抓住它会误报 `tool_error`，前端显示"派发子 Agent 失败"，实际只是在等审批。
- **edit 决策用 `model_copy` 保留 id** —— 因为 `add_messages` 遇到同 id 是**覆盖**。这是 Day 2 那个 reducer 语义在这里兑现。

多中断的 resume 形态（`{中断id: 决策}`）也是 state 层面的约束：一轮派出多个子 Agent，每个都停在自己的审批点，state 里同时挂着多个 pending interrupt，LangGraph 无从知道你的单值 resume 是给谁的。

### Day 8 — 自己往 state 上挂字段

`BudgetState(AgentState)` 加了 `tokens_used` / `cost_usd`。这一天的核心知识点是**写 state 的两种姿势**：

| 场景 | 写法 | 为什么 |
|---|---|---|
| `before_model` / `after_model`（是节点钩子） | 返回 dict `{"tokens_used": n}` | 钩子的返回值就是 state 增量 |
| `awrap_model_call`（是包装器，不是节点） | `ExtendedModelResponse(command=Command(update={...}))` | 包装器没有"返回增量"的位置，只能把 update 塞进 Command 捎带回去 |

熔断那一步同时干了两件事：往 `messages` 塞一条对用户交代的 AIMessage，并置 `jump_to="end"`（靠 `@hook_config(can_jump_to=["end"])` 授权）。**`jump_to` 是一个"控制流字段"** —— 它长得像 state key，实际是路由信号，用完即弃。

还有个 state 之外但相关的坑：`_extract_usage` 取不到 `usage_metadata` 时预算形同虚设，所以 `build_chat_model` 必须开 `stream_usage=True`（OpenAI 协议下 `stream=True` 默认不返回 usage）。**没有输入，state 里的累加器就是个永远为 0 的摆设。**

### Day 9 — 一天没碰 state

RAG 流水线（`store` / `retriever` / `rag_tools`）全程无 state 字段：检索结果通过 ToolMessage 进 `messages`，向量库在 `data/chroma/`，retriever 挂在 `AgentDeps` 上。

三链路 fallback 写在 system_prompt 里而不是代码 if/else，也意味着**降级路径不落 state** —— 模型每轮自己看历史决定要不要换链路。`knowledge_base.py` 里 retriever 为 None 时替换成降级版 `rag_search` 工具，是**构建期**的分支，同样和 state 无关。

这一天值得答的反而是："什么不该进 state。"

### Day 10 — 直接对 state 的 messages/files 通道动刀

三层上下文策略，每一层作用在不同的 state 通道上：

| 层 | 动的通道 | 触发 | 代价 |
|---|---|---|---|
| 卸载 Offload | 写 `files`，`messages` 里只留 200 字 | 单条工具结果 > 4KB | 多一次 `read_file` |
| 摘要 Summarization | 压缩 `messages` | 总 token > 60K | 一次 LLM 调用 + 信息损失 |
| 裁剪 ContextEditing | 把旧 ToolMessage 内容换成 `[cleared]` | 总 token > 80K | 不可恢复 |

**60K < 80K 的顺序是有意的**：反过来配的话，工具结果先被 `[cleared]`，摘要器看到一堆 `[cleared]` 什么也总结不出来。

`exclude_tools=["write_todos"]` 是在保护 `todos` 相关的消息 —— 计划被裁掉，agent 就忘了自己在干什么。

同一天的 `list_past_reports` 是"**用拉代替推**"：记忆是推的（每轮自动进 state / 上下文），索引是拉的（只在模型调工具时才读磁盘）。这就是你砍掉 L3 长期记忆的论据 —— 拉的那种零膨胀风险，且能拿到完整历史。

### Day 11 — 从 state 里把最终答案捞出来

`_final_answer` 那段踩坑注释是这一天最有价值的 state 知识：

**一条 AI 消息可以同时带正文和 tool_calls。** 旧写法"倒着找第一条没有 tool_calls 的 AI 消息"，捞到的是"我已完成查询，如还有问题请随时告诉我"，正文全丢。现在改成从 `aget_state(config)` 拿 messages，从尾往回走到 HumanMessage 为止，把中间所有 AI 正文拼起来。

**为什么读 checkpoint 而不用流式拼接的 `final_text`？** 流式拼接混进了子 Agent 的 token 和中间轮次；checkpoint 里的主图 messages 是干净的、权威的。流式拼接只作兜底。

同一天的 `current_thread_id` contextvar 是又一个"不进 state 的状态"：它只服务日志，跟对话内容无关。

---

## 3. 一条请求的 state 全链路

```
HTTP /task  →  TaskService.submit          写 TaskRecord（进程状态）
                  └ RunContext(thread_id, session_dir)   ← 每请求，只读，不落盘
                      └ agent.astream(input, config={thread_id}, context=ctx)
                          │
                          ├ BudgetMiddleware.before_model   读 tokens_used/cost_usd → 可能 jump_to=end
                          ├ 模型节点                         写 messages（+ 可能 tool_calls）
                          │   └ awrap_model_call            Command(update={tokens_used,cost_usd})
                          ├ SqlGuard.awrap_tool_call        非法 SQL → 直接写一条 error ToolMessage
                          ├ ToolNode                        写 messages；大结果 → 写 files(/scratch/)
                          ├ write_todos                     写 todos → 触发 plan_update 事件
                          └ task(子Agent)                   子图独立 state；files 合并回来、messages 不回来
                                └ DBQueryState              schema_cache / sql_attempts / interrupt
                          │
                          └ 每步落 checkpoints.sqlite ── 崩溃/中断后从这里恢复
                  最终 aget_state(config) 读回 messages → task_result 事件
```

---

## 4. 现状里三个可以顺手收掉的点

1. **`DBQueryState.pending_sql` 是死字段** —— 全项目无人读写。要么删掉，要么就用它把"待审批的 SQL"显式存下来（现在是从 `messages[-1].tool_calls[0]` 现场取，语义上更隐晦）。
2. **`plan_update` 双发** —— `observability.py:aafter_model` 和 `stream.py` 的 updates 分支各推一次，两边去重签名互不知情。
3. **`schema_cache` 只在数据库子图里** —— 主图看不到表结构，所以主 Agent 无法判断"这个问题库里有没有数据"，只能盲派。如果要优化，可以让子图把一句话的 schema 摘要通过返回值带回主图。

---

## 5. 面试时的三句话版本

> 项目里有四类状态，我按"谁读它"分层：图 State 是模型要看、要恢复的，走 checkpointer；RunContext 是每请求只读的，走 context_schema；依赖容器和任务记录是进程级的，绝不进 state。
>
> 图 State 我扩展过两次：主图加了 `tokens_used`/`cost_usd` 做预算熔断，数据库子图自定义了 `schema_cache`（用一条毫秒级 SQL 换掉两轮模型探路）和 `sql_attempts`（覆盖"报错"和"零结果"两种失败形态的刹车片）。
>
> State 膨胀我用三层压制，分别作用在不同通道：大结果卸载到 `files`、历史摘要压 `messages`、机械裁剪兜底，阈值 4KB / 60K / 80K，顺序不能反 —— 先裁后摘的话摘要器只能看到一堆 `[cleared]`。

---

*出处：`app/agents/{context,deps,main_agent,stream}.py`、`app/agents/subagents/database_query.py`、`app/middleware/{budget,sql_guard,observability,stack}.py`、`app/tools/_offload.py`、`app/services/{task,session}_service.py`、`data/mydataS/PHASE2_DEEPAGENT_PLAN.md` §1.6、`docs/context_strategy.md`*
