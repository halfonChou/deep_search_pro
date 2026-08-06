# DeepSearch Pro — 开发 + 掌握 + 面试：14天一体化计划

> ## 这份文档怎么用
>
> **本文件 = 日程表。** 每天做什么、时间怎么分、理解闭环练什么、决策日记问什么，看这里。
>
> **技术细节 = `PHASE2_DEEPAGENT_PLAN.md`。** 接口签名、中间件装配顺序、bug 行位与修法、每天的验收标准、架构决策依据（含 §1.6 文件与记忆三层），全在那一份。
>
> 两份文档的 Day 编号一一对应。**开工看本文件，写代码查 PHASE2。**

> **核心原则：每天的最后40分钟是"理解闭环"，不是额外任务，是当天开发的一部分。**
> 刚写完的代码最热，这时候关掉AI做理解练习，效果比事后补课高5倍。
>
> **时间预算：** 每天5-6小时 = 开发4-4.5h + 理解闭环40min + 决策日记10min
>
> **整体节奏：**
> - Day 1-11：跟着 PHASE2 计划开发，每天嵌入理解闭环
> - Day 12-13：面试专项准备
> - Day 14：模拟面试 + 查漏补缺
> - Day 14 之后：投递 + 持续迭代

---

## 每日理解闭环的标准流程（40分钟）

每天开发完成后，在收工前做以下三步。**关掉AI，关掉代码编辑器。**

| 步骤 | 时间 | 做什么 |
|------|------|--------|
| ①画 | 10min | 凭记忆画出今天写的模块的数据流/结构图，画不出来的打❓ |
| ②破 | 20min | 回到代码，做1个破坏实验（改一个参数/注释一个组件，跑，观察后果） |
| ③记 | 10min | 填当天的决策日记模板（3个问题，每个≤3句话） |

**❓标记的地方就是你下次开AI继续写代码时要优先搞清楚的。**

---

## Week 1：核心骨架（Day 1-6）

---

### Day 1 — 地基修复：6个bug + 探测 + 循环依赖

#### 开发内容（4h）
完全按 PHASE2 Day 1 执行：
- `probe_api.py` 探测真实API签名
- 修 B1-B6（重点是 B5 路径穿越高危漏洞）
- 建 `agents/deps.py` + `agents/context.py`
- 扩 `config.py` 配置项（含 §1.6 的文件分层 5 项：`offload_threshold_bytes` / `scratch_dir` / `report_index_file` 等）
- 验收全绿

#### 理解闭环（40min）

**①画（10min）：** 关掉编辑器，画出你改完之后的项目目录结构，标注每个文件夹的职责。重点画清楚 `agents/deps.py` 和 `agents/context.py` 解决了什么依赖关系。

**②破（20min）：** 做一个B5漏洞的攻防实验——
```
把你的修复代码注释掉，恢复原来的 session_dir: Path = Query(...)
然后用 curl 构造一个 session_dir=C:\ 的请求
观察你能读到什么文件
```
亲眼看到漏洞的威力，这个安全知识就是你的了。然后恢复修复。

**③记（10min）：**
```
决策日记 Day 1
Q1：RunContext 解决的核心问题是什么？（不用 RunContext 的话 thread_id 怎么传？）
A1 让中间件和工具能拿到当前请求的 thread_id 和 session_dir。调用 agent 时通过 context=RunContext(...) 传入一次，所有中间件和工具通过 runtime.context.thread_id 统一读取。不用给每个工具加参数，也不用隐式全局变量。

Q2：B5 漏洞的根因是什么？（一句话）
A2 session_dir 由客户端任意指定，服务端没有校验其合法性。攻击者传入 session_dir=C:\ 即可读写全盘。根因是信任了不可信的输入——安全边界（_safe_resolve）建立在攻击者可控的锚点上，等于没有边界。修法：改为服务端从 thread_id 推导路径，客户端只传 ID。。

Q3：为什么 AgentDeps 要从 main_agent.py 迁到独立文件？
A3：AgentDeps 是 agents 和 tools 都需要引用的公共定义。放在 main_agent.py 里会形成 agents → tools → agents 的循环依赖。搬到独立的 agents/deps.py 后，它只依赖 config 和 infra，agents 和 tools 都可以安全导入它，依赖方向变成单向。
```

