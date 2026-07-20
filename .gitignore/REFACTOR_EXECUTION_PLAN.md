# deep_search_pro 重构 · 每日执行计划

> 配套文档：`REFACTOR_PLAN.md`（战略与设计依据）。本文件是**可照着敲代码**的落地版：具体到每天做什么、在哪建文件夹、每个文件写什么接口、完成哪些动作、怎么验收。
>
> 工期：**10 个工作日（约 2 周）**，对应 Phase 1 的 M0–M7。每天一个可提交、可回滚的单元。

---

## 老代码处置策略：Strangler Fig（绞杀者）迁移

> 本项目仅约 1800 行，重构是**照着旧逻辑重新组织**，而非在旧代码上改。因此旧代码几乎 100% 被替代，最终全部删除；并存只是过程中的临时状态。

**核心手法——`legacy/` 隔离区：**
1. **Day 1 第一件事**：把旧的 `agent/ api/ tools/ utils/ rawflow/` 整体 `git mv` 进 `legacy/`。此后 `app/` 全程保持干净，新老代码永远不在同一层。
2. `legacy/` 只作"参照抄写"用，**不再运行**（新入口从 Day 2 起是 `app/main.py`）。
3. **每天验收通过后，在同一个 commit 里删掉 `legacy/` 中已被替代的旧文件**——`legacy/` 逐日变空，`git log` 清楚记录每个旧文件何时被谁取代。
4. **Day 10** 删除空的 `legacy/`，重构完成。

**逐文件迁移/删除对照表：**

| 旧文件 | 处置 | 去向 | 何时删 legacy |
|---|---|---|---|
| `agent/llm.py` | 重写 | `app/infra/llm.py` | Day 2 |
| `agent/prompts.py` | 重写 | `app/prompts.py` | Day 2 |
| `agent/main_agent.py` | 拆分重写 | `app/agents/main_agent.py` + `agents/stream.py` | Day 8 |
| `agent/subagents/network_search_agent.py` | 重写 | `app/agents/subagents/network_search.py` | Day 4 |
| `agent/subagents/database_query_agent.py` | 重写 | `app/agents/subagents/database_query.py` | Day 6 |
| `agent/subagents/knowledge_base_agent.py` | 重写 | `app/agents/subagents/knowledge_base.py` | Day 9 |
| `api/server.py` | 拆分重写 | `app/main.py` + `app/api/routes_*.py` | Day 8 |
| `api/monitor.py` | 替换 | `app/infra/emitter.py` + `events_bus.py` | Day 3 |
| `api/context.py` | **废弃删除** | 被依赖注入取代，不再需要 ContextVar | Day 4 |
| `api/deep_agent_02_fixed.py` | **直接删除** | 历史遗留 | Day 1 |
| `tools/db_tools.py` | 拆分重写 | `app/infra/db.py` + `tools/sql_tools.py` + `sql_safety.py` | Day 6 |
| `tools/ragflow_tools.py` | **删除** | 被自研 `app/rag/*` 替代 | Day 9 |
| `tools/tavily_tool.py` | 重写 | `app/tools/search_tools.py` | Day 4 |
| `tools/markdown_tools.py` | 重写 | `app/tools/doc_tools.py` | Day 4 |
| `tools/pdf_tools.py` | 重写 | `app/tools/doc_tools.py` + `app/infra/pdf/*` | Day 7 |
| `tools/upload_file_read_tool.py` | 重写/复用 | `app/rag/ingest.py`（解析逻辑） | Day 9 |
| `tools/test_session_123/` | **直接删除** | 测试遗留 | Day 1 |
| `utils/word_converter.py` | 迁移 | `app/infra/pdf/worker.py` | Day 7 |
| `utils/path_utils.py` | 迁移 | `app/infra/paths.py` | Day 4 |
| `rawflow/` | **删除** | demo，不进生产 | Day 1（或 Day 9 抄完解析逻辑后） |
| `prompt/prompts.yml` | 移动 | `prompts/prompts.yml` | Day 2 |
| `output/` `updated/` | 移出代码树 | `data/`（gitignore，非代码） | Day 1 |

