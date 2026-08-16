# DeepSearch Pro 架构文档

## 系统概览

DeepSearch Pro 是一个面向医药行业的多 Agent 深度搜索系统。用户提交自然语言查询后，系统自动规划任务、调度多个子 Agent 并行采集数据（数据库、互联网、知识库），最终汇总生成分析报告。

```
┌───────────────────────────────────────────────────────────┐
│                      前端（浏览器）                         │
│              WebSocket ← 实时事件流推送                     │
└────────────┬──────────────────────────────┬────────────────┘
             │ POST /task                   │ WS /ws/{tid}
             ▼                              ▼
┌───────────────────────────────────────────────────────────┐
│                    FastAPI 应用层                           │
│  routes_task.py     routes_ws.py     routes_files.py      │
└────────────┬──────────────────────────────────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────────────┐
│                    TaskService                             │
│  幂等提交 │ 信号量限流 │ 取消传播 │ 事件发布               │
│  contextvars thread_id → 结构化日志                        │
└────────────┬──────────────────────────────────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────────────┐
│                中间件栈（由外到内）                          │
│                                                           │
│  ① EventEmitMiddleware    — 观测：量到含重试的真实耗时      │
│  ② BudgetMiddleware       — 预算：超限 → jump_to="end"     │
│  ③ ModelCallLimitMiddleware — 模型调用次数硬闸              │
│  ④ ToolCallLimitMiddleware  — 工具调用次数 + 分工具限流     │
│  ⑤ SqlGuardMiddleware     — SQL 拦截：非法语句不进重试      │
│  ⑥ ToolRetryMiddleware    — 瞬时故障退避重试               │
│  ⑦ ModelRetryMiddleware   — 模型调用重试                   │
│  ⑧ ModelFallbackMiddleware — 主模型不可用时降级             │
│  ⑨ TodoListMiddleware     — 提供 write_todos 任务规划      │
│  ⑩ SummarizationMiddleware — 60K token 触发 LLM 摘要      │
│  ⑪ ContextEditingMiddleware — 80K token 硬裁剪兜底         │
│                                                           │
│  顺序依据：                                                │
│  · 观测最外层才能测到真实耗时                                │
│  · SQL 拦截在重试外层，非法 SQL 不被重试 3 次                │
│  · 预算在重试之前，耗尽后不浪费重试                          │
│  · 摘要阈值(60K) < 裁剪阈值(80K)，先保语义后机械丢弃         │
└────────────┬──────────────────────────────────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────────────┐
│               主 Agent（项目经理角色）                       │
│                                                           │
│  · 收到任务先 write_todos 规划                              │
│  · 按描述委派给子 Agent                                     │
│  · list_past_reports 查历史报告避免重复                      │
│  · write_report 输出最终报告                                │
│                                                           │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐       │
│  │network   │  │knowledge_base│  │database_query  │       │
│  │_search   │  │              │  │(LangGraph      │       │
│  │(dict)    │  │(dict)        │  │ StateGraph)    │       │
│  │          │  │              │  │                │       │
│  │internet  │  │rag_search    │  │list_sql_tables │       │
│  │_search   │  │              │  │describe_table  │       │
│  └────┬─────┘  └──────┬───────┘  │get_table_data  │       │
│       │               │          │execute_sql_query│       │
│       │               │          │(HITL 审批)     │       │
│       ▼               ▼          └───────┬────────┘       │
│   Tavily API    ChromaDB 向量库      MySQL 数据库          │
└───────────────────────────────────────────────────────────┘
```

## 混合架构：Dict-based vs LangGraph

系统采用 **deepagents 框架**，子 Agent 有两种实现方式：

**Dict-based 子 Agent**（network_search、knowledge_base）：
- 用 Python dict 声明工具和 prompt
- deepagents 自动编译为可执行 Agent
- 适合线性工作流（搜索 → 返回）

**LangGraph StateGraph 子 Agent**（database_query）：
- 用 LangGraph 的 `StateGraph` 构建非线性工作流
- 支持条件路由（`should_continue` 判断是否需要更多数据）
- 通过 `CompiledSubAgent` 包装后接入 deepagents
- 适合需要循环/分支的复杂流程

这种混合设计让简单子 Agent 保持声明式的简洁，复杂子 Agent 获得状态机的表达力。


## 三层上下文管理

```
上下文膨胀 ──→ ┌─────────────┐     ┌──────────────┐     ┌───────────────┐
               │ L0 卸载      │ ──→ │ L1 摘要       │ ──→ │ L2 裁剪        │
               │ >4KB 落盘    │     │ >60K LLM压缩  │     │ >80K 机械清除   │
               │ 零 LLM 成本  │     │ 保语义        │     │ 零 LLM 成本    │
               └─────────────┘     └──────────────┘     └───────────────┘
```

详见 [docs/context_strategy.md](context_strategy.md)。


## 三层文件系统

| 层级 | 路径 | 存储 | 用途 | 用户可见 |
|------|------|------|------|----------|
| L0 草稿 | `/scratch/` | `checkpoints.sqlite`（虚拟） | 搜索原文、SQL 结果集 | 否 |
| L1 状态 | checkpointer | `checkpoints.sqlite` | 对话历史、Agent 状态 | 否 |
| L2 产出 | `data/sessions/<tid>/` | 真实磁盘 | 最终报告、可下载文件 | 是（HTTP 下载） |

**关键规则**：搜索原文走 L0，最终报告走 L2。绝不能把中间资料落到 L2，否则用户下载目录被垃圾塞满。


## HITL 人工审批

对于高风险操作（默认是 `execute_sql_query`），系统通过 LangGraph 的 `interrupt` 机制暂停执行：

1. Agent 调用 `execute_sql_query` → LangGraph 中断
2. `run_agent_stream` 检测到 `__interrupt__` → 发布 `interrupt` 事件
3. 前端收到事件 → 展示 SQL 语句，提供 approve / edit / reject 按钮
4. 用户决策 → `POST /task/{tid}/decision` → `TaskService.decide()`
5. `_resume()` 用 `Command(resume=...)` 恢复 LangGraph 执行


## 可观测性

**结构化日志**：
- `contextvars.ContextVar` 传递 `thread_id`，asyncio 并发安全
- `ThreadIdFilter` 自动注入每条日志，格式：`时间 | 级别 | tid=xxx | 模块 | 消息`
- 并发任务通过 `tid` 区分日志归属

**LangSmith 追踪**：
- 设置环境变量 `LANGSMITH_TRACING=true` 即自动生效
- 通过 LangChain 回调机制采集 Agent/Tool/LLM 调用链
- 在 LangSmith 控制台可视化查看每次运行的完整 trace

**EventBus 事件流**：
- 12 种事件类型覆盖 Agent 全生命周期
- WebSocket 实时推送 + 历史缓冲重放
- `EventEmitMiddleware` 在中间件最外层采集


## 技术栈

| 组件 | 技术选型 |
|------|---------|
| Web 框架 | FastAPI + Uvicorn |
| Agent 框架 | deepagents + LangGraph |
| LLM | 通义千问（qwen-max），OpenAI 兼容接口 |
| 向量数据库 | ChromaDB |
| 业务数据库 | MySQL |
| 状态持久化 | SQLite（checkpoints.sqlite） |
| 搜索引擎 | Tavily API |
| 可观测性 | LangSmith + 结构化日志 |
| 实时通信 | WebSocket |