---

### Day 2 — 编译第一个 deep agent + checkpointer

#### 开发内容（4h）
按 PHASE2 Day 2：
- `checkpoint.py`（AsyncSqliteSaver + WAL）
- 重写 `build_main_agent` 返回真正的 CompiledStateGraph
- `main.py` lifespan 装配
- 验证多轮记忆

#### 理解闭环（40min）

**①画（10min）：** 画出请求进来到 agent 响应的完整链路：
```
FastAPI endpoint → lifespan 里的 app.state.agent → create_deep_agent 内部发生了什么 → checkpointer 在哪个环节介入


启动：uvicorn -> 创建异步sqlite -> 创建deepagent -> 挂载到app.state.agent
请求：用户 -> fastapi ->state.agent -> invoke -> checkpoint读 ->执行 -> checkpoint写 -> 反馈
```

**②破（20min）：** WAL实验——
```
实验1：用 sqlite3 命令确认 journal_mode 是 wal
实验2：把 PRAGMA journal_mode=WAL 注释掉，同时开两个 thread_id 发请求
       观察有没有 "database is locked" 错误
实验3：恢复 WAL，重复实验2，确认不报错了
```

**③记：**
```
决策日记 Day 2
Q1：为什么 agent 是单例而 thread_id 通过 context 传入？（反过来每次请求建新 agent 会怎样）
A1：create_deep_agent 要编译整个图结构，有性能开销。每次请求都要新建agent会浪费大量资源，但是agent本身并没有state，不同用户的对话状态都存在checkpoint里面按照thread_id进行存储，一个agent实例就可以服务所有用户

Q2：WAL 解决的具体问题是什么？（你实验2看到了什么现象）
A2：sqlite默认模式下，写操作会锁住整个数据库，其他链接读写都不行。在多用户同时对话时，一个用户状态会导致其他用户的请求报：database is locked。WAL模式让写操作写到单独的日志文件里面，不会阻塞读操作。
Q3：create_deep_agent 默认栈里有哪些中间件？（至少说出3个）
A3：todolist中间件 提供写todos工具，让工具可以制定和更新任务计划
	filesystem中间件，提供读写文件等工具，让gaent可以读写虚拟文件系统
	summarize中间件 对话历史超过token阈值会使用LLM摘要压缩，防止上下文溢出
```

---

### Day 3 — 自研中间件① EventEmitMiddleware

#### 开发内容（4h）
按 PHASE2 Day 3：
- 写 EventEmitMiddleware（观测中间件）
- 写 stream.py（流式桥接）
- **删除** 三个工具文件里所有 emitter.emit 埋点（从8处收敛到1处）
- 验收：grep 确认埋点全删

#### 理解闭环（40min）

**①画（10min）：** 画事件流的完整链路：
```
agent 内部行为 → EventEmitMiddleware 的哪个hook捕获 → AgentEvent → EventBus → ???（今天还没有WebSocket，事件到EventBus就停了）
```
标注：wrap_tool_call 和 after_model 分别在什么时机触发。

**②破（20min）：** thread_id路由实验——
```
把 _tid() 方法改成 return "hardcoded"
跑一个查询，看事件的 thread_id 是不是变成了 "hardcoded"
思考：如果所有事件的 thread_id 都一样，多会话时会怎样？
恢复原代码
```

**③记：**
```
决策日记 Day 3
Q1：观测中间件为什么要放在栈的最外层？（如果放内层，量到的耗时有什么问题）
A1：观测中间件放到最外层，英文wrap-style是嵌套的，第一个包住后面所有中间件，放到最外层才能
①量到包括重试在内的真实耗时，工具的失败，重试这些在外层看来是一次调用的，放到内层只能看到单次尝试，无法看到总耗时
②可以看到所有内层中间件的动作，并且进行观测

Q2：删掉工具里8处埋点的好处是什么？（只说"解耦"不够，要具体）
A2：①扩展强 加一个工具不需要增加观测，只要工具在图里面就一定会被观测到
	②分别维护 如果需要给事件加通道或者换字段 只需要修改一个文件即可
	③ 相比之前的硬编码 id=“”，所有会话混进一个消息队列里面，中间件可用获取真实的id
	④工具回归业务 工具下载只关系其具体的业务功能，不再关心发事件等其他业务

Q3：awrap_tool_call 里 raise 之前先发 tool_error 事件，为什么不吞异常？
A3："EventEmitMiddleware 是观测中间件，职责是记录而不是决策。吞掉异常会让内层的 ToolRetry 看不到失败、重试永不触发；还会让 agent 误以为工具成功，基于错误结果继续执行。所以正确的做法是：先发 tool_error 事件把'失败'记下来，再原样 raise，把决策权交还给内层。"
```

