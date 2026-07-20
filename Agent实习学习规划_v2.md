# Deep Search Pro 项目学习 & Agent实习求职规划 (v2)

> **适用对象：** Usama（Python + FastAPI基础 + LangChain入门）
> **每日学习时间：** 4小时（2小时学/读 + 2小时写代码）
> **起止时间：** 2026年7月9日 - 2026年8月24日（共40个学习日）
> **休息安排：** 每周六休息
> **最终目标：** 拿到AI Agent方向实习offer
> **项目定位：** 药品销售数据分析智能助手（垂直场景，非"通用企业助手"）

---

## 与v1的核心变化

| 变化点 | v1 | v2 | 原因 |
|--------|----|----|------|
| 第一阶段 | 8天读代码 | 4天 | 1800行代码不需要8天，产出应是理解而非笔记 |
| 测试 | 无 | 重构时同步写pytest | 零测试是硬伤 |
| 第四阶段 | 6个feature平铺 | 按P0-P5分优先级 | 避免全做成半成品 |
| 前端 | 无 | 加2天Streamlit | 没有可演示界面是大减分项 |
| 场景 | "通用企业助手" | "药品销售数据分析助手" | 收窄场景才能讲好故事 |

---

## 总览

| 阶段 | 内容 | 天数 | 日期范围 |
|------|------|------|----------|
| 第一阶段 | 搞懂现有项目 | 4天 | 7/9 - 7/13 |
| 第二阶段 | LangGraph核心特训 | 5天 | 7/14 - 7/18 |
| 第三阶段 | 用原生LangGraph重构 + 同步写测试 | 10天 | 7/20 - 7/31 |
| 第四阶段 | 加分项（按优先级） | 8天 | 8/1 - 8/10 |
| 第五阶段 | Streamlit可演示前端 | 2天 | 8/11 - 8/12 |
| 第六阶段 | 项目包装 & GitHub整理 | 3天 | 8/13 - 8/15 |
| 第七阶段 | 面试准备 & 投递 | 6天+ | 8/17 - 8/24+ |

---

## 第一阶段：搞懂现有项目（4天）

**目标：** 能独立画出完整架构图，脱稿用2分钟讲清楚每一层的设计意图和数据流。

### Day 1 — 7月9日：API层 + 实时推送机制

- [x] 通读 `api/server.py`，画出所有API端点的请求/响应流程
- [x] 理解 FastAPI + WebSocket 的配合：HTTP触发任务，WebSocket推送进度
- [x] 精读 `api/monitor.py`，理解 ToolMonitor 单例 + 三通道推送
- [x] 精读 `api/context.py`，搞懂 ContextVar 的原理及为什么不能用全局变量
- [x] 本地跑通项目
- [x] **产出：** "请求从前端到后端的完整流转图"（手画）

### Day 2 — 7月10日：Agent编排 + 子Agent + Prompt设计

- [x] 精读 `agent/main_agent.py`，理解 `create_deep_agent` + `run_deep_agent` 全流程
- [x] 精读三个子Agent定义文件 + `prompt/prompts.yml`
- [x] 思考：main_agent prompt为什么要强调执行顺序？prompt设计有哪些要素？
- [x] **产出：** 注释版 `run_deep_agent`（自己的理解，不是抄课程注释）

### Day 3 — 7月11日：全部工具链 + deepagents源码

- [x] 精读6个工具文件（db_tools, tavily_tool, ragflow_tools, markdown_tools, pdf_tools, upload_file_read_tool）
- [x] **重点：** 找出 `execute_sql_query` 的SQL注入风险，写出修复思路
- [x] `pip show deepagents` 找到源码，搞懂 `create_deep_agent` 内部如何把子Agent字典转成LangGraph节点
- [x] **产出：** 工具清单表（输入/输出/作用）+ deepagents内部状态图

### Day 4 — 7月13日：全链路串讲 + 查漏补缺

- [x] 不看代码，画出完整架构图：前端 → API → Agent编排 → 子Agent → 工具 → 结果返回
- [x] 模拟面试：用2分钟讲清楚这个项目做了什么、怎么做的、为什么这样设计
- [x] 列出"还没搞懂的问题清单"
- [x] **产出：** 一份自己写的项目架构文档