> 规则：**只有当新模块验收通过、确认不再需要参照时，才删对应 legacy 文件**。删早了会丢失可抄写的参照；删晚了会造成混乱。上表"何时删"即安全删除点。

## 使用约定
- **分支**：每天从 `develop` 拉 `refactor/dayNN-xxx`，当天验收通过后合并。
- **完成定义（DoD）**：当天所有"动作"完成 + "验收"全绿 + `ruff` 无致命告警 + 相关 `pytest` 通过 + 一次 `git commit`。
- **路径基准**：项目根 = `deep_search_pro/`。新代码统一进 `app/` 包。运行期数据统一进 `data/`（不进 git）。
- **接口先行**：先写接口/签名与 docstring，再填实现，最后补测试。

## 里程碑 ↔ 天数映射
| Day | 里程碑 | 主题 |
|---|---|---|
| 1 | M0 + M1a | 骨架、工具链、配置 Settings、**老代码隔离到 legacy/** |
| 2 | M1b | 消除 import 副作用、lifespan 依赖装配 |
| 3 | M2a | 事件模型、EventEmitter、事件总线 |
| 4 | M2b | 工具/Agent 去耦，参数注入 |
| 5 | M3 | 安全加固（SQL/路径/CORS/鉴权） |
| 6 | M4a | MySQL 异步化 + 连接池 |
| 7 | M4b | Word→PDF 子进程隔离 + PdfConverter 抽象 |
| 8 | M5 | 任务生命周期、SQLite checkpoint、astream_events |
| 9 | M6 | 自研 RAG（摄取/嵌入/存储/检索/接入） |
| 10 | M7 | 可观测性、清理、测试补齐、README、**删除 legacy/** |

---

## Day 1 — 骨架 + 工具链 + 配置（M0 + M1a）

### 目标
搭好 `app/` 包骨架和开发工具链，写出集中式配置 `Settings`。

### 新建文件夹
```
app/  app/api/  app/services/  app/agents/  app/agents/subagents/
app/tools/  app/rag/  app/infra/  app/infra/pdf/
tests/  scripts/  prompts/  data/   (data/ 加入 .gitignore)
```
每个 Python 包目录放一个空 `__init__.py`。

### 新建/改动文件
| 文件 | 职责 | 关键内容 |
|---|---|---|
| `.gitignore` | 忽略运行期与 IDE 产物 | `output/ updated/ data/ *.sqlite* chroma/ __pycache__/ .idea/ .env` |
| `.env.example` | 配置样例（不含真实密钥） | 列出所有环境变量键 |
| `pyproject.toml` 或 `ruff.toml` | lint 配置 | 启用 ruff、行宽、忽略规则 |
| `app/config.py` | 集中配置 | `Settings(BaseSettings)` + `get_settings()` |
| `tests/test_config.py` | 配置加载单测 | 缺失必填项应报错 |

### `app/config.py` 接口
```python
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # LLM
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_timeout: int = 60
    llm_max_retries: int = 2
    # MySQL（业务数据源，只读）
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str
    mysql_password: str
    mysql_database: str
    mysql_pool_min: int = 1
    mysql_pool_max: int = 5
    # Tavily
    tavily_api_key: str
    # RAG
    embed_model: str
    chroma_dir: Path = Path("data/chroma")
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 120
    # 运行期
    data_dir: Path = Path("data")
    checkpoint_db: Path = Path("data/checkpoints.sqlite")
    max_concurrent_tasks: int = 5
    event_queue_maxsize: int = 1000
    # 安全
    cors_origins: list[str] = ["http://localhost:3000"]
    api_token: str | None = None
    sql_table_allowlist: list[str] = []
    sql_row_limit: int = 100

@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore
```

### 动作
1. **隔离老代码**：`git mv agent api tools utils rawflow legacy/`（新建 `legacy/`），让 `app/` 从零开始保持干净。
2. **删除明确无用物**：`git rm -r legacy/api/deep_agent_02_fixed.py legacy/tools/test_session_123`；`rawflow/` 若无需参照可一并删（否则留到 Day 9 抄完解析逻辑）。
3. 建 `app/` 各目录与 `__init__.py`；建 `data/`。
4. `git rm -r --cached output updated .idea` 及各 `__pycache__`，写 `.gitignore`。
5. 装工具：`pip install ruff pytest pytest-asyncio`（加进 `requirements.txt`）。
6. 写 `config.py` 与 `.env.example`。
7. 写 `test_config.py`。

### 验收
- `pytest tests/test_config.py` 通过（含"缺失必填项抛错"用例）。
- `ruff check app` 无致命告警。
- 项目根下只剩 `app/`（新）+ `legacy/`（待删）两处代码，界限清晰。
- `git status` 中不再出现 `output/ updated/ __pycache__`。

---

## Day 2 — 消除 import 副作用 + 依赖装配（M1b）

### 目标
所有"导入即执行"的副作用（顶层 print、读盘、建客户端、建 Agent）改为**显式工厂 + lifespan 装配**。外部服务不可达时应用仍能启动。

### 新建/改动文件
| 文件 | 职责 | 关键内容 |
|---|---|---|
| `prompts/prompts.yml` | 迁移自旧 `prompt/prompts.yml` | 内容不变 |
| `app/prompts.py` | 按需加载提示词 | `load_prompts()` 函数，无顶层执行 |
| `app/infra/llm.py` | LLM 工厂 | `build_chat_model(settings)`，含超时/重试 |
| `app/main.py` | FastAPI 应用工厂 + lifespan | `create_app()`，在 lifespan 内装配依赖并挂到 `app.state` |
| `tests/test_imports.py` | 导入无副作用测试 | 不连外部服务能 import 全部模块 |

### 关键接口
```python
# app/prompts.py
def load_prompts(path: Path | None = None) -> dict: ...
def main_agent_prompt() -> str: ...
def subagent_prompts() -> dict: ...

# app/infra/llm.py
def build_chat_model(settings: Settings):
    return init_chat_model(
        model=settings.llm_model, model_provider="openai",
        base_url=settings.llm_base_url, api_key=settings.llm_api_key,
        timeout=settings.llm_timeout, max_retries=settings.llm_max_retries,
    )

# app/main.py
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)  # Day3 引入
    # DB/PDF/RAG 等采用惰性初始化，不在此处强连接
    yield
    # 清理：关闭 DB 池、进程池等
def create_app() -> FastAPI: ...
```

### 动作
1. 移动 `prompt/prompts.yml` → `prompts/prompts.yml`；改写 `app/prompts.py` 去掉顶层 print/加载。
2. 写 `app/infra/llm.py` 工厂。
3. 写 `app/main.py` 的 `create_app()` + `lifespan` 骨架（依赖占位，后续天填充）。
4. 写 `test_imports.py`：断言在无 DB/无网络下能导入 `app.tools.*`、`app.agents.*`、`app.rag.*`。

### 验收
- 断开 DB/RAGFlow/网络，`python -c "import app.main"` 及 `uvicorn app.main:create_app --factory` 能启动不崩。
- `pytest tests/test_imports.py` 通过。

---

## Day 3 — 事件模型 + EventEmitter + 事件总线（M2a）

### 目标
用注入式 `EventEmitter` + 进程内 `EventBus` 替换全局单例 `monitor`；顺带修复"WebSocket 晚连丢事件"（P0-3）。

### 新建/改动文件
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/agents/events.py` | 事件数据模型 | `AgentEvent` dataclass |
| `app/infra/emitter.py` | 发射器接口与实现 | `EventEmitter` / `WebSocketEmitter` / `RecordingEmitter` / `ConsoleEmitter` |
| `app/infra/events_bus.py` | 进程内事件总线 | `EventBus` |
| `tests/test_events.py` | 事件流单测 | 缓冲、订阅、丢弃策略 |

### 关键接口
```python
# app/agents/events.py
from dataclasses import dataclass, field
from typing import Literal, Any
EventType = Literal["session_created","tool_start","tool_end",
                    "subagent_call","token","task_result","error"]
@dataclass
class AgentEvent:
    type: EventType
    thread_id: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    ts: str = ""   # ISO 时间，构造时填充

# app/infra/emitter.py
from typing import Protocol
class EventEmitter(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...
class WebSocketEmitter:          # 把事件发布到 EventBus
    def __init__(self, bus: EventBus, thread_id: str): ...
class RecordingEmitter:          # 测试用，收集到 self.events
    def __init__(self): self.events: list[AgentEvent] = []
class ConsoleEmitter: ...        # 脚本/调试用

# app/infra/events_bus.py
import asyncio
from typing import AsyncIterator
class EventBus:
    def __init__(self, maxsize: int = 1000):
        self._queues: dict[str, asyncio.Queue] = {}
    def get_queue(self, thread_id: str) -> asyncio.Queue: ...   # 不存在则创建（缓冲）
    async def publish(self, thread_id: str, event: AgentEvent) -> None: ...  # 满则丢最旧
    async def subscribe(self, thread_id: str) -> AsyncIterator[AgentEvent]: ...
    def drop(self, thread_id: str) -> None: ...
```

### 动作
1. 写 `AgentEvent`、`EventBus`（有界队列 + 满时丢最旧 + 记 warning）。
2. 写三个 Emitter 实现。
3. `main.py` lifespan 里实例化 `EventBus` 挂 `app.state`。
4. 单测：晚订阅仍能读到已缓冲事件；队列超限丢弃最旧。

### 验收
- `pytest tests/test_events.py` 通过（含缓冲补发、超限丢弃两条用例）。

---

## Day 4 — 工具/Agent 去耦，参数注入（M2b）

### 目标
把工具从"反向依赖 api.monitor/api.context"改成**工厂函数注入依赖**（`emitter` + `session_dir` + 资源句柄），彻底矫正依赖方向。

### 新建/改动文件（此阶段先迁移非阻塞类工具，DB/PDF 留到 M4）
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/tools/search_tools.py` | Tavily 网络搜索 | `build_search_tools(emitter, settings) -> list[BaseTool]` |
| `app/tools/doc_tools.py` | markdown 生成（PDF 占位） | `build_doc_tools(emitter, session_dir, pdf_converter=None)` |
| `app/infra/paths.py` | 路径解析与校验（迁移自 utils/path_utils） | `resolve_in_session(name, session_dir) -> Path` |
| `app/agents/subagents/network_search.py` | 网络搜索子 Agent 工厂 | `build_network_search_agent(deps)` |
| `app/agents/main_agent.py` | 主 Agent 工厂 | `build_main_agent(deps) -> CompiledGraph` |
| `tests/test_tools_search.py` | 用 RecordingEmitter 测工具 | 断言事件被发出 |

### 关键接口
```python
# app/tools/search_tools.py
from langchain_core.tools import tool
def build_search_tools(emitter: EventEmitter, settings: Settings):
    client = TavilyClient(api_key=settings.tavily_api_key)  # 工厂内建，非顶层
    @tool
    async def internet_search(query: str, topic: str = "general",
                              max_results: int = 5) -> str:
        await emitter.emit(AgentEvent("tool_start", ..., data={"query": query}))
        res = await asyncio.to_thread(client.search, query=query, ...)
        await emitter.emit(AgentEvent("tool_end", ...))
        return res
    return [internet_search]

# app/agents/main_agent.py
@dataclass
class AgentDeps:          # 一次性把所有依赖收进来
    settings: Settings
    emitter: EventEmitter
    session_dir: Path
    db: "Database | None" = None
    pdf_converter: "PdfConverter | None" = None
    retriever: "Retriever | None" = None
def build_main_agent(deps: AgentDeps):
    model = build_chat_model(deps.settings)
    tools = [*build_doc_tools(...), *build_search_tools(...)]
    subagents = [build_network_search_agent(deps), ...]
    return create_deep_agent(model=model, system_prompt=main_agent_prompt(),
                             tools=tools, subagents=subagents,
                             checkpointer=...)  # Day8 注入
```

### 动作
1. 迁移 `path_utils` → `app/infra/paths.py`，保留 `resolve()` + `is_relative_to` 校验。
2. 写 `search_tools`、`doc_tools`（markdown 部分），全部工厂化、异步化、注入 emitter。
3. 写 `AgentDeps` 与 `build_main_agent`、网络搜索子 Agent 工厂。
4. 单测：`RecordingEmitter` 注入，调用工具后断言事件序列；确认工具模块 **不 import `app.api`**。

### 验收
- `grep -r "import.*app.api" app/tools app/agents` 无结果（依赖方向已矫正）。
- `pytest tests/test_tools_search.py` 通过。

---

## Day 5 — 安全加固（M3）

### 目标
修 P1-1/1-2/1-5/1-6：SQL 只读白名单与参数化、路径校验、CORS 收敛、接口鉴权。

### 新建/改动文件
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/tools/sql_safety.py` | SQL 安全校验 | `assert_read_only(sql)` / `assert_table_allowed(name, allowlist)` |
| `app/api/deps.py` | FastAPI 鉴权依赖 | `require_token(...)` |
| `app/api/routes_files.py` | 文件接口 + 路径校验 | upload/download/list |
| `tests/test_sql_safety.py` | SQL 拦截用例 | DROP/DELETE/多语句/注释绕过 |
| `tests/test_security.py` | 路径穿越、鉴权 | 越权路径、无 token |

### 关键接口
```python
# app/tools/sql_safety.py
FORBIDDEN = {"DROP","DELETE","UPDATE","INSERT","ALTER","TRUNCATE","CREATE","GRANT"}
def assert_read_only(sql: str) -> None:
    """拒绝非 SELECT / 多语句 / 危险关键字，抛 ValueError。"""
def assert_table_allowed(name: str, allowlist: list[str]) -> None: ...
def enforce_limit(sql: str, row_limit: int) -> str:
    """SELECT 无 LIMIT 时自动追加 LIMIT。"""

# app/api/deps.py
from fastapi import Header, HTTPException
async def require_token(authorization: str = Header(None),
                        settings: Settings = Depends(get_settings)):
    if settings.api_token and authorization != f"Bearer {settings.api_token}":
        raise HTTPException(401, "unauthorized")
```

### 动作
1. 实现 `sql_safety`（用正则 + 关键字集合；去注释后再判，防 `--`/`/* */` 绕过；禁分号多语句）。
2. `routes_files`：迁移旧 download/list 的 `resolve()`+`is_relative_to` 校验并加固；上传加大小上限、类型白名单、同名去重。
3. `create_app()` 用配置里的 `cors_origins`（不再 `*`）；任务/文件接口挂 `require_token` 依赖。
4. 单测覆盖各拦截路径。

### 验收
- `pytest tests/test_sql_safety.py tests/test_security.py` 全绿（含注释绕过、多语句、`../` 穿越、无 token）。

---

## Day 6 — MySQL 异步化 + 连接池（M4a）

### 目标
把 MySQL 从同步 `mysql-connector` 换成异步 `asyncmy` + 连接池，SQL 工具全异步、参数化，接上 Day5 的安全校验。

### 新建/改动文件
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/infra/db.py` | 异步 MySQL 池 | `Database` 类 |
| `app/tools/sql_tools.py` | 三个 SQL 工具（异步） | `build_sql_tools(db, emitter, settings)` |
| `app/agents/subagents/database_query.py` | 数据库子 Agent 工厂 | `build_database_agent(deps)` |
| `tests/test_db.py` | DB 集成测（可用 SQLite/mock 或标记 skip） | 查询/异常/超时 |

