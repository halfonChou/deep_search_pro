# 典型使用场景与预期调用链

## 场景一：药品价格异常监测

**用户输入**：`"分析最近3个月布洛芬的采购价格趋势，找出异常波动"`

**预期调用链**：

1. 主 Agent 收到查询 → `write_todos` 规划步骤
2. 主 Agent 调 `list_past_reports(keyword="布洛芬")` → 检查是否有历史报告可复用
3. 委派 `database_query` 子 Agent：
   - `list_sql_tables` → 发现 `purchase_orders`、`drug_catalog` 表
   - `describe_table("purchase_orders")` → 了解字段
   - `execute_sql_query("SELECT ...")` → **触发 HITL 中断**
   - 用户审批 approve → 恢复执行
   - SQL 结果 > 4KB → `offload_if_large` 落盘至 `/scratch/sql-xxx.txt`
4. 委派 `network_search` 子 Agent：
   - `internet_search("布洛芬 原料药 价格 2024")` → 获取市场参考价
   - 搜索结果 > 4KB → 落盘，只留 200 字摘要
5. 主 Agent 汇总分析 → `write_report` 输出到 `data/sessions/<tid>/report.md`
6. 前端通过 WebSocket 实时收到全部事件流

**上下文管理触发**：
- 第 3 步 SQL 大结果触发 L0 卸载
- 第 4 步搜索原文触发 L0 卸载
- 若对话 > 60K token → 摘要中间件压缩
- 若对话 > 80K token → 裁剪中间件清除旧工具结果（write_todos 受保护）


## 场景二：药品合规审查

**用户输入**：`"检查阿莫西林胶囊的GMP认证是否过期，对比FDA最新要求"`

**预期调用链**：

1. 主 Agent → `write_todos` 规划
2. 委派 `database_query`：查本地数据库的 GMP 认证信息
3. 委派 `knowledge_base`：`rag_search("GMP认证 过期判定标准")` → 从内部知识库检索
4. 委派 `network_search`：`internet_search("FDA GMP requirements 2024")` → 搜最新法规
5. 主 Agent 汇总：对比内部记录 vs 法规要求 → 生成合规报告

**关键点**：
- RAG 检索结果若 > 4KB 也会触发卸载
- 三个子 Agent 可以并行（由 deepagents 调度）


## 场景三：供应商比价分析

**用户输入**：`"对比三家供应商的维生素C原料报价，推荐最优采购方案"`

**预期调用链**：

1. 主 Agent → `write_todos`
2. `database_query`：`execute_sql_query` 查三家供应商历史报价（需审批）
3. `network_search`：搜索市场行情参考
4. `knowledge_base`：检索内部采购政策文档
5. 主 Agent：交叉比对 → 推荐方案 → `write_report`

**预算控制**：
- BudgetMiddleware 跟踪总 token 消耗
- 搜索工具有独立限流（`search_tool_run_limit=5`）
- SQL 工具有独立限流（`sql_tool_run_limit=10`）


## 场景四：长对话中的上下文管理

**用户输入**：连续 15 轮追问药品分析

**事件时间线**：

| 轮次 | 事件 | 触发 |
|------|------|------|
| 1-5 | 正常对话 + 工具调用 | 搜索/SQL 大结果触发 L0 卸载 |
| 6-8 | 累计 token > 60K | SummarizationMiddleware 触发，LLM 压缩历史 |
| 9-11 | 压缩后仍 > 80K | ContextEditingMiddleware 裁剪旧工具结果 |
| 12-15 | 稳定运行 | write_todos 计划始终保留，Agent 不迷路 |

**验证要点**：
- 第 15 轮不报 `context length exceeded`
- 裁剪后 `write_todos` 结果仍在上下文中
- 日志能看到三层依次触发的记录