> **7月14日起直接进入第二阶段，不留缓冲日——4天足够读懂这个体量的项目**

---

## 第二阶段：LangGraph核心特训（5天）

**目标：** 能用原生LangGraph独立构建多Agent系统，为重构做准备。

### Day 5 — 7月14日：LangGraph基础概念

- [x] 学习核心概念：StateGraph、State、Node、Edge、Conditional Edge
- [x] 官方文档：https://langchain-ai.github.io/langgraph/
- [x] 跑通官方quickstart示例
- [x] **产出：** 用LangGraph写一个最简单的"调用工具的单Agent"

### Day 6 — 7月15日：自定义State & 条件路由

- [x] 学习 TypedDict 定义自定义State
- [x] 学习 `add_conditional_edges` 实现动态路由
- [x] 练习：写一个根据用户意图路由到不同处理节点的Agent
- [x] **产出：** 一个带条件路由的Agent demo

### Day 7 — 7月16日：多Agent编排

- [x] 学习 LangGraph 的 subgraph 机制
- [x] 学习 Agent-as-tool 模式（把子Agent封装为工具）
- [x] 练习：用LangGraph构建一个主Agent调度两个子Agent的系统
- [x] **产出：** 一个多Agent协作的demo

### Day 8 — 7月17日：Checkpointer & 流式输出

- [x] 学习 MemorySaver、SqliteSaver 等持久化方案
- [x] 学习 `astream` 和 `astream_events` 的区别
- [x] 练习：给Day 7的demo加上持久化和流式输出
- [x] **产出：** 能断点续传的多Agent demo

### Day 9 — 7月18日：Human-in-the-loop & 中断机制

- [x] 学习 `interrupt_before` / `interrupt_after` 节点中断
- [x] 学习 LangGraph 的 human-in-the-loop 模式
- [x] 练习：在Agent执行SQL前插入人工确认步骤
- [x] **产出：** 带人工审批的Agent demo（重构时直接复用）

---

## 第三阶段：用原生LangGraph重构 + 同步写测试（10天）

**目标：** 去掉deepagents依赖，用原生LangGraph重写核心编排。每个模块写完同步写pytest。

> **核心原则：写一个模块，测一个模块。不要等最后再补测试。**

### Day 10 — 7月20日：设计新架构

- [ ] 定义自定义State（TypedDict）：messages、current_agent、task_status等
- [ ] 画出新的StateGraph：主Agent节点 → 条件路由 → 子Agent节点 → 工具节点
- [ ] 确定节点间的数据流转方式
- [ ] 搭建 `tests/` 目录结构，配置 pytest
- [ ] **产出：** 新架构设计文档 + StateGraph草图 + pytest配置

### Day 11 — 7月21日：重写主Agent节点

- [ ] 创建 `agent/graph.py`，定义StateGraph
- [ ] 实现主Agent节点：接收用户输入，决定调用哪个子Agent
- [ ] 实现路由函数：根据LLM输出判断下一步走向
- [ ] **写测试：** `tests/test_graph.py` — 测试路由逻辑（mock LLM响应，验证走向正确节点）
- [ ] **产出：** 能跑通的主Agent骨架 + 路由测试通过

### Day 12 — 7月22日：重写子Agent — 网络搜索

- [ ] 把网络搜索子Agent改为LangGraph子图（subgraph）
- [ ] 实现搜索Agent的内部状态管理
- [ ] 接入主Agent的条件路由
- [ ] **写测试：** `tests/test_network_agent.py` — mock Tavily API，验证搜索结果解析
- [ ] **产出：** 网络搜索子Agent重构完成 + 测试通过

### Day 13 — 7月23日：重写子Agent — 数据库查询

- [ ] 把数据库查询子Agent改为LangGraph子图
- [ ] **修复SQL注入：** 表名白名单校验 + execute_sql_query只读限制（禁止DROP/DELETE/UPDATE/INSERT）
- [ ] 加入Human-in-the-loop：SQL执行前需确认
- [ ] **写测试：** `tests/test_db_agent.py` — 测试SQL白名单拦截、只读限制、注入防护
- [ ] **产出：** 数据库子Agent重构完成 + 安全测试通过

### Day 14 — 7月24日：重写子Agent — 知识库检索（替换RAGFlow为本地RAG）