### 关键接口
```python
# app/infra/db.py
import asyncmy
class Database:
    def __init__(self, settings: Settings): self._pool = None; self._s = settings
    async def connect(self) -> None:      # 建池
        self._pool = await asyncmy.create_pool(host=..., minsize=..., maxsize=...)
    async def close(self) -> None: ...
    async def fetch(self, sql: str, params: tuple = ()) -> tuple[list[str], list[tuple]]:
        """返回 (列名, 行)。带超时；异常包装成友好错误。"""

# app/tools/sql_tools.py
def build_sql_tools(db: Database, emitter, settings):
    @tool
    async def list_sql_tables() -> str: ...
    @tool
    async def get_table_data(table_name: str) -> str:
        assert_table_allowed(table_name, settings.sql_table_allowlist)
        cols, rows = await db.fetch("SELECT * FROM %s LIMIT %s", ...)  # 表名走白名单校验
    @tool
    async def execute_sql_query(query: str) -> str:
        assert_read_only(query); query = enforce_limit(query, settings.sql_row_limit)
        ...
    return [list_sql_tables, get_table_data, execute_sql_query]
```

### 动作
1. `pip install asyncmy`（加进 requirements，移除或保留 mysql-connector 视情况）。
2. 写 `Database` 池 + 超时 + 断连重试；`main.py` lifespan 惰性建池、退出关池。
3. 写异步 `sql_tools`，接安全校验；写数据库子 Agent 工厂。
4. 边界测试：DB 断连、结果集超大截断、中文/NULL、连接池耗尽排队。