---

### Day 4 — TaskService + WebSocket 网关

#### 开发内容（4h）
按 PHASE2 Day 4：
- TaskService（提交/查状态/取消）
- SessionService（会话目录管理 + `record_report` / `list_reports` 维护 `data/index.jsonl`）
- WebSocket 网关
- EventBus 改 fan-out

#### 理解闭环（40min）

**①画（10min）：** 画出一个任务从提交到结果返回的生命周期：
```
POST /task → TaskService.submit → asyncio.create_task → agent运行 → 事件产生 → EventBus → WS /ws/{thread_id} → 前端
```
标注：取消、审批中断分别在哪个环节发生。

**②破（20min）：** 晚连接实验——
```
先通过 POST /task 提交一个任务
等3秒（任务已经在跑，已经产生了事件）
然后才连 WebSocket
观察：能不能收到之前的事件？
（这验证了 EventBus 的缓冲机制是否真的有效）
```

**③记：**
```
决策日记 Day 4
Q1：为什么要改 fan-out 而不是保持单 Queue？（多客户端订阅同一个 thread 会怎样）
A1：

Q2：TaskService 为什么用信号量限并发？（不限会怎样）
A2：

Q3：任务取消后为什么要确认 DB 连接归还？（不确认的后果是什么）
A3：

Q4：index.jsonl 里为什么只存一句话摘要 + 路径，不存报告全文？
A4：
```

---

### Day 5 — 声明式子 Agent（网搜 + 知识库桩）

#### 开发内容（4h）
按 PHASE2 Day 5：
- 两个声明式子 Agent 工厂
- description 按三原则精修
- 挂 subagents 到主 Agent
- **主 prompt 追加「文件使用规则」**（草稿走 `write_file` 到 `/scratch/`，交付走 `generate_markdown`。见 PHASE2 §1.6 与 Day 5 的坑）
- 手动测路由

#### 理解闭环（40min）

**①画（10min）：** 凭记忆画出主 Agent 和三个子 Agent 的关系图：
```
主 Agent (deepagents)
├── network-search (声明式 dict) → 持有什么工具？
├── knowledge-base (声明式 dict/桩) → 持有什么工具？
└── database-query (Day 6 才写) → 为什么不能用声明式？
```

**②破（20min）：** 误路由实验——
```
把 network-search 的 description 改成一句很泛的话，比如"搜索各种信息"
然后问："上季度销量下降超20%的药品"（这应该走数据库）
观察：是不是误路由到了 network-search？
记录误路由的具体表现
恢复原 description
```
这个实验能让你亲眼看到 description 的写法直接决定路由质量。

**②-2 破（额外 10min）：** 两套文件系统实验——这个坑不亲眼踩一次记不住。
```
把主 prompt 里刚加的「文件使用规则」整段注释掉
让它跑一个"出一份布洛芬分析报告"的任务
等它回复"报告已生成"之后：
  ① 看 data/sessions/<thread_id>/  → 大概率是空的
  ② 让它 read_file 刚才那个文件名 → 能读到，内容在
结论：文件确实写了，但写进了虚拟文件系统（落在 checkpoints.sqlite 里），
      用户通过 /files/download 永远拿不到。
恢复 prompt，再跑一次，确认 data/sessions/ 里有 .md 文件了。
```

**③记：**
```
决策日记 Day 5
Q1：description 三原则各解决什么问题？（每条一句话）
A1：

Q2：为什么网搜和知识库用声明式 dict，不用手写 StateGraph？
A2：

Q3：你的误路由实验观察到了什么？改回好的 description 后路由恢复了吗？
A3：

Q4：write_file 和 generate_markdown 写到了哪两个地方？为什么要分开？
A4：
```

---

