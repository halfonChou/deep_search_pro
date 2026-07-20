# deep_search_pro 重构计划

> 目标定位：把一个"教学/原型"阶段的 Agent 系统，重构成一个**扎实的生产级单体**（Phase 1），并规划好"业务增长后如何演进"（Phase 2）。
> 核心原则：**先做地基，后加钢筋**；遵循 YAGNI，不引入当前规模用不到的基础设施。
>
> 已对齐的技术约束：
> - 编排层保留 `deepagents` + `langgraph` 并用
> - RAG 自研（占比不大），替换 `ragflow-sdk`
> - 部署环境：**必须支持 Windows**（Word 转 PDF 依赖 COM）
> - 使用规模：多用户并发（单机足以承载当前阶段）
> - Phase 1 状态存储：**SQLite（checkpoint）+ Chroma（向量）+ 现有 MySQL（业务数据源，只读）**，零新增服务

---

## 1. 背景与目标

### 1.1 项目现状一句话
基于 `deepagents` + `langgraph` 的"深度研究" Agent 系统：FastAPI + WebSocket 后端，主 Agent 编排 3 个子 Agent（数据库查询 / 网络搜索 Tavily / 知识库 RAGFlow）与若干工具（生成 Markdown、MD→PDF、读上传文件），通过全局单例 `monitor` 经 WebSocket 把进度推给前端。

### 1.2 重构目标（做什么）
1. **解耦**：把"业务逻辑 / 框架编排 / 传输层"三者拆开——这是所有问题的总根源。
2. **健壮**：修掉阻塞事件循环、发射后不管、状态易失、启动脆弱等生产阻断级问题。
3. **安全**：SQL 只读白名单、路径校验、CORS 收敛、接口鉴权。
4. **可测试 & 可观测**：分层清晰、依赖注入、pytest 覆盖核心、结构化日志。
5. **可移植但务实**：抽象掉 Windows 强耦合点（Word COM），但当前仍在 Windows 部署。

### 1.3 非目标（这次不做，避免过度设计）
- 不引入消息队列（Celery/RQ/arq）——见 §4.1。
- 不引入 Redis、Postgres、专用向量库——见 §4.2 / §4.3。
- 不做多机横向扩展、不做微服务拆分——留待 Phase 2 且有明确触发条件。
- 不重写前端。

---

## 2. 现状评估（问题清单，按严重程度）

### P0 — 生产阻断级
| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| P0-1 | 同步阻塞调用跑在异步事件循环里（MySQL、RAGFlow SDK、Word COM） | `tools/db_tools.py`、`tools/ragflow_tools.py`、`utils/word_converter.py` | 多用户并发时互相卡死，"并发"名存实亡 |
| P0-2 | `asyncio.create_task` 发射后不管，无追踪/取消/错误回传 | `api/server.py` `run_task` | 任务失败静默、无法取消、异常只能靠 WebSocket 偶发捕获 |
| P0-3 | `/api/task` 与 WebSocket 连接存在竞态 | `server.py` + `main_agent.py` | 任务先跑完，前端还没连上 → 进度/结果丢失 |
| P0-4 | `InMemorySaver` 状态存内存 | `agent/main_agent.py` | 进程重启即丢，无法多进程，会话不可恢复 |

### P1 — 严重
| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| P1-1 | `execute_sql_query` 允许 LLM 执行任意 SQL | `tools/db_tools.py` | 可 DROP/DELETE/UPDATE，数据安全风险 |
| P1-2 | `get_table_data` 用 f-string 拼表名 | `tools/db_tools.py` | SQL 注入 |
| P1-3 | 依赖方向倒置：`tools/*` 反向 import `api.monitor` / `api.context` | 全部工具 | 无法单测、循环耦合、复用困难 |
| P1-4 | 导入即执行副作用：`prompts.py` 顶层 print/读盘、`ragflow_tools.py` 顶层建客户端、`main_agent.py` 顶层建 Agent | 多处 | RAG 挂掉 → 整个应用起不来；无法测试 |
| P1-5 | CORS `allow_origins=["*"]` 且 `allow_credentials=True` | `api/server.py` | 安全配置错误（该组合浏览器实际会拒绝，且过宽） |
| P1-6 | 全部接口无鉴权 | `api/server.py` | 任何人可提交任务、下载文件 |