### 验收
- 数据库子 Agent 端到端跑一条真实查询；恶意 SQL 被 `sql_safety` 拦截。
- `pytest tests/test_db.py`（无 DB 环境时相关用例 skip，安全校验用例必过）。

---

## Day 7 — Word→PDF 子进程隔离 + PdfConverter 抽象（M4b）

### 目标
把 Word COM（STA 阻塞）放进独立子进程池，主事件循环不被阻塞；抽象出可替换的转换器接口。

### 新建/改动文件
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/infra/pdf/base.py` | 转换器接口 | `PdfConverter` Protocol |
| `app/infra/pdf/word_converter.py` | Windows/Word 实现 | `WordPdfConverter` |
| `app/infra/pdf/worker.py` | 子进程内转换函数 | `_convert_in_process(md, pdf)` |
| `app/tools/doc_tools.py`（补全） | 接入 pdf_converter | `convert_md_to_pdf` 工具 |
| `tests/test_pdf.py` | 转换/超时/崩溃恢复 | 标记 Windows-only |

### 关键接口
```python
# app/infra/pdf/base.py
from pathlib import Path
from typing import Protocol
class PdfConverter(Protocol):
    async def convert(self, md_path: Path, pdf_path: Path) -> Path: ...

# app/infra/pdf/word_converter.py
from concurrent.futures import ProcessPoolExecutor
class WordPdfConverter:
    def __init__(self, max_workers: int = 2, timeout: int = 120):
        self._pool = ProcessPoolExecutor(max_workers=max_workers,
                                         initializer=_init_com)
    async def convert(self, md_path, pdf_path) -> Path:
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(self._pool, _convert_in_process, str(md_path), str(pdf_path))
        return Path(await asyncio.wait_for(fut, self._timeout))  # 超时 kill