### Day 6 — 数据库子 Agent：原生 StateGraph

#### 开发内容（4.5h）
按 PHASE2 Day 6（这天最重，多给30分钟）：
- DBQueryState 四个自定义字段
- 四节点 StateGraph + 条件路由
- CompiledSubAgent 挂回主 Agent
- 验收端到端

#### 理解闭环（40min）

**①画（10min）：** 这是最关键的一次画图。画出数据库子图的完整状态机：
```
START → db_agent → [条件路由]
                     ├── 有 tool_call 且合法 → db_tools → db_agent
                     ├── SQL 校验失败 → rewrite_sql → db_agent
                     ├── 改写次数超限 → give_up → END
                     └── 没有 tool_call → END
```
每个箭头旁标注触发条件。

**②破（20min）：** 非线性路由实验——
```
实验1：把 route_after_db_agent 的 rewrite_sql 分支注释掉（校验失败直接走END）
       喂一条不合法的SQL，观察：是直接失败了还是有机会改写？
实验2：把 MAX_SQL_ATTEMPTS 改成 1
       喂一条需要改写2次才能通过的查询
       观察：是不是第1次改写后就走 give_up 了？
恢复原代码
```

**③记：**
```
决策日记 Day 6
Q1：DBQueryState 的四个字段，哪些是"必须下沉到原生 StateGraph"的证据？
A1：

Q2：子图为什么不传 checkpointer？（传了会怎样）
A2：

Q3：rewrite_sql 节点和让模型自己重试有什么区别？（为什么不直接回 db_agent 让模型再来一遍）
A3：
```

---

## Week 2：能力补齐 + 联调（Day 7-11）

---

### Day 7 — HITL + 自研中间件② SqlGuardMiddleware

#### 开发内容（4h）
按 PHASE2 Day 7：
- SqlGuardMiddleware
- interrupt_on 配置
- TaskService.decide() + REST审批接口
- 删除工具内安全校验代码

#### 理解闭环（40min）

**①画（10min）：** 画出一条 SQL 从 LLM 生成到实际执行的完整安全链路：
```
LLM 输出 SQL → [____] → [____] → [____] → MySQL 执行
```
标注：SqlGuardMiddleware 在哪一环、HITL 中断在哪一环、如果两个都触发，顺序是什么。

**②破（20min）：** 这是整个计划里最有价值的攻防实验——
```
准备3个SQL注入payload：
1. SELECT * FROM sales -- ; DROP TABLE sales
2. SELECT * FROM sales; DROP TABLE sales
3. SELECT name FROM sales UNION SELECT password FROM users

逐个喂给系统，记录：
- 每个被拦在哪一层？
- 日志里安全拦截出现了几次？（应该是1次，不是3次，因为在重试外层）
- 总耗时是多少？（应该<100ms，因为没有重试等待）
```

**③记：**
```
决策日记 Day 7
Q1：安全校验从工具内移到中间件的核心好处是什么？（"解耦"之外的具体好处）
A1：

Q2：SqlGuard 放在重试外层——你的实验证据是什么？（拦截次数和耗时）
A2：

Q3：ToolMessage status="error" 比返回普通字符串好在哪？
A3：
```

---

### Day 8 — 弹性重试 + 调用限制 + 自研中间件③ BudgetMiddleware

#### 开发内容（4h）
按 PHASE2 Day 8：
- BudgetMiddleware + BudgetState
- stack.py 完整装配（5内置 + 3自研）
- build_fallback_models
- 故障注入验证

#### 理解闭环（40min）

**①画（10min）：** 画中间件洋葱图。把 stack.py 里的完整栈画成洋葱圈结构：
```
请求进来 →
  [EventEmit] →
    [Budget] →
      [ModelCallLimit] →
        [ToolCallLimit] →
          [SqlGuard] →
            [ToolRetry] →
              [ModelRetry] →
                [ModelFallback] →
                  [ContextEditing] →
                    实际模型/工具调用
                  ← 响应出来
                ←
              ←
            ←
          ←
        ←
      ←
    ←
  ←
← 最终响应
```
在每两层之间标注：为什么A在B外面。