### P2 — 工程质量
| # | 问题 | 后果 |
|---|---|---|
| P2-1 | 满屏 `print`，无结构化日志 | 生产无法排查 |
| P2-2 | 无测试，散落 `if __name__` 与 `tools/test_session_123` 遗留物 | 回归无保障 |
| P2-3 | `output/`、`updated/`、`deep_agent_02_fixed.py` 等进 git | 仓库臃肿、会话数据泄漏 |
| P2-4 | 会话目录无 TTL、无清理；上传文件从 `updated/` 复制到 `output/` 造成冗余 | 磁盘无限增长 |
| P2-5 | `run_deep_agent` 靠 `node_name=='model'`、`tool_call['name']=='task'` 硬解析库内部结构 | deepagents 升级即碎 |
| P2-6 | `rawflow/`（demo）与生产代码混在一起 | 边界不清 |

---

## 3. 目标架构（Phase 1）

### 3.1 形态：分层清晰的生产级单体（单进程）
一个 FastAPI 进程即可，但内部严格分层、依赖单向向下。长任务用后台执行 + 进程内事件总线推 WebSocket；两个阻塞点（MySQL、Word）分别用异步驱动和子进程池隔离。

```
┌─────────────────────────────────────────────────────────┐
│ 接口层 API        FastAPI Routers · Schemas · Auth · WS   │
├─────────────────────────────────────────────────────────┤
│ 应用层 Services   TaskService · SessionService · 用例编排  │
├─────────────────────────────────────────────────────────┤
│ 领域层 Agents     deepagents 高层编排 + langgraph 精细控制  │
│                   EventEmitter 抽象（依赖注入，非全局单例） │
├─────────────────────────────────────────────────────────┤
│ 工具层 Tools      SQL · WebSearch · RAG检索 · 文档生成      │
│ RAG 模块          摄取→分块→嵌入→Chroma 检索（自研）        │
├─────────────────────────────────────────────────────────┤
│ 基础设施 Infra    Config · Logging · 异步MySQL池 ·          │
│                   SQLite Checkpoint · Chroma · PDF子进程    │
└─────────────────────────────────────────────────────────┘
       依赖方向：上层依赖下层，下层不知道上层
       事件回流：工具/Agent 只调用注入的 emit()，由 Infra 决定推给谁
```

### 3.2 核心解耦手段：EventEmitter 抽象
把全局单例 `monitor` 替换为一个接口：

```python
class EventEmitter(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...
```

- **生产实现**：`WebSocketEmitter`——把事件放进该 `thread_id` 的进程内 `asyncio.Queue`，WebSocket 端消费转发。
- **测试实现**：`RecordingEmitter`——把事件收集到 list 里断言。
- **脚本实现**：`ConsoleEmitter`——打印到控制台。

工具和 Agent 只接收 `emitter` 参数，**不再 import 任何 api 模块**，依赖方向就此矫正。这也顺带解决 P0-3 竞态：事件先落进程内队列，前端晚连也能拉到缓冲。

### 3.3 阻塞隔离
- **MySQL**：换异步驱动 `asyncmy`（或 `aiomysql`）+ 连接池；查询全部参数化。
- **Word→PDF**：COM 是 STA 单线程阻塞模型，放进 `ProcessPoolExecutor`（每个子进程 `pythoncom.CoInitialize()`），主事件循环 `await loop.run_in_executor(...)`。
- **转换器抽象**：`PdfConverter` 接口 → `WordPdfConverter`（Windows 实现）。将来上 Linux 只需加一个 `WeasyPrintPdfConverter`，不动上层。

### 3.4 长任务执行模型（不引入队列的前提下）
- `POST /api/task` 立即返回 `thread_id`；任务用一个受管的后台执行器运行（内部维护 `dict[thread_id, asyncio.Task]`），支持查询状态、取消。
- 提供 `POST /api/task/{id}/cancel` 与 `GET /api/task/{id}` 补上 P0-2。
- 用 `asyncio.Semaphore` 限制同时运行的 Agent 数，防止资源耗尽。

---

## 4. 关键设计决策 · 工业界依据 · 何时升级

> 这一节是重点：不仅给结论，更说明工业界怎么做、为什么这么选、以及"什么信号出现时该换"。