> **架构变更：** 去掉 `ragflow-sdk` 依赖，改用 LangChain + ChromaDB 搭建本地RAG pipeline。
> 好处：①不需要租服务器部署RAGFlow ②展示对RAG内部原理的理解 ③别人clone项目后零外部依赖即可跑通

- [ ] `pip install chromadb langchain-huggingface`（或用已有的通义千问Embedding接口）
- [ ] 创建 `knowledge_base/` 目录，放入药品知识文档（txt/pdf，几份即可）
- [ ] 重写 `tools/rag_tools.py`（替换原 `ragflow_tools.py`）：
  - 用 `DirectoryLoader` + `RecursiveCharacterTextSplitter` 加载和切分文档
  - 用 Embedding 模型向量化，存入 ChromaDB（持久化到 `data/chroma_db/`）
  - 封装为两个 `@tool`：`list_knowledge_bases`（列出可用知识库）和 `query_knowledge_base`（检索+返回相关片段）
- [ ] 把知识库子Agent改为LangGraph子图，接入新的RAG工具
- [ ] 优化错误处理和超时机制
- [ ] **写测试：** `tests/test_rag_agent.py` — 用小型测试文档验证切分、向量化、检索全流程
- [ ] **产出：** 本地RAG子Agent完成 + 测试通过 + `ragflow-sdk` 从 requirements.txt 中移除

### Day 15 — 7月25日：重写流式输出 & Monitor集成

- [ ] 用LangGraph的 `astream_events` 替换原来的chunk解析逻辑
- [ ] 适配Monitor的推送接口，确保前端能正常接收进度
- [ ] 测试WebSocket推送是否正常
- [ ] **产出：** 流式输出 + 实时推送重构完成

### Day 16 — 7月27日：工具链迁移 & 路径系统

- [ ] 把所有tools迁移到新架构，确保兼容
- [ ] 优化路径处理逻辑，统一使用Path
- [ ] 确保文件上传/下载/生成流程正常
- [ ] **消除重复代码：** `get_table_data` 和 `execute_sql_query` 合并公共逻辑
- [ ] **产出：** 工具链迁移完成

### Day 17 — 7月28日：场景收窄 & Prompt重写

- [ ] 把场景从"空调公司通用助手"收窄为**"药品销售数据分析助手"**
- [ ] 重写 main_agent 的 system_prompt：围绕药品销售场景，明确能力边界
- [ ] 重写子Agent prompt：数据库助手专注药品/销售表，RAG助手专注药品知识文档
- [ ] 准备2-3个典型使用场景（如："分析上季度哪些药品销量下降超过20%"）
- [ ] **产出：** 新版 prompts.yml + 场景用例文档

### Day 18 — 7月29日：端到端测试 & Debug

- [ ] 完整测试：用户提问 → 主Agent路由 → 子Agent执行 → 工具调用 → 结果返回
- [ ] 测试多轮对话场景
- [ ] 测试并发请求场景
- [ ] `pytest tests/ -v` 全部通过
- [ ] **产出：** 所有核心流程测试通过

### Day 19 — 7月30日：代码整理 & 重构收尾

- [ ] 删除deepagents依赖，清理requirements.txt
- [ ] 代码格式化，添加类型注解
- [ ] 删除所有教学注释，替换为简洁的docstring
- [ ] 添加 `.gitignore`（排除 __pycache__、.idea、.env、output/）
- [ ] 跑一遍完整流程确认无误
- [ ] **产出：** 重构完成，代码干净可读

---

## 第四阶段：加分项 — 按优先级排序（8天）

> **原则：按顺序做，做完一个再做下一个。时间不够就从底部砍，不要每个都做一半。**
>
> P0 = 不做就是减分项，必须完成
> P1 = 做了是明显加分项，强烈建议完成
> P2 = 锦上添花，有余力就做
> P3 = 了解概念即可，不建议硬塞进项目

### P0 — 结构化日志 + Agent可观测性（2天）

**为什么排第一：** 全项目用print输出是最明显的业余标志。LangSmith追踪是Agent项目标配，面试时可以展示trace截图，直观说明Agent的决策链路。

#### Day 20 — 7月31日：替换print为结构化日志