**②破（20min）：**
```
把 BudgetMiddleware 和 ToolRetryMiddleware 的位置对调
然后设一个很低的预算上限（比如1000 token）
喂一个会触发工具重试的请求
观察：预算已耗尽时，重试还在继续吗？
（应该会继续，因为 Budget 在内层看不到外层的重试）
恢复原代码
```

**③记：**
```
决策日记 Day 8
Q1：次数限制和 token 预算的区别是什么？（举一个次数限不住但 token 能限住的例子）
A1：

Q2：retry_on 为什么排除 ValueError？
A2：

Q3：BudgetState 为什么放 state 而不是实例变量？（实例变量的两个问题是什么）
A3：
```

---

### Day 9 — RAG Pipeline + 三链路 fallback

#### 开发内容（4.5h，预留缓冲）
按 PHASE2 Day 9：
- embedder / store / ingest / retriever 四件套
- rag_tools + 知识库子 Agent 桩换真实
- scripts/build_index.py
- fallback 验证

#### 理解闭环（40min）

**①画（10min）：** 画RAG pipeline的完整数据流：
```
PDF/文档 → [解析] → [切分，参数：chunk_size=?, overlap=?] → [Embedding，模型=?，维度=?] → [ChromaDB 存储]
用户查询 → [Embedding] → [ChromaDB 检索，top_k=?, 距离度量=?] → [命中/零命中] → [返回结果/降级到网搜]
```
每个方括号里填你实际用的参数值。

**②破（20min）：**
```
构造一个知识库肯定没有的问题，比如"2026年GLP-1类药物市场规模"
观察完整链路：
- 系统走了哪条路？是不是先查知识库、零命中后自动转网搜？
- 最终回答里有没有标注来源性质？
- 如果把降级策略从 prompt 里删掉（那段 FALLBACK_INSTRUCTION），系统会怎么处理零命中？
```

**③记：**
```
决策日记 Day 9
Q1：中文分隔符为什么要加"。"、"；"、"，"？（默认英文分隔符对中文的问题是什么）
A1：

Q2：降级策略为什么写进 prompt 而不是硬编码 if/else？
A2：

Q3：chunk_size 和 overlap 你用的值是多少？为什么？（如果不确定为什么，诚实写"AI建议的，还没验证"）
A3：
```

---

### Day 10 — 上下文管理：摘要 + 裁剪 + 落盘卸载

#### 开发内容（4h）
按 PHASE2 Day 10：
- 大结果落盘逻辑（`offload_if_large`，**落到 `/scratch/` 不是会话目录**）
- 确认默认栈摘要中间件参数
- ContextEditingMiddleware 配置
- `list_past_reports` 工具（§1.6 里「用拉代替推」，它替代了本来要做的长期记忆）
- 长对话验证三层依次触发

#### 理解闭环（40min）

**①画（10min）：** 画三层策略的触发关系图：
```
消息进来
  → 单条工具结果 > 4KB？→ 是 → 落盘，只回摘要+路径
  → 总 token > 60K？→ 是 → LLM 摘要压缩
  → 总 token > 80K？→ 是 → ContextEditing 机械裁剪旧工具输出
```
在图旁标注：为什么 60K < 80K（摘要阈值低于裁剪阈值的原因）。

**②破（20min）：**
```
实验：把摘要阈值和裁剪阈值对调（摘要80K，裁剪60K）
跑一个多轮对话（至少5轮，每轮都有大搜索结果）
观察：摘要器收到的输入是什么？
是正常文本还是一堆 [cleared]？
恢复原代码
```

**③记：**
```
决策日记 Day 10
Q1：三层策略的顺序为什么是 落盘→摘要→裁剪？（反过来会怎样）
A1：

Q2：为什么 write_todos 结果不能被裁剪？
A2：

Q3：你的"阈值对调"实验看到了什么现象？
A3：

Q4：为什么这个项目不做长期记忆，而是用 list_past_reports 这个查询工具替代？
   （提示：记忆是"推"的，每轮自动进上下文；索引是"拉"的，只在被调用时读）
A4：
```

---

### Day 11 — 端到端联调 + 可观测性 + 收尾

#### 开发内容（4.5h）
按 PHASE2 Day 11：
- print → logging + contextvars
- LangSmith 追踪（截图存档！）
- 集成测试
- README
- 全量 ruff + pytest

#### 理解闭环（40min）