### 4.1 任务执行：Phase 1 用后台执行器，不用队列
- **工业界现状**：Python 任务队列里 **Celery** 是事实标准（占有率第一）；异步 FastAPI 圈子里 **arq** 更地道；**RQ** 是轻量替代；**Dramatiq** 是更现代的选择。
- **为什么 Phase 1 不上**：Agent 工作是 **IO 密集**（大部分时间在等 LLM/搜索 API 返回），不是 CPU 密集；队列的价值（重试、定时、跨机分发、削峰）你现在都用不到。过早引入 = 多一套 Broker 运维 + 部署复杂度，是典型的过度设计。
- **升级触发条件（Phase 2 上 arq/Celery + Redis）**：① 要多机部署分摊负载；② 需要任务重试/定时/持久化队列；③ 单机内存/CPU 扛不住并发任务数。
- **Windows 注意**：Celery 的 prefork 池在 Windows 不可用，需 `--pool=threads/solo`；`arq` / `RQ` 在 Windows 更省心。

### 4.2 Agent 状态持久化：Phase 1 用 SQLite Saver
- **工业界现状**：langgraph 生产环境**最标准**的是 **PostgresSaver**（官方文档主推、可查询、支持并发）；`SqliteSaver` 用于开发/轻量；`InMemorySaver` 仅 demo。
- **为什么选 SQLite**：零新增服务、随项目文件走、够当前"多用户"量级；开发调试友好。
- **边界**：SQLite 高并发**写**时有全库写锁，必须开启 WAL 模式（`PRAGMA journal_mode=WAL`）缓解；checkpoint 文件要固定路径并纳入备份。
- **升级触发条件**：并发写入出现锁等待/超时，或需要多进程共享状态 → 换 **PostgresSaver**（`langgraph-checkpoint-postgres`）。

### 4.3 向量库：Phase 1 用 Chroma
- **工业界现状**：分散。**pgvector**（"能用 Postgres 就别加新组件"的强趋势）、**Chroma**（原型/中小量）、**Pinecone**（托管，创业公司常用）、**Qdrant/Milvus/Weaviate**（大规模、高性能）。
- **为什么选 Chroma**：RAG 在本项目占比小、零运维、可持久化到本地目录、langchain 一等公民支持。
- **边界**：持久化目录（`persist_directory`）要固定并备份；进程内嵌入式，不适合多进程写。
- **升级触发条件**：向量规模到百万级、检索延迟顶不住、或要多服务共享 → 换 **pgvector**（顺带和关系库统一）或 **Qdrant**。

### 4.4 RAG 自研的最小闭环
替换 `ragflow-sdk`，自己搭一条标准 RAG 流水线（这正是理解 RAG 业务的最好方式）：
1. **摄取 Ingestion**：读取文档（复用现有 `upload_file_read_tool` 的解析能力：md/docx/pdf/xlsx）。
2. **分块 Chunking**：`langchain-text-splitters`（已在依赖里），按 token/字符切，带 overlap。
3. **嵌入 Embedding**：走 OpenAI 兼容接口（与现有 Qwen 同一套 provider），封装成可替换的 `Embedder` 接口。
4. **存储/检索**：Chroma；检索器封装成一个工具 `rag_search(query, top_k)`，交给知识库子 Agent 使用。
- **业务要点**：把"召回质量"做成可观测（记录命中片段、分数），这是 RAG 在真实业务里最需要调的地方。

### 4.5 LLM 接入
保留现有 `init_chat_model` + OpenAI 兼容（Qwen-Max）。改进点：模型名、baseURL、超时、重试次数全部走配置（§4.6），不在代码里硬编码；加统一的超时与有限重试（`tenacity` 已在依赖）。

### 4.6 配置管理
用 `pydantic-settings`（已在依赖）做一个 `Settings` 类集中管理所有环境变量（DB、LLM、Tavily、路径、CORS 白名单、并发上限等）。**杜绝 import 时读盘/建连接**，全部改为显式初始化（工厂函数 / FastAPI lifespan 依赖注入），修掉 P1-4。

### 4.7 编排层：deepagents 与 langgraph 如何"并用"
- **deepagents** 负责高层：主 Agent + 子 Agent 的声明式编排、任务分派（保留现有心智模型）。
- **langgraph** 负责需要精细控制的地方：checkpoint、流式事件、（未来的）人工介入/断点续跑。
- **关键改进**：不再靠字符串硬解析库内部 chunk 结构（P2-5）。改用 langgraph 的 `astream_events`（标准事件流 API）来捕获工具调用/子 Agent/结果，映射成自己的 `AgentEvent`，与库版本解耦。

