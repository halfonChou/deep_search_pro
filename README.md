# DeepSearch Pro

医药行业多 Agent 深度搜索系统。用户提交自然语言查询，系统自动规划任务、调度子 Agent 并行采集数据（MySQL 数据库、Tavily 互联网搜索、ChromaDB 知识库），汇总生成分析报告。

## 特性

- **多 Agent 架构**：主 Agent 规划 + 3 个子 Agent（网络搜索 / 知识库检索 / 数据库查询）并行执行
- **混合编排**：简单子 Agent 用 dict 声明，复杂子 Agent 用 LangGraph StateGraph
- **HITL 人工审批**：高风险 SQL 操作需用户审批后才执行
- **三层上下文管理**：大结果卸载（>4KB）→ LLM 摘要（>60K token）→ 机械裁剪（>80K token）
- **实时事件流**：WebSocket 推送 12 种事件，前端实时展示 Agent 工作过程
- **预算控制**：token 上限 + 费用上限 + 分工具限流
- **可观测性**：结构化日志（contextvars 异步安全）+ LangSmith 追踪

## 快速开始（30 分钟）

### 1. 环境准备

```bash
# Python 3.11+
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 或直接编辑 `.env`：

```env
# LLM（必填）
LLM_MODEL=qwen-max
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-your-key

# MySQL（必填，只读连接业务数据库）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root
MYSQL_DATABASE=pharma_db

# Tavily 搜索（必填）
TAVILY_API_KEY=tvly-your-key

# RAG 向量检索
EMBED_MODEL=text-embedding-v3

# LangSmith 可观测性（可选）
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_your-key
LANGSMITH_PROJECT=DeepSearchPro
```

### 3. 初始化知识库（可选）

```bash
# 将文档放入 data/docs/ 目录，然后运行：
python scripts/build_index.py
```

### 4. 启动服务

```bash
uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000
```

### 5. 提交任务

```bash
# 提交分析任务
curl -X POST "http://localhost:8000/task?query=分析布洛芬采购价格趋势&thread_id=test-001" \
  -H "Authorization: Bearer YOUR_TOKEN"

# 查看任务状态
curl "http://localhost:8000/task/test-001" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 6. 订阅实时事件

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/test-001");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

## 项目结构

```
app/
├── main.py                  # FastAPI 入口 + lifespan
├── config.py                # Pydantic Settings 配置
├── prompt.py                # Agent 提示词
├── logging_config.py        # 结构化日志（contextvars）
├── agents/
│   ├── main_agent.py        # 主 Agent 工厂
│   ├── deps.py              # 依赖注入容器
│   ├── events.py            # 12 种事件类型定义
│   ├── context.py           # RunContext 运行上下文
│   ├── stream.py            # Agent 流式输出 + 事件桥接
│   └── subagents/
│       ├── network_search.py    # 网络搜索子 Agent
│       ├── knowledge_base.py    # 知识库检索子 Agent
│       └── database_query.py    # 数据库查询子 Agent（LangGraph）
├── api/
│   ├── routes_task.py       # 任务提交/状态/取消/审批
│   └── routes_ws.py         # WebSocket 事件流
├── middleware/
│   ├── stack.py             # 中间件栈装配（顺序在此）
│   ├── budget.py            # 预算控制
│   ├── observability.py     # 事件发射
│   └── sql_guard.py         # SQL 安全拦截
├── tools/
│   ├── _offload.py          # 大结果卸载
│   ├── search_tools.py      # Tavily 搜索
│   ├── rag_tools.py         # RAG 检索
│   ├── sql_tools.py         # SQL 工具
│   ├── report_tools.py      # 历史报告查询
│   └── doc_tools.py         # 文档工具
├── services/
│   ├── task_service.py      # 任务生命周期管理
│   └── session_service.py   # 会话/报告持久化
├── infra/
│   ├── event_bus.py         # 事件总线（发布/订阅/重放）
│   ├── llm.py               # LLM 客户端构建
│   ├── checkpoint.py        # LangGraph checkpoint
│   └── db.py                # MySQL 连接池
└── rag/
    ├── embedder.py          # 向量编码器
    ├── store.py             # ChromaDB 封装
    ├── retriever.py         # 检索器
    └── ingest.py            # 文档导入

tests/
├── test_context_management.py   # 上下文管理单元测试
└── test_integration.py          # 集成测试

docs/
├── architecture.md          # 架构文档
├── context_strategy.md      # 三层上下文管理策略
└── use_cases.md             # 典型场景与调用链
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/task?query=...&thread_id=...` | 提交分析任务 |
| GET | `/task/{thread_id}` | 查询任务状态 |
| DELETE | `/task/{thread_id}` | 取消任务 |
| POST | `/task/{thread_id}/decision` | HITL 审批决策 |
| WS | `/ws/{thread_id}` | 订阅实时事件流 |

## 运行测试

```bash
pytest tests/ -v
```

## 文档

- [架构设计](docs/architecture.md)
- [上下文管理策略](docs/context_strategy.md)
- [使用场景](docs/use_cases.md)

## License

MIT