**①画（10min）：** 最后一次全局架构图。关掉一切，凭记忆画出完整系统：
```
FastAPI → TaskService → Agent(deepagents)
                          ├── 中间件栈（画出9层顺序）
                          ├── 子Agent: network-search (声明式)
                          ├── 子Agent: knowledge-base (声明式)
                          └── 子Agent: database-query (StateGraph)
                                         ├── db_agent
                                         ├── db_tools
                                         ├── rewrite_sql
                                         └── give_up
WebSocket ← EventBus ← EventEmitMiddleware
Checkpointer(SQLite+WAL) ↔ 多轮记忆 + HITL中断恢复
```
画不出来的地方打❓——这些❓就是Day 12-13面试准备要攻的点。

**②破（20min）：** 做一次完整的端到端破坏实验——
```
同时发3个不同的查询（3个不同的 thread_id）
观察：
1. 日志里每行都带 thread_id 吗？能区分吗？
2. LangSmith trace 里三个任务是分开的吗？
3. 事件有没有串台？
```

**③记：**
```
决策日记 Day 11
Q1：contextvars 解决了什么问题？（为什么不用 threading.local）
A1：

Q2：你的全局架构图哪里画不出来？列出所有❓
A2：

Q3：如果让你给一个新人讲这个项目，你会从哪里开始讲？（写出你的讲解顺序）
A3：
```

---

## Day 12-13：面试专项准备

到这一天，项目已经完整跑通。接下来的目标从"做出来"切换到"讲得出来"。

---

### Day 12 — 从零重写 + 弱点突击（5h）

#### 上午：核心模块重写（2.5h）

从以下列表中选 **2个**，**关掉AI、不看原代码**，从空文件写到能跑：

| 模块 | 对应Day | 建议优先级 |
|------|---------|-----------|
| 3节点简化版 StateGraph（db_agent → db_tools → rewrite_sql） | Day 6 | 最高——面试必问 |
| SQL白名单校验器（去注释→去字符串→首词白名单→关键字集合） | Day 7 | 高——能展示安全意识 |
| 重试装饰器（指数退避+抖动+只重试瞬时异常） | Day 8 | 高——通用能力 |
| 上下文管理器（大结果截断+旧消息清理） | Day 10 | 中 |
| 简化版事件队列（1生产者→N消费者 fan-out） | Day 4 | 中 |

**规则：** 可以查 LangGraph/Python 官方文档，不可以问AI，不可以看项目代码。每个最多1.5小时。写不出来记录卡在哪里。

#### 下午：攻击 Day 11 的 ❓ 列表（2.5h）

把 Day 11 理解闭环里你标记的所有 ❓，逐个回到对应的代码做一次快速破坏实验。每个❓不超过20分钟：改代码 → 跑 → 观察现象 → 恢复 → 用一句话记录你学到了什么。

---

### Day 13 — 面试问题过堂 + 项目叙事（5h）

#### 上午：11个高频面试题自问自答（2.5h）

**不看任何材料**，对着录音/镜子回答。每个问题限2分钟。

**架构层（对应 Day 2, 5, 6）：**
1. 介绍一下你这个项目的整体架构
2. 为什么主Agent用deepagents、数据库链路用原生StateGraph？
3. 子Agent的路由靠什么？description 你是怎么写的？

**中间件层（对应 Day 3, 7, 8）：**
4. 你的中间件装配顺序是什么？为什么这么排？
5. SQL守卫为什么放在重试外层？
6. 预算中间件和内置次数限流有什么区别？
7. 观测中间件解决了什么问题？之前为什么不好？

**上下文层（对应 Day 10）：**
8. 三层压缩策略是什么？阈值为什么这么设？
9. 如果摘要阈值比裁剪阈值高会怎样？

**工程层（对应 Day 1, 2, 4, 9, 11）：**
10. SQL注入防护是怎么做的？你测过哪些攻击？
11. 前端晚连接怎么保证不丢事件？

**评分标准：**
- A：流畅讲清楚，有实验依据（"我试过把它注释掉，结果……"）
- B：能讲出来但不够顺，个别细节模糊
- C：只能说what，说不出why
- D：卡住

#### 下午：项目叙事打磨 + C/D 补课（2.5h）