# app/infra/pdf/worker.py
def _init_com(): import pythoncom; pythoncom.CoInitialize()
def _convert_in_process(md: str, pdf: str) -> str:
    # 迁移旧 utils/word_converter 逻辑，跑在子进程
```

### 动作
1. 迁移旧 `word_converter` 转换逻辑到 `worker._convert_in_process`。
2. 写 `WordPdfConverter`（进程池 + 每进程 `CoInitialize` + 超时 + 崩溃后进程池自愈）。
3. `main.py` lifespan 惰性创建转换器，退出时 `shutdown(wait=False)`。
4. `doc_tools.convert_md_to_pdf` 通过注入的 `pdf_converter` 调用。
5. 边界测试：Word 未安装报错、子进程超时被 kill、并发转换串行不冲突。

### 验收
- 并发触发多个 PDF 转换，主循环仍响应其他请求（日志时间戳交错）。
- Word 缺失时返回清晰错误而非崩溃。

---

## Day 8 — 任务生命周期 + SQLite checkpoint + astream_events（M5）

### 目标
修 P0-2/P0-4/P2-5：受管后台执行器（提交/取消/状态 + 并发信号量）、SQLite checkpoint（WAL）、用 `astream_events` 替换硬解析。

### 新建/改动文件
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/infra/checkpoint.py` | checkpoint 工厂 | `build_checkpointer(settings)` |
| `app/agents/stream.py` | astream_events → AgentEvent 映射 | `run_agent_stream(agent, query, cfg, emitter)` |
| `app/services/task_service.py` | 任务生命周期 | `TaskService` |
| `app/services/session_service.py` | 会话目录/文件 | `SessionService` |
| `app/api/routes_task.py` | 任务接口 | submit/status/cancel |
| `app/api/routes_ws.py` | WebSocket 网关 | 订阅 EventBus 转发 |
| `tests/test_task_service.py` | 提交/取消/并发/恢复 | |

