# deep_search_pro 依赖与环境需求文档

> 配套：`REFACTOR_PLAN.md`（架构）、`REFACTOR_EXECUTION_PLAN.md`（每日落地）。
> 本文把重构后的技术选型落成**可执行的依赖清单**：运行环境要求、按功能分组的依赖（用途 / 所属层 / 增·留·删）、相对现有 `requirements.txt` 的变更对照、版本策略，以及环境搭建命令（conda 环境名 **deepagent**）。

---

## 1. 运行环境要求（Runtime Requirements）

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | **Windows 10/11** | Word→PDF 依赖 COM（`pywin32`），生产部署在 Windows |
| Python | **3.11**（3.10 起可用） | 代码用到 `X | None` 联合类型、`asyncio.to_thread` 等，需 ≥3.10；选 3.11 兼顾稳定与生态 |
| 关系数据库 | **MySQL 8+**（业务数据源，只读） | Agent 查询用；通过异步驱动 `asyncmy` 连接 |
| 本机软件 | **Microsoft Word** | `WordPdfConverter` 通过 COM 调用，运行在独立子进程 |
| LLM 服务 | OpenAI 兼容接口（Qwen-Max） | 对话与 Embedding 复用同一 `base_url` |
| 搜索服务 | Tavily API Key | 网络搜索子 Agent |
| 本地存储 | 文件系统（`data/`） | SQLite（checkpoint）、Chroma（向量库）均落本地目录，**无需额外服务** |

> Phase 1 不依赖 Redis / Postgres / 消息队列（理由与升级触发条件见 `REFACTOR_PLAN.md` §4、§10）。

---

## 2. 依赖清单（按功能分组）

标记：🟢 保留 ｜ 🔵 新增 ｜ 🔴 删除 ｜ ⚪ 待核实（疑似未使用，确认后删）

### 2.1 Web / 服务框架 — 层：API / 应用
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| fastapi | 🟢 | 0.129.2 | HTTP + WebSocket 服务 |
| uvicorn | 🟢 | 0.41.0 | ASGI 服务器 |
| python-multipart | 🟢 | 0.0.22 | 文件上传解析 |
| websockets | 🟢 | 15.0.1 | WebSocket 实时推送 |
| aiofiles | 🟢 | 25.1.0 | 异步文件读写 |
| pydantic | 🟢 | 2.12.5 | 数据模型 / Schema |
| pydantic-settings | 🟢 | 2.13.1 | 集中式配置 `Settings`（修 P1-4） |
| python-dotenv | 🟢 | 1.2.1 | 加载 `.env` |

### 2.2 Agent 编排 — 层：领域 / Agent
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| deepagents | 🟢 | 0.4.3 | 主 / 子 Agent 高层编排 |
| langgraph | 🟢 | 1.0.9 | 图执行、流式事件、精细控制 |
| langgraph-checkpoint | 🟢 | 4.0.0 | checkpoint 抽象基类 |
| **langgraph-checkpoint-sqlite** | 🔵 | 安装时最新兼容 | `AsyncSqliteSaver` 状态持久化（替换 InMemorySaver，修 P0-4） |
| langchain | 🟢 | 1.2.10 | 工具 / 消息抽象 |
| langchain-core | 🟢 | 1.2.14 | 核心类型、`@tool` |
| langchain-openai | 🟢 | 1.1.10 | OpenAI 兼容 LLM / Embedding 接入 |
| langchain-text-splitters | 🟢 | 1.1.1 | RAG 分块 |
| tiktoken | 🟢 | 0.12.0 | token 计数 / 分块度量 |
| langchain-community | ⚪ | 0.4.1 | 若无实际引用则删（确认后处理） |
| langchain-google-genai | 🔴 | 4.2.1 | 未用 Gemini，删 |
| google-genai | 🔴 | 1.64.0 | 同上，删 |
| anthropic | 🔴 | 0.83.0 | 未用 Claude（使用 Qwen），删 |

### 2.3 数据库 — 层：基础设施 / 工具
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| **asyncmy** | 🔵 | 安装时最新兼容 | 异步 MySQL 驱动 + 连接池（修 P0-1 阻塞） |
| mysql-connector-python | 🔴 | 9.6.0 | 同步驱动，被 asyncmy 取代，删 |
| SQLAlchemy | ⚪ | 2.0.46 | 若不用 ORM 则删（确认 langchain-community 是否需要） |

### 2.4 RAG / 向量 — 层：RAG 模块
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| **chromadb** | 🔵 | 安装时最新兼容 | 自研 RAG 的向量库（本地持久化） |
| ragflow-sdk | 🔴 | 0.24.0 | 被自研 RAG 取代，删 |

### 2.5 搜索 / LLM
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| tavily-python | 🟢 | 0.7.21 | 网络搜索工具 |
| openai | 🟢 | 2.21.0 | LLM + Embedding（OpenAI 兼容 Qwen） |