- [ ] 安装 `loguru` 或 `structlog`
- [ ] 替换全部 `print()` 为结构化日志（带级别、时间戳、模块名）
- [ ] 配置日志输出到文件 + 控制台
- [ ] 在工具调用和Agent决策点添加关键日志
- [ ] **产出：** 全项目零print，日志可读可查

#### Day 21 — 8月1日：LangSmith/LangFuse集成

- [ ] 注册LangSmith账号，获取API Key
- [ ] 集成LangSmith，实现Agent执行全链路追踪
- [ ] 记录每次工具调用的耗时和token消耗
- [ ] 截图保存几个典型trace（面试展示用）
- [ ] **产出：** 可观测性模块完成 + trace截图

---

### P1 — Agent评估系统（2天）

**为什么排第二：** 面试时能说"我的Agent在10个case上准确率80%，主要在多表联查场景失败"，比说"我做了个Agent挺好用的"强十倍。

#### Day 22 — 8月3日：设计评估用例 & 评估框架

- [ ] 设计10个测试case，覆盖：
  - 简单查询（"列出所有药品"）
  - 多表联查（"销量最高的药品价格是多少"）
  - RAG查询（"XX药品的使用说明"）
  - 网络搜索（"XX药品的行业趋势"）
  - 混合场景（"对比我们的XX药品和市场上竞品的情况"）
- [ ] 写评估框架：定义成功标准（结果正确性、工具选择正确性、响应时间）
- [ ] **产出：** `eval/test_cases.json` + `eval/evaluator.py` 框架

#### Day 23 — 8月4日：运行评估 & 输出报告

- [ ] 运行评估脚本，收集结果
- [ ] 统计：成功率、平均延迟、token消耗、各场景表现
- [ ] 分析失败case的原因，记录改进方向
- [ ] **产出：** `eval/report.md` 评估报告（含数据和分析）

---

### P2 — 重试 & Fallback策略（1天）

**为什么排第三：** 代码量不大但体现对生产环境稳定性的思考。面试时讲"我设计了容错机制"是加分项。

#### Day 24 — 8月5日：实现容错机制

- [ ] 工具调用失败后自动重试（最多3次，指数退避）
- [ ] 子Agent fallback：网络搜索超时时用RAG兜底
- [ ] 在StateGraph中加入 error_handler 节点
- [ ] **写测试：** `tests/test_fallback.py` — mock工具失败，验证重试和fallback触发
- [ ] **产出：** 容错机制完成 + 测试通过

---

### P3 — 对话记忆管理（1天）

**为什么排第四：** SqliteSaver替换InMemorySaver是有意义的改进，摘要压缩也是实用功能。但不是面试核心考点，优先级低于上面三个。

#### Day 25 — 8月6日：持久化记忆 + 摘要压缩

- [ ] 用 SqliteSaver 替换 InMemorySaver，实现重启不丢失对话
- [ ] 实现对话历史的摘要压缩（当消息超过N条时，用LLM压缩旧消息）
- [ ] 测试：重启服务后能继续之前的对话
- [ ] **产出：** 记忆管理模块完成

---

### P4 — 安全加固（1天）

**为什么排第五：** SQL注入已在第三阶段修了。这里做的是CORS白名单、文件上传限制等。面试时不是核心讲点，但做了说明你有安全意识。JWT对实习面试来说不是必需品，简化处理即可。

#### Day 26 — 8月7日：安全加固

- [ ] CORS 从 `allow_origins=["*"]` 改为配置化白名单
- [ ] 文件上传加大小限制（如10MB）和类型校验（白名单后缀）
- [ ] API加简单的API Key认证（不用JWT，用Header传Key即可，降低复杂度）
- [ ] SQL查询加超时限制
- [ ] **产出：** 安全加固完成

---

### P5 — MCP协议支持（2天）

**为什么排最后：** MCP是热点概念，面试可能会问，但硬塞进项目不如口头讲清楚。如果前面的都做完了且时间充裕，再做这个。否则只学概念，面试时口述即可。

> **如果时间紧张，这2天直接跳过，把时间给第五、六阶段。**

#### Day 27 — 8月8日：MCP基础 & Server实现

- [ ] 学习MCP协议基本概念（资源、工具、Prompt的区别）
- [ ] 把现有的数据库工具用MCP协议暴露为MCP Server
- [ ] **产出：** MCP Server基础实现