### 关键接口
```python
# app/infra/checkpoint.py
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
async def build_checkpointer(settings):
    saver = AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db))
    # 开启 WAL：PRAGMA journal_mode=WAL
    return saver

# app/agents/stream.py
async def run_agent_stream(agent, query, config, emitter):
    async for ev in agent.astream_events({"messages":[...]}, config=config, version="v2"):
        kind = ev["event"]         # on_tool_start / on_tool_end / on_chain_end ...
        # 映射成 AgentEvent 并 emitter.emit(...)

# app/services/task_service.py
class TaskService:
    def __init__(self, build_agent, bus, settings):
        self._tasks: dict[str, asyncio.Task] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)
    async def submit(self, query: str, thread_id: str) -> str: ...   # 幂等：重复 id 返回既有
    async def cancel(self, thread_id: str) -> bool: ...              # task.cancel()
    def status(self, thread_id: str) -> dict: ...                    # running/done/error/cancelled
```

### 动作
1. checkpoint 换 `AsyncSqliteSaver` + WAL，注入 `build_main_agent`。
2. 写 `run_agent_stream`（astream_events 映射，覆盖工具/子 Agent/最终结果/错误）。
3. `TaskService`：信号量限流、`dict` 跟踪、取消传播（图内响应取消）、幂等提交。
4. `routes_task`（submit 立即返回 id / status / cancel）、`routes_ws`（订阅 bus 转发，断开清理）。
5. 边界：重复提交、运行中断连、取消释放资源、进程重启凭 thread_id 续跑。