### 2.6 文档处理 — 层：工具 / RAG 摄取
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| python-docx | 🟢 | 1.2.0 | 读/写 Word、RAG 摄取解析 |
| pypdf | 🟢 | 6.7.2 | 读取 PDF 文本 |
| openpyxl | 🟢 | 3.1.5 | 读取 xlsx |
| pandas | 🟢 | 3.0.1 | 表格数据处理 |
| numpy | 🟢 | 2.4.2 | 数值（pandas / 向量依赖） |
| Markdown | 🟢 | 3.10.2 | Markdown 渲染 |
| pymdown-extensions | 🟢 | 10.21 | Markdown 扩展 |
| pywin32 | 🟢 | 311 | **Word COM（PDF 转换，Windows）** |

### 2.7 PDF 引擎（当前用 Word COM，其余为候选/延后）
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| weasyprint | ⚪ | 68.1 | Phase 2 Linux 跨平台 PDF 备选，暂留 |
| md2pdf | ⚪ | 3.1.0 | 疑似未用，确认后删 |
| xhtml2pdf | ⚪ | 0.2.17 | 疑似未用，确认后删 |
| reportlab | ⚪ | 4.4.10 | 疑似未用，确认后删 |
| svglib | ⚪ | 1.6.0 | 疑似未用，确认后删 |
| pyHanko | ⚪ | 0.33.0 | PDF 签名，未用则删 |

### 2.8 通用 / 工具
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| tenacity | 🟢 | 9.1.4 | LLM / 工具调用重试 |
| PyYAML | 🟢 | 6.0.3 | 加载 `prompts.yml` |
| requests | 🟢 | 2.32.5 | 同步 HTTP（部分 SDK 依赖） |
| httpx | 🟢 | 0.28.1 | 异步 HTTP |

### 2.9 开发 / 测试（新增，dev 依赖）
| 包 | 标记 | 版本 | 用途 |
|---|---|---|---|
| **pytest** | 🔵 | 安装时最新兼容 | 单元 / 集成测试 |
| **pytest-asyncio** | 🔵 | 安装时最新兼容 | 异步测试 |
| **ruff** | 🔵 | 安装时最新兼容 | Lint / 格式检查 |
| mypy | 🔵（可选） | 安装时最新兼容 | 静态类型检查（可选） |

> 其余未列出的包（`anyio`、`starlette`、`orjson`、`certifi` 等）为上述库的**传递依赖**，由 pip 自动解析，无需手动管理。

---

## 3. 相对现有 requirements.txt 的变更对照

**🔵 新增（5 必需 + 1 可选）**
`asyncmy`、`chromadb`、`langgraph-checkpoint-sqlite`、`pytest`、`pytest-asyncio`、`ruff`（`mypy` 可选）

**🔴 删除（5）**
`ragflow-sdk`、`mysql-connector-python`、`anthropic`、`google-genai`、`langchain-google-genai`

**⚪ 待核实后决定（疑似未使用）**
`md2pdf`、`xhtml2pdf`、`reportlab`、`svglib`、`pyHanko`、`langchain-community`、`SQLAlchemy`
> 建议：Day 10 收尾时用 `pip check` + 全局 grep 确认无引用后再删，避免误删传递依赖。

---

## 4. 版本策略

- **已存在的包**：沿用你当前 `requirements.txt` 的锁定版本（上表所列），不擅自升级，降低重构期变量。
- **新增的包**：标注"安装时最新兼容"——因为本项目环境版本较新，硬编码可能不匹配。做法是先装、跑通，再 `pip freeze` 锁定写回 `requirements.txt`。
- **锁定原则**：生产依赖全部 `==` 精确锁定；dev 依赖可略宽松。建议后续拆分 `requirements.txt`（运行）与 `requirements-dev.txt`（开发）。

---

## 5. 环境搭建（conda 环境名：deepagent）

### 5.1 创建并激活环境
```bash
# 1. 创建新环境（环境名 deepagent，Python 3.11）
conda create -n deepagent python=3.11 -y

# 2. 激活
conda activate deepagent

# 3. 升级 pip
python -m pip install --upgrade pip
```

### 5.2 安装依赖
```bash
# 先按现有 requirements.txt 安装
pip install -r requirements.txt

# 安装重构新增依赖
pip install asyncmy chromadb langgraph-checkpoint-sqlite
pip install pytest pytest-asyncio ruff

# 卸载已弃用依赖
pip uninstall -y ragflow-sdk mysql-connector-python anthropic google-genai langchain-google-genai

# 安装完跑通后，锁定版本写回
pip freeze > requirements.txt
```

> 说明：以上包绝大多数为 **pip-only**，故用 conda 建纯净 Python 环境、再用 pip 安装，是最稳妥的组合。`pywin32` 仅在 Windows 有效；`asyncmy` 在 Windows 由 pip 直接安装预编译 wheel。

### 5.3 一键复制版（最常用）
```bash
conda create -n deepagent python=3.11 -y && conda activate deepagent && python -m pip install --upgrade pip && pip install -r requirements.txt
```

---

## 6. 验证环境就绪
```bash
conda activate deepagent
python -c "import fastapi, langgraph, deepagents, chromadb, asyncmy; print('core deps OK')"
python -c "import langgraph.checkpoint.sqlite; print('sqlite saver OK')"
ruff --version && pytest --version
```
全部无报错即表示环境可用。