#### Day 28 — 8月10日：MCP Client & 动态工具加载

- [ ] 写MCP Client demo验证连通性
- [ ] 让Agent能通过MCP动态发现和加载工具
- [ ] 测试通过MCP调用工具的完整链路
- [ ] **产出：** 动态工具加载机制（如果来不及，至少留一个能跑的MCP Server demo）

---

## 第五阶段：Streamlit可演示前端（2天）

**为什么加这个阶段：** 没有可演示的界面，面试官无法直观看到效果。录屏也需要一个界面。Streamlit是最快的方案，不需要前端经验。

### Day 29 — 8月11日：搭建对话界面

- [ ] `pip install streamlit`
- [ ] 实现基础对话界面：输入框 + 聊天气泡 + 流式输出显示
- [ ] 对接后端API（POST /api/task + WebSocket接收推送）
- [ ] 显示Agent执行进度（哪个子Agent在工作、调用了哪个工具）
- [ ] **产出：** 能对话的基础界面

### Day 30 — 8月12日：完善界面 + 文件功能

- [ ] 添加文件上传功能（对接 /api/upload）
- [ ] 添加生成文件的下载按钮（对接 /api/download）
- [ ] 侧边栏显示会话历史
- [ ] 美化界面，加上项目名称和说明
- [ ] **产出：** 完整可演示的前端界面

---

## 第六阶段：项目包装 & GitHub整理（3天）

**目标：** 让项目在GitHub上看起来专业，简历上写起来有料。

### Day 31 — 8月13日：GitHub整理 & README

- [ ] 整理项目结构，确保目录清晰
- [ ] 写专业的README：项目介绍、架构图（Mermaid）、技术栈、快速开始、演示截图/GIF
- [ ] 添加 `.gitignore`（已在第三阶段完成，检查即可）
- [ ] 确认项目能一键跑通（别人clone下来按README能直接用）
- [ ] **产出：** GitHub仓库整理完成

### Day 32 — 8月14日：简历项目描述 & 技术博客

- [ ] 写简历中的项目描述（STAR法则）：
  - **S:** 企业需要从多个数据源（数据库/知识库/互联网）获取信息并生成分析报告
  - **T:** 设计并实现基于LangGraph的多Agent协作系统
  - **A:** 用原生LangGraph替代封装库实现状态编排；修复SQL注入风险并加入Human-in-the-loop；集成LangSmith实现全链路追踪；设计10个评估case验证系统准确率
  - **R:** 系统在10个评估场景中达到X%准确率，支持多轮对话和并发会话
- [ ] 写1篇技术博客（发掘金/知乎）："从deepagents到原生LangGraph：我为什么要重构一个多Agent系统"
- [ ] **产出：** 简历项目段 + 技术博客

### Day 33 — 8月15日：录制Demo & 完善细节

- [ ] 用Streamlit界面录一段演示视频（2-3分钟），覆盖：
  - 一个完整的查询流程（看到Agent选择子Agent、调用工具、返回结果）
  - 文件上传和报告生成
  - LangSmith trace截图
- [ ] 完善README中的演示GIF/截图
- [ ] 最终检查：所有测试通过、文档完整、代码无教学注释
- [ ] **产出：** 项目进入可展示状态

---

## 第七阶段：面试准备 & 投递（6天+）

### Day 34 — 8月17日：项目讲解 & Agent高频题

- [ ] 练习2分钟项目讲解（练3遍以上，录屏复盘）：
  - 30秒讲场景和目标
  - 60秒讲架构和技术选型（为什么LangGraph、为什么多Agent而非单Agent多工具）
  - 30秒讲亮点（安全修复、评估体系、可观测性）
- [ ] 准备高频题：
  - Agent的核心组成？（规划、记忆、工具调用、反思）
  - LangGraph和LangChain的区别？为什么选LangGraph？
  - 多Agent vs 单Agent多工具，各自优劣？
  - 什么是MCP？（即使没做也要能讲清楚概念）
  - Agent幻觉问题怎么处理？
  - RAG的完整流程？你为什么用ChromaDB而不是RAGFlow？chunking策略怎么选？

### Day 35 — 8月18日：深度技术问题准备