### 验收
- 任务可查状态、可取消；晚连 WebSocket 收到缓冲事件；重启后 checkpoint 生效。
- `pytest tests/test_task_service.py` 通过。

---

## Day 9 — 自研 RAG（M6）

### 目标
用自研 RAG 流水线替换 `ragflow-sdk`：摄取→分块→嵌入→Chroma→检索，封装成 `rag_search` 工具接进知识库子 Agent。

### 新建/改动文件
| 文件 | 职责 | 关键接口 |
|---|---|---|
| `app/rag/embedder.py` | 嵌入接口 + OpenAI 兼容实现 | `Embedder` / `OpenAIEmbedder` |
| `app/rag/store.py` | 向量库封装 | `VectorStore` / `ChromaStore` |
| `app/rag/ingest.py` | 摄取 + 分块 | `ingest_documents(...)` |
| `app/rag/retriever.py` | 检索器 | `Retriever` |
| `app/tools/rag_tools.py` | rag_search 工具 | `build_rag_tools(retriever, emitter)` |
| `app/agents/subagents/knowledge_base.py` | 知识库子 Agent 工厂 | `build_knowledge_agent(deps)` |
| `scripts/build_index.py` | 一次性建库脚本 | CLI |
| `tests/test_rag.py` | 分块/检索/空命中 | |