---

## 5. 目标目录结构

```
deep_search_pro/
├── app/                          # 生产代码统一收进 app 包
│   ├── main.py                   # FastAPI 应用工厂 + lifespan（依赖装配）
│   ├── config.py                 # pydantic-settings 集中配置
│   ├── logging.py                # 结构化日志配置
│   ├── api/
│   │   ├── routes_task.py        # /api/task、/cancel、/status
│   │   ├── routes_files.py       # /api/upload、/download、/files（含路径校验）
│   │   ├── routes_ws.py          # /ws/{thread_id}
│   │   └── schemas.py            # 请求/响应 Pydantic 模型
│   ├── services/
│   │   ├── task_service.py       # 后台执行器：提交/取消/状态、并发信号量
│   │   └── session_service.py    # 会话目录、文件生命周期、TTL 清理
│   ├── agents/
│   │   ├── main_agent.py         # build_main_agent(deps) 工厂
│   │   ├── subagents/            # 子 Agent 工厂（注入 tools + emitter）
│   │   └── events.py             # AgentEvent 定义 + astream_events 映射
│   ├── tools/                    # 纯工具，不 import api
│   │   ├── sql_tools.py          # 参数化 + 只读白名单
│   │   ├── search_tools.py       # Tavily
│   │   ├── rag_tools.py          # rag_search（调 rag 模块）
│   │   └── doc_tools.py          # markdown 生成、md→pdf（走 PdfConverter）
│   ├── rag/                      # 自研 RAG
│   │   ├── ingest.py             # 摄取 + 分块
│   │   ├── embedder.py           # Embedder 接口 + OpenAI 兼容实现
│   │   ├── store.py              # Chroma 封装（VectorStore 接口）
│   │   └── retriever.py          # 检索器
│   └── infra/
│       ├── db.py                 # 异步 MySQL 连接池（asyncmy）
│       ├── checkpoint.py         # SqliteSaver（WAL）
│       ├── pdf/                  # PdfConverter 接口 + WordPdfConverter（子进程池）
│       ├── emitter.py            # EventEmitter 接口 + WebSocket/Console/Recording 实现
│       └── events_bus.py         # 进程内 thread_id → asyncio.Queue
├── tests/                        # pytest：单测 + 少量集成测
├── scripts/                      # 一次性脚本（RAG 建库等），与生产代码隔离
├── prompts/                      # prompts.yml（改为按需加载函数）
├── .env.example                  # 配置样例
├── .gitignore                    # 忽略 output/ updated/ data/ *.sqlite chroma/
├── requirements.txt
└── REFACTOR_PLAN.md
```

> 说明：`output/`、`updated/`、`rawflow/`（demo）从生产代码树移除或 gitignore；运行期数据统一放 `data/`（不进 git）。

---

## 6. 分阶段实施计划

> 每个里程碑独立可验收、可回滚。建议按顺序推进，M1/M2 是地基，优先级最高。

### M0 — 准备（0.5 天）
- 建 `app/` 骨架与 `tests/`；配 `.gitignore`、`.env.example`；`git rm --cached` 清掉误入库的 `output/`、`updated/`、`__pycache__`、`.idea`。
- 引入 `pytest`、`ruff`（lint）、`pytest-asyncio`。
- **验收**：空骨架能 `pytest` 跑通、`ruff` 无致命告警。

### M1 — 配置与依赖装配（1 天）
- 写 `config.py`（`Settings`）；把所有 `os.getenv`/`load_dotenv` 收敛进去。
- 消除 import 副作用：`prompts` 改按需加载函数；LLM、DB、RAG 客户端全部工厂化。
- `main.py` 用 FastAPI `lifespan` 装配依赖。
- **验收**：RAGFlow/DB 不可达时应用**仍能启动**（延迟到首次使用才报错）；`pytest` 能在不连任何外部服务下导入所有模块。

### M2 — 解耦传输层（EventEmitter）（1.5 天）
- 定义 `AgentEvent`、`EventEmitter`；实现 `events_bus`（进程内队列）、`WebSocketEmitter`、`RecordingEmitter`。
- 工具与 Agent 去掉对 `api.monitor`/`api.context` 的依赖，改为参数注入 `emitter` + `session_dir`。
- **验收**：用 `RecordingEmitter` 单测一个工具，断言事件被正确发出；工具模块不再 import api。