- [ ] 准备以下问题：
  - ContextVar vs threading.local？
  - WebSocket vs SSE？你为什么选WebSocket？
  - SQL注入怎么防？你做了什么？
  - 你项目的评估结果怎么样？哪些case表现不好？为什么？
  - 如果让你重新设计，你会改什么？
  - LangGraph的State是怎么在节点间传递的？checkpointer的作用？
  - 你对比过CrewAI/AutoGen/LangGraph吗？trade-off是什么？

### Day 36 — 8月19日：模拟面试

- [ ] 找朋友或用AI模拟技术面试
- [ ] 练习被追问时的应对（不会就说不会，但要说出你会怎么去查/学）
- [ ] 复盘录音，找出薄弱环节补强
- [ ] **产出：** 流畅的项目讲解 + 模拟面试复盘

### Day 37 — 8月20日：简历定稿 & 岗位调研

- [ ] 简历定稿
- [ ] 调研目标公司：
  - **第一梯队（难度高）：** 字节(Coze)、蚂蚁(百灵)、月之暗面、智谱
  - **第二梯队（机会大）：** AI创业公司、传统企业AI部门、外包公司AI团队
  - 实习不要只盯大厂，中小公司更容易拿到机会，积累经验后再跳
- [ ] 整理每家公司的Agent产品方向
- [ ] **产出：** 定稿简历 + 目标公司清单

### Day 38 — 8月21日：开始投递

- [ ] 第一批投递（10家，大厂+创业公司混投）
- [ ] 优先走内推渠道（脉脉、LinkedIn、牛客、Boss直聘）
- [ ] 准备每家公司的定制化自我介绍

### Day 39-40+ — 8月22日起：持续投递 & 面试迭代

- [ ] 每天投3-5家
- [ ] 每次面试后复盘，补充薄弱环节
- [ ] 根据面试反馈迭代项目和回答
- [ ] 关注Agent领域动态（Twitter/GitHub/arxiv）

---

## 关键资源

| 资源 | 链接 | 用途 |
|------|------|------|
| LangGraph官方文档 | https://langchain-ai.github.io/langgraph/ | 第二、三阶段核心 |
| LangGraph教程 | https://langchain-ai.github.io/langgraph/tutorials/ | 跟着做demo |
| MCP协议规范 | https://modelcontextprotocol.io/ | 第四阶段P5 |
| LangSmith | https://smith.langchain.com/ | 可观测性 |
| ChromaDB文档 | https://docs.trychroma.com/ | 第三阶段本地RAG |
| Streamlit文档 | https://docs.streamlit.io/ | 第五阶段前端 |
| pytest文档 | https://docs.pytest.org/ | 测试 |

---

## 里程碑检查点

| 检查点 | 日期 | 验收标准 |
|--------|------|----------|
| 能画出架构图并讲清楚 | 7/13 | 不看代码，2分钟讲完 |
| LangGraph独立写多Agent | 7/18 | demo能跑通 |
| 重构完成 + 测试通过 | 7/30 | `pytest tests/ -v` 全绿，零deepagents依赖 |
| P0-P1加分项完成 | 8/4 | 日志+追踪+评估报告都有 |
| P2-P4完成 | 8/7 | 容错+记忆+安全 |
| 可演示前端 | 8/12 | Streamlit界面能正常对话和展示 |
| GitHub可展示 | 8/15 | README专业，能一键跑，有演示视频 |
| 开始投递 | 8/21 | 第一批10家 |

---

## 如果时间不够怎么砍

按以下顺序从底部砍掉，**绝不能砍的是前面的**：

1. **第一个砍：** P5 MCP协议（省2天）→ 面试时口述概念即可
2. **第二个砍：** P4 安全加固的API Key认证部分（省半天）→ 只保留CORS和文件限制
3. **第三个砍：** P3 对话记忆的摘要压缩（省半天）→ 只做SqliteSaver替换
4. **绝不能砍：** 重构本身、测试、P0日志追踪、P1评估系统、Streamlit前端、项目包装

---

## 每日学习模板

```
## 日期：____

### 今日目标
-

### 学习内容 & 笔记（简洁，不要抄课程）
-

### 代码产出（具体文件名和改动）
-

### 测试情况（pytest结果）
-

### 遇到的问题 & 解决方式
-

### 明日计划
-
```