**项目叙事（1h）：** 准备一段2分钟的项目介绍，结构如下：
```
第1句：项目是什么（药品行业深度研究，三链路多Agent系统）
第2句：核心技术决策（deepagents编排 + 数据库链路下沉原生StateGraph，为什么）
第3句：我做的最有价值的事（三个自研中间件，各解决什么内置中间件解决不了的问题）
第4句：工程亮点（上下文三层策略 / HITL审批 / 指数退避重试）
第5句：量化（30+配置项 / 12种事件类型 / 5种SQL注入防住了4种 / 等等）
```
对着镜子讲5遍，直到不卡顿。

**C/D 补课（1.5h）：** 上午打了C或D的题，回到对应Day的代码做一次破坏实验。不要重新读代码——直接改代码跑，用现象加深理解。

---

### Day 14 — 模拟面试 + 投递准备（5h）

#### 上午：完整模拟面试（2h）

找同学（或对着录音），模拟30分钟技术面：
- 自我介绍 + 项目介绍（5min）
- 面试官追问（20min，用 Day 13 的 11 个问题随机抽）
- 现场题：面试官给一个小需求，你白板讲思路（5min）

面试后回听录音，把每个卡顿的地方标记出来。

#### 下午：投递材料终检 + 简历微调（3h）

- GitHub README 确认能让新人 30 分钟跑通
- LangSmith trace 截图准备好（中间件嵌套层级、工具耗时）
- 简历用词和实际能力对齐（Day 1-11 决策日记就是对齐依据——你能讲清楚的才写上去，讲不清楚的删掉或弱化措辞）
- 准备一个2分钟的demo视频或GIF（提交查询→看到plan_update→审批→最终报告）

---

## Day 14 之后：投递 + 持续迭代

### 投递期间每天30分钟

从 Day 1-11 的决策日记里随机抽2个问题，不看笔记口头回答。答不出来的花10分钟做一次对应的破坏实验。

### 面试前一天速查

过一遍 Day 13 的 11 个面试题。只过上次打 C/D 的。如果某个从 C 变成了 D（遗忘），跑一次对应的破坏实验，20分钟捡回来。

### 如果有面试反馈

面试后立刻记录被问到但没答好的问题，加入到你的 11 个题库里，Day 13 的逻辑持续迭代。

---

## 决策日记汇总表（打印贴墙上）

| Day | 核心模块 | 破坏实验 | 面试对应问题 |
|-----|---------|----------|-------------|
| 1 | RunContext + 漏洞修复 | B5路径穿越攻防 | Q10 |
| 2 | Checkpointer + WAL | 并发锁实验 | Q1 |
| 3 | EventEmitMiddleware | thread_id硬编码 | Q7 |
| 4 | TaskService + WS + 报告索引 | 晚连接补发 | Q11 |
| 5 | 声明式子Agent + description | 误路由实验 **+ 两套文件系统实验** | Q3 |
| 6 | 原生StateGraph | 非线性路由注释实验 | Q2 |
| 7 | SqlGuardMiddleware + HITL | SQL注入攻防 | Q5, Q10 |
| 8 | BudgetMiddleware + 完整栈 | 栈顺序对调实验 | Q4, Q6 |
| 9 | RAG + fallback | 零命中降级 | Q8（部分） |
| 10 | 上下文三层策略 + 文件三层 | 阈值对调实验 | Q8, Q9 |
| 11 | 联调 + LangSmith | 并发串台测试 | Q1（全局） |

---

## 预期分数轨迹

| 节点 | 面试"答不上来"比例 | 主管评分预估 |
|------|-------------------|------------|
| Day 6 完成（骨架能跑） | ~50% | 5.5-6.0 |
| Day 11 完成（全链路跑通） | ~40% | 6.0-6.5 |
| Day 13 完成（面试准备） | ~20-25% | 7.0 |
| Day 14 完成（模拟面试） | ~15-20% | 7.0-7.5 |
| 持续迭代2周 | ~10% | 7.5-8.0 |

> **关键区别：因为你是边开发边理解的，不是事后补课的，所以同样14天，这个路径比纯开发后再补课的效率高很多。每天40分钟的理解闭环，14天就是额外10小时的刻意练习，而且是在记忆最热的时候做的。**