### M3 — 安全加固（1 天）
- `sql_tools`：查询参数化；`execute_sql_query` 加只读校验（正则/SQL 解析拦截 DROP/DELETE/UPDATE/INSERT/ALTER 等）、表名白名单、强制 `LIMIT`。
- `routes_files`：下载/列表路径做 `resolve()` + `is_relative_to` 双校验（现有逻辑保留并加固）；限制上传大小与类型。
- CORS 白名单从配置读；补一个最简 API Key/Token 鉴权中间件。
- **验收**：单测覆盖"恶意 SQL 被拦截""路径穿越被拒""无 token 被拒"。

### M4 — 阻塞隔离与异步化（1.5 天）
- MySQL 换 `asyncmy` + 连接池；`sql_tools` 全异步。
- `PdfConverter` 接口 + `WordPdfConverter`（`ProcessPoolExecutor` + `CoInitialize`）；`doc_tools` 通过 `run_in_executor` 调用。
- **验收**：并发发起 N 个含 DB 查询 + PDF 生成的任务，事件循环不被阻塞（用日志时间戳验证交错执行）；Word 子进程崩溃不影响主进程。

### M5 — 任务生命周期（1 天）
- `task_service`：受管后台执行器（提交/取消/状态、并发信号量）；checkpoint 换 `SqliteSaver`（WAL）。
- 补 `/api/task/{id}` 状态查询、`/cancel` 取消接口。
- 编排事件改用 `astream_events` 映射，去掉硬解析。
- **验收**：任务可查状态、可取消；进程重启后能凭 `thread_id` 恢复会话（checkpoint 生效）；晚连的 WebSocket 能收到缓冲事件（P0-3 修复）。

### M6 — 自研 RAG（1.5 天）
- 实现 `rag/` 四件套（ingest/embedder/store/retriever）；`scripts/build_index.py` 建库脚本。
- `rag_tools.rag_search` 接进知识库子 Agent，替换 `ragflow_tools`。
- **验收**：给定一批文档能建库并检索；检索返回片段+分数可观测；知识库子 Agent 端到端跑通。

### M7 — 可观测性、清理与测试补齐（1 天）
- `print` 全部换结构化日志（`logging`，带 `thread_id` 上下文）。
- `session_service` 加会话目录 TTL 清理（定时任务）；去掉 updated→output 冗余复制，统一读取。
- 补齐核心路径 pytest；写 README（如何本地跑、如何建 RAG 库、如何切换 PDF 引擎）。
- **验收**：`pytest` 覆盖 §8 清单；README 可让新人 30 分钟跑起来。

**Phase 1 总工期估算：约 9–10 人天**（不含前端联调）。

---

## 7. 边界情况清单（必须在实现与测试中覆盖）

### 并发与生命周期
- 同一 `thread_id` 重复提交任务 → 幂等处理或拒绝（返回既有任务状态）。
- 任务运行中客户端断开 WebSocket → 任务**继续跑**，事件缓冲在队列；客户端重连后补发。
- 任务被取消 → `langgraph` 图需响应取消、释放 DB 连接、关闭 Word 子进程。
- 并发任务数超过信号量上限 → 排队而非拒绝，或明确返回"繁忙"。
- 进程重启 → 未完成任务如何处理（标记为中断 / 依据 checkpoint 可续跑）。

### 传输层
- WebSocket 未连上就有事件 → 进程内队列缓冲（有界，设上限防内存爆）。
- 队列积压超上限 → 丢弃最旧事件或背压，需明确策略。
- 客户端发非法帧 / 半连接 → 心跳超时清理。

### LLM / 工具
- LLM 超时、限流(429)、返回空 → 有限重试（tenacity）+ 明确错误事件，不吞异常。
- LLM 幻觉出不存在的表/文件 → 工具层校验并返回可读错误，让 Agent 自我纠正。
- 工具抛异常 → 捕获并作为工具结果返回给 Agent，而非中断整个图。
- 子 Agent 无限循环 / 步数爆炸 → 设递归/步数上限。