### 关键接口
```python
# app/rag/embedder.py
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
class OpenAIEmbedder:  # 复用 llm_base_url / embed_model
    def __init__(self, settings): ...

# app/rag/store.py
@dataclass
class Hit: id: str; text: str; score: float; metadata: dict
class VectorStore(Protocol):
    async def add(self, ids, texts, embeddings, metadatas) -> None: ...
    async def query(self, embedding: list[float], top_k: int) -> list[Hit]: ...
class ChromaStore:   # persist_directory = settings.chroma_dir
    def __init__(self, settings): ...

# app/rag/ingest.py
async def ingest_documents(paths: list[Path], embedder, store, settings) -> int:
    # 复用 upload_file_read 的解析（md/docx/pdf/xlsx）→ 分块(langchain-text-splitters)
    # → 嵌入 → store.add；返回写入分块数

# app/rag/retriever.py
class Retriever:
    def __init__(self, embedder, store, settings): ...
    async def search(self, query: str, top_k: int = 5) -> list[Hit]: ...
```

### 动作
1. 写 `embedder`/`store`/`ingest`/`retriever` 四件套。
2. `rag_tools.rag_search`（返回片段 + 分数，emit 可观测事件）；接进知识库子 Agent，移除 ragflow 依赖。
3. 写 `scripts/build_index.py`（指定文档目录建库）。
4. 边界：空文档/超长/扫描版无文本 PDF、嵌入超时重试、检索无命中→交由网络搜索兜底、Chroma 目录可重建。

### 验收
- 给定样例文档能建库、检索返回带分数的片段；知识库子 Agent 端到端跑通。
- `pytest tests/test_rag.py` 通过。

---

## Day 10 — 可观测性 + 清理 + 测试补齐 + README（M7）

### 目标
修 P2-1/2-3/2-4：结构化日志、会话 TTL 清理、去冗余复制、补齐测试与 README，收尾整个 Phase 1。

### 新建/改动文件
| 文件 | 职责 | 关键内容 |
|---|---|---|
| `app/logging.py` | 结构化日志配置 | `setup_logging()`，日志带 `thread_id` |
| `app/services/session_service.py`（补全） | TTL 清理 | `cleanup_expired(ttl)` 定时任务 |
| `tests/test_integration.py` | 端到端集成测 | 提交→事件→结果（LLM mock） |
| `README.md` | 上手文档 | 本地运行、建 RAG 库、切 PDF 引擎、配置说明 |
| 删除 `legacy/` | 清理隔离区 | 此时 `legacy/` 应已被逐日删空，`git rm -r legacy/` 收尾 |

### 动作
1. 全量把 `print` 换成 `logging`（用 `contextvars` 或 filter 注入 `thread_id`）。
2. `session_service` 加 TTL 清理（可用现有 schedule 能力或后台定时协程）；统一从会话目录读取，去掉 updated→output 复制。
3. 补集成测（LLM 用 mock/录制），跑通 submit→WebSocket 事件→task_result。
4. 写 README；更新 `requirements.txt`（去 ragflow-sdk / mysql-connector 等已弃用项）。
5. **确认 `legacy/` 已空并删除**：`git rm -r legacy/`；若仍有残留文件，说明有旧逻辑未迁移，先补齐再删。
6. 全量 `ruff` + `pytest` 收尾。

### 验收
- `pytest`（全量）通过；核心模块（tools/rag/services）有测试覆盖。
- README 能让新人在 30 分钟内本地跑起来并建一次 RAG 库。
- `legacy/` 已删除，仓库只剩干净的 `app/`；无 demo/遗留物、无运行期数据入库。

---

## 收尾：Phase 1 完成判定
- P0（4 项）、P1（6 项）全部关闭；P2 主要项关闭。
- 应用在外部服务不可达时可启动；多用户并发下事件循环不阻塞。
- 全量测试通过，具备回归保障。
- 进入 Phase 2 的触发条件与方案见 `REFACTOR_PLAN.md` §10（撞到瓶颈再做，不提前）。

## 每日节奏建议
- 上午：写接口签名 + 实现；下午：补测试 + 自测 + 提交。
- 任一天验收不过 → 不进入下一天（里程碑串行依赖）。
- Day 6/7（DB/PDF）与 Day 9（RAG）是三个最容易超时的重点，预留半天缓冲。