### 数据库
- 危险 SQL（DROP/DELETE/多语句 `;` 注入）→ 只读校验拦截。
- 超大结果集 → 强制 `LIMIT`，流式或截断并提示。
- 连接池耗尽 / DB 断连 → 超时 + 重连 + 友好报错。
- 中文/特殊字符/NULL 值 → 编码与序列化正确（utf8mb4）。

### 文件
- 路径穿越（`../`、绝对路径、软链接）→ `resolve()` + `is_relative_to` 拦截。
- 上传超大文件 / 恶意类型 / 同名覆盖 → 大小上限、类型白名单、去重命名。
- 文件名含特殊字符 / 中文 → 安全化处理。
- 磁盘写满 → 捕获并报错，不崩溃。
- 会话目录无限增长 → TTL 清理。

### RAG
- 空文档 / 超长文档 / 扫描版 PDF（无文本层）→ 摄取时校验与提示。
- 嵌入服务超时/失败 → 重试 + 局部失败可继续。
- 检索无命中 → 返回空并让 Agent 走网络搜索兜底。
- Chroma 持久化目录损坏 → 可重建脚本。

### PDF / Windows
- Word 未安装 / COM 初始化失败 → 明确报错，或降级到其他引擎。
- Word 子进程卡死 → 超时 kill 并重建进程。
- 并发转换 → 进程池串行化 COM 调用，避免 STA 冲突。

### 配置
- 关键环境变量缺失 → 启动时 `Settings` 校验并给出清晰报错（而非运行时神秘崩溃）。
- 外部服务（RAGFlow/Tavily/DB）不可达 → 不阻断应用启动，延迟到调用时报错。

---

## 8. 测试与验收策略

- **单元测试**（主体）：工具（用 `RecordingEmitter`）、SQL 安全校验、路径校验、配置加载、RAG 分块/检索、事件映射。
- **集成测试**（少量）：一个提交→执行→事件→结果的端到端流程（LLM 可用 mock 或录制回放）；WebSocket 缓冲补发。
- **并发验证**：脚本并发发起任务，用日志时间戳证明未阻塞事件循环。
- **CI 门槛**：`ruff` + `pytest` 通过；核心模块（tools/rag/services）覆盖率作为参考指标。
- **每个里程碑**都有明确验收标准（见 §6），未达标不进入下一里程碑。

---

## 9. 迁移与回滚策略

- **分支策略**：`refactor/*` 分支逐里程碑合并；每个 M 一个可回滚的 PR。
- **绞杀者模式（Strangler Fig）**：新 `app/` 与旧代码可短期共存；接口逐个切到新实现，旧路径保留到验证通过再删。
- **数据兼容**：checkpoint 从 InMemory→SQLite 是新增，无历史数据迁移负担；RAG 从 RAGFlow→Chroma 需用 `scripts/build_index.py` 重建索引（一次性）。
- **回滚**：任一里程碑出问题，`git revert` 对应 PR 即可，因每步独立。

---

## 10. Phase 2 演进路线（有明确触发条件才做）

| 演进项 | 触发信号 | 目标方案 |
|---|---|---|
| 引入任务队列 | 要多机部署 / 需重试定时 / 单机扛不住 | **arq 或 Celery + Redis**（Windows 注意池类型） |
| checkpoint 升级 | SQLite 写锁等待 / 需多进程共享 | **PostgresSaver** |
| 向量库升级 | 百万级向量 / 检索延迟高 / 多服务共享 | **pgvector 或 Qdrant** |
| WebSocket 跨机分发 | 多台 Web 服务器 | **Redis Pub/Sub** 做事件扇出 |
| PDF 上 Linux | 部署迁移到 Linux/容器 | 新增 **WeasyPrint/pandoc** 实现，切 `PdfConverter` |
| 可观测性增强 | 需要链路追踪 | 接 **LangSmith**（依赖已在）/ OpenTelemetry |

> 核心思想：Phase 1 把"一个生产单体该有的样子"做扎实；Phase 2 每一步都是"业务增长撞到具体瓶颈后的针对性演进"——**懂得何时不上，比会用更重要**。

---

## 附：优先级速查
1. 先修 P0（阻塞、发射后不管、竞态、状态易失）——对应 M2/M4/M5。
2. 再修 P1（安全、依赖倒置、导入副作用）——对应 M1/M2/M3。
3. 最后补 P2（日志、测试、清理）——对应 M7。
