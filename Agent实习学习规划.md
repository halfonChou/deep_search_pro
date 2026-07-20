# Deep Search Pro 项目学习 & Agent实习求职规划

> **适用对象：** Usama（Python + FastAPI基础 + LangChain入门）
> **每日学习时间：** 4小时
> **起止时间：** 2026年7月9日 - 2026年8月24日（共40个学习日）
> **休息安排：** 每周六休息
> **最终目标：** 拿到AI Agent方向实习offer

---

## 总览

| 阶段 | 内容 | 天数 | 日期范围 |
|------|------|------|----------|
| 第一阶段 | 搞懂现有项目 | 8天 | 7/9 - 7/18 |
| 第二阶段 | LangGraph核心特训 | 5天 | 7/20 - 7/24 |
| 第三阶段 | 用原生LangGraph重构项目 | 10天 | 7/25 - 8/7 |
| 第四阶段 | 添加面试加分项 | 8天 | 8/8 - 8/17 |
| 第五阶段 | 项目包装 & GitHub整理 | 3天 | 8/18 - 8/20 |
| 第六阶段 | 面试准备 & 投递 | 6天 | 8/21 - 8/24+ |

---

## 第一阶段：搞懂现有项目（8天）

**目标：** 能独立画出完整架构图，能脱稿讲清楚每一层的设计意图和数据流向。

### Day 1 — 7月9日（周三）：项目全貌 & API层

- [x] 通读 `api/server.py`，画出所有API端点的请求/响应流程
- [x] 理解 FastAPI + WebSocket 的配合方式：HTTP触发任务，WebSocket推送进度
- [x] 本地跑通项目（配置.env，启动server，用Postman/curl发请求）
- [x] **产出：** 手画一张"请求从前端到后端的完整流转图"

### Day 2 — 7月10日（周四）：主Agent编排逻辑（项目的"大脑"）

> **学习原则：** 先搞懂"谁在干活、怎么干活"，再学"怎么汇报、怎么隔离"。

- [x] 精读 `agent/llm.py`，理解 LLM 模型的加载方式（init_chat_model + .env）
- [ ] 精读 `agent/main_agent.py`，理解 `create_deep_agent` 的参数含义
- [ ] 重点分析 `run_deep_agent` 函数：session创建、路径处理、提示词拼接、流式处理
- [ ] 理解 `astream` 返回的 chunk 结构：`{node_name: {messages: [...]}}`
- [ ] 理解 tool_call 的判断逻辑：`name == 'task'` 代表调用子Agent
- [ ] **产出：** 注释版 `run_deep_agent`，每一行都写上自己的理解

### Day 3 — 7月11日（周五）：进度推送 & 会话隔离（项目的"嘴巴"和"隔离墙"）

> **为什么放在 main_agent 后面：** 你已经看到 `run_deep_agent` 里调了 `monitor.report_xxx()` 和 `set_session_context()`，现在带着"为什么需要它们"的问题去读，才能理解。

- [x] 精读 `api/monitor.py`，理解 ToolMonitor 单例模式 + 三通道推送（WebSocket / builtins / print）
- [x] 重点理解：`_emit()` 中 `run_coroutine_threadsafe` vs `create_task` 的使用场景
- [x] 理解 `set_websocket_manager` 的作用：把"对讲机"交给"广播员"
- [x] 精读 `api/context.py`，搞懂 ContextVar 的原理
- [x] 对比理解：全局变量 vs threading.local vs ContextVar 三者的区别
- [ ] **产出：** 用自己的话写一段"为什么用ContextVar而不是全局变量"的解释（面试会问）

### Day 4 — 7月13日（周日）：子Agent & Prompt设计

- [ ] 精读三个子Agent定义文件，理解dict方式创建子Agent的结构
- [ ] 精读 `prompt/prompts.yml`，分析每个Agent的system_prompt设计
- [ ] 思考：为什么main_agent的prompt要强调"执行顺序"和"禁止并行调用"？
- [ ] 精读 `agent/prompts.py` 和 `agent/llm.py`，理解配置加载方式
- [ ] **产出：** 总结"好的Agent Prompt应该包含哪些要素"（这是面试高频题）

### Day 5 — 7月14日（周一）：工具链（上）— 数据库 & 网络搜索

- [ ] 精读 `tools/db_tools.py`，理解三个数据库工具的设计
- [ ] **安全分析：** 找出SQL注入风险点，思考如何修复
- [ ] 精读 `tools/tavily_tool.py`，理解Tavily搜索工具的封装
- [ ] 理解 `@tool` 装饰器的作用：把普通函数变成LangChain Tool
- [ ] **产出：** 写出db_tools的安全修复方案（面试必问点）

### Day 6 — 7月15日（周二）：工具链（下）— RAG & 文件处理

- [ ] 精读 `tools/ragflow_tools.py`，理解RAGFlow的交互流程
- [ ] 精读 `tools/markdown_tools.py`、`tools/pdf_tools.py`、`tools/upload_file_read_tool.py`
- [ ] 理解路径处理工具 `utils/path_utils.py` 和 `utils/word_converter.py`
- [ ] 画出"工具调用链"：Agent决定调用 → Monitor埋点 → 工具执行 → 结果返回
- [ ] **产出：** 整理一张"全部工具清单表"，包含每个工具的输入/输出/作用

### Day 7 — 7月16日（周三）：deepagents源码剖析

- [ ] `pip show deepagents` 找到源码位置，阅读核心代码
- [ ] 重点搞懂：`create_deep_agent` 内部如何把子Agent字典转成LangGraph节点
- [ ] 搞懂：子Agent是如何被当作tool_call来调度的
- [ ] 搞懂：checkpointer（InMemorySaver）在内部如何工作
- [ ] **产出：** 画出"deepagents内部的LangGraph状态图"，标注节点和边

### Day 8 — 7月17日（周四）：全链路串讲 & 查漏补缺

- [ ] 不看代码，画出完整架构图：前端 → API → Agent编排 → 子Agent → 工具 → 结果返回
- [ ] 模拟面试：用2分钟讲清楚这个项目做了什么、怎么做的、为什么这样设计
- [ ] 整理第一阶段的所有笔记和产出
- [ ] 列出"我还没搞懂的问题清单"，后续阶段逐个解决
- [ ] **产出：** 一份完整的项目架构文档（自己写的，不是抄注释）

> **7月18日（周五）：** 缓冲日，消化前8天内容，处理遗留问题
> **7月19日（周六）：** 休息

---

## 第二阶段：LangGraph核心特训（5天）

**目标：** 能用原生LangGraph独立构建多Agent系统，为重构做准备。

### Day 9 — 7月20日（周日）：LangGraph基础概念

- [ ] 学习核心概念：StateGraph、State、Node、Edge、Conditional Edge
- [ ] 官方文档：https://langchain-ai.github.io/langgraph/
- [ ] 跑通官方quickstart示例
- [ ] **产出：** 用LangGraph写一个最简单的"调用工具的单Agent"

### Day 10 — 7月21日（周一）：自定义State & 条件路由

- [ ] 学习 TypedDict 定义自定义State
- [ ] 学习 `add_conditional_edges` 实现动态路由
- [ ] 练习：写一个根据用户意图路由到不同处理节点的Agent
- [ ] **产出：** 一个带条件路由的Agent demo

### Day 11 — 7月22日（周二）：多Agent编排

- [ ] 学习 LangGraph 的 subgraph 机制
- [ ] 学习 Agent-as-tool 模式（把子Agent封装为工具）
- [ ] 练习：用LangGraph构建一个主Agent调度两个子Agent的系统
- [ ] **产出：** 一个多Agent协作的demo

### Day 12 — 7月23日（周三）：Checkpointer & 流式输出

- [ ] 学习 MemorySaver、SqliteSaver 等持久化方案
- [ ] 学习 `astream` 和 `astream_events` 的区别
- [ ] 练习：给Day 11的demo加上持久化和流式输出
- [ ] **产出：** 能断点续传的多Agent demo

### Day 13 — 7月24日（周四）：Human-in-the-loop & 中断机制

- [ ] 学习 `interrupt_before` / `interrupt_after` 节点中断
- [ ] 学习 LangGraph 的 human-in-the-loop 模式
- [ ] 练习：在Agent执行SQL前插入人工确认步骤
- [ ] **产出：** 带人工审批的Agent demo（后面重构直接用）

> **7月25日（周五）直接进入第三阶段**
> **7月26日（周六）：** 休息

---

## 第三阶段：用原生LangGraph重构项目（10天）

**目标：** 去掉deepagents依赖，用原生LangGraph重写核心编排，同时修复安全问题。

### Day 14 — 7月25日（周五）：设计新架构

- [ ] 定义项目的自定义State（TypedDict）：messages、current_agent、task_status等
- [ ] 画出新的StateGraph：主Agent节点 → 条件路由 → 子Agent节点 → 工具节点
- [ ] 确定节点间的数据流转方式
- [ ] **产出：** 新架构设计文档 + StateGraph草图

### Day 15 — 7月27日（周日）：重写主Agent节点

- [ ] 创建新文件 `agent/graph.py`，定义StateGraph
- [ ] 实现主Agent节点：接收用户输入，决定调用哪个子Agent
- [ ] 实现路由函数：根据LLM输出判断下一步走向
- [ ] **产出：** 能跑通的主Agent骨架（先不接子Agent）

### Day 16 — 7月28日（周一）：重写子Agent — 网络搜索

- [ ] 把网络搜索子Agent改为LangGraph子图（subgraph）
- [ ] 实现搜索Agent的内部状态管理
- [ ] 接入主Agent的条件路由
- [ ] 测试：主Agent能正确调度网络搜索子Agent
- [ ] **产出：** 网络搜索子Agent重构完成

### Day 17 — 7月29日（周二）：重写子Agent — 数据库查询

- [ ] 把数据库查询子Agent改为LangGraph子图
- [ ] **修复SQL注入：** 加入表名白名单校验，execute_sql_query加只读限制
- [ ] 加入Human-in-the-loop：SQL执行前需要确认
- [ ] **产出：** 数据库子Agent重构完成 + 安全修复

### Day 18 — 7月30日（周三）：重写子Agent — RAGFlow

- [ ] 把RAGFlow子Agent改为LangGraph子图
- [ ] 优化错误处理和超时机制
- [ ] 接入主Agent路由
- [ ] **产出：** RAGFlow子Agent重构完成

### Day 19 — 7月31日（周四）：重写流式输出 & Monitor集成

- [ ] 用LangGraph的 `astream_events` 替换原来的chunk解析逻辑
- [ ] 适配Monitor的推送接口，确保前端能正常接收进度
- [ ] 测试WebSocket推送是否正常
- [ ] **产出：** 流式输出 + 实时推送重构完成

### Day 20 — 8月1日（周五）：工具链迁移 & 路径系统

- [ ] 把所有tools迁移到新架构，确保兼容
- [ ] 优化路径处理逻辑，统一使用Path
- [ ] 确保文件上传/下载/生成流程正常
- [ ] **产出：** 工具链迁移完成

### Day 21 — 8月3日（周日）：端到端测试 & Debug

- [ ] 完整测试：用户提问 → 主Agent路由 → 子Agent执行 → 工具调用 → 结果返回
- [ ] 测试多轮对话场景
- [ ] 测试并发请求场景（多个session同时执行）
- [ ] 修复所有bug
- [ ] **产出：** 所有核心流程测试通过

### Day 22 — 8月4日（周一）：Prompt优化 & 场景泛化

- [ ] 把"空调公司"改为通用企业助手场景
- [ ] 优化main_agent的system_prompt，加入更好的任务规划指令
- [ ] 优化子Agent的prompt，提升工具调用准确率
- [ ] **产出：** 新版prompts.yml

### Day 23 — 8月5日（周二）：代码整理 & 重构收尾

- [ ] 删除deepagents依赖，清理requirements.txt
- [ ] 代码格式化，添加类型注解
- [ ] 添加关键模块的docstring
- [ ] 跑一遍完整流程确认无误
- [ ] **产出：** 重构完成，代码干净可读

---

## 第四阶段：添加面试加分项（8天）

**目标：** 让项目从"能用"变成"有亮点"，面试时有东西可讲。

### Day 24 — 8月6日（周三）：添加重试 & Fallback策略

- [ ] 实现工具调用失败后的自动重试（最多3次）
- [ ] 实现子Agent fallback：网络搜索失败时用RAG兜底
- [ ] 在StateGraph中加入error_handler节点
- [ ] **产出：** 容错机制完成

### Day 25 — 8月7日（周四）：添加对话记忆管理

- [ ] 用SqliteSaver替换InMemorySaver，实现持久化记忆
- [ ] 实现对话历史的摘要压缩（避免token爆炸）
- [ ] 实现跨session的上下文保持
- [ ] **产出：** 记忆管理模块完成

### Day 26 — 8月8日（周五）：添加Agent评估系统

- [ ] 设计5-10个测试case（覆盖不同场景）
- [ ] 写评估脚本：自动跑case，统计成功率、延迟、token消耗
- [ ] 输出评估报告
- [ ] **产出：** `eval/` 目录 + 评估脚本 + 测试报告

### Day 27 — 8月10日（周日）：添加MCP协议支持

- [ ] 学习MCP（Model Context Protocol）基本概念
- [ ] 把现有工具用MCP协议暴露为MCP Server
- [ ] 写一个MCP Client demo验证连通性
- [ ] **产出：** MCP Server实现

### Day 28 — 8月11日（周一）：MCP深化 & 工具发现

- [ ] 实现MCP的工具自动发现机制
- [ ] 让Agent能动态加载MCP工具（而非硬编码）
- [ ] 测试通过MCP调用工具的完整链路
- [ ] **产出：** 动态工具加载机制完成

### Day 29 — 8月12日（周二）：添加日志 & 可观测性

- [ ] 用 `structlog` 或 `loguru` 替换print，实现结构化日志
- [ ] 添加LangSmith/LangFuse集成，实现Agent执行追踪
- [ ] 记录每次工具调用的耗时和token消耗
- [ ] **产出：** 可观测性模块完成

### Day 30 — 8月13日（周三）：添加认证 & 安全加固

- [ ] 给API加JWT认证
- [ ] CORS配置从 `*` 改为白名单
- [ ] 文件上传加大小限制和类型校验
- [ ] SQL工具加只读模式和查询超时
- [ ] **产出：** 安全加固完成

### Day 31 — 8月14日（周四）：端到端测试 & 最终调优

- [ ] 全部功能回归测试
- [ ] 性能调优：减少不必要的LLM调用
- [ ] 修复所有遗留bug
- [ ] **产出：** 项目功能完整，准备包装

> **8月15日（周五）直接进入第五阶段**
> **8月16日（周六）：** 休息

---

## 第五阶段：项目包装 & GitHub整理（3天）

**目标：** 让项目在GitHub上"看起来专业"，简历上"写起来有料"。

### Day 32 — 8月15日（周五）：GitHub整理 & README

- [ ] 整理项目结构，确保目录清晰
- [ ] 写一份专业的README：项目介绍、架构图、技术栈、快速开始、演示截图
- [ ] 画架构图（用Mermaid或draw.io）
- [ ] 添加 `.gitignore`，清理无关文件（.idea、__pycache__等）
- [ ] **产出：** GitHub仓库整理完成

### Day 33 — 8月17日（周日）：简历项目描述 & 技术博客

- [ ] 写简历中的项目描述（STAR法则：背景-任务-行动-结果）
- [ ] 写1-2篇技术博客（发掘金/知乎/CSDN）：
  - "用LangGraph构建多Agent系统的实战经验"
  - "从deepagents到原生LangGraph：为什么要自己造轮子"
- [ ] **产出：** 简历项目段 + 技术博客初稿

### Day 34 — 8月18日（周一）：录制Demo & 完善细节

- [ ] 录一段项目演示视频（2-3分钟）
- [ ] 完善README中的演示GIF/截图
- [ ] 检查所有代码注释是否清晰
- [ ] 确认项目能一键跑通（别人clone下来能直接用）
- [ ] **产出：** 项目可展示状态

---

## 第六阶段：面试准备 & 投递（6天+持续）

**目标：** 能自信地讲清楚项目，回答Agent相关技术问题，拿到面试机会。

### Day 35 — 8月19日（周二）：Agent高频面试题准备

- [ ] 准备以下问题的回答：
  - Agent的核心组成是什么？（规划、记忆、工具调用、反思）
  - LangGraph和LangChain的区别？为什么选LangGraph？
  - 你的项目中多Agent是怎么协作的？状态怎么传递？
  - 什么是MCP？为什么需要它？
  - Agent的幻觉问题怎么处理？
  - 如何评估一个Agent系统的效果？
- [ ] **产出：** 面试题答案文档

### Day 36 — 8月20日（周三）：深度技术问题准备

- [ ] 准备以下问题的回答：
  - ContextVar vs threading.local 的区别和使用场景？
  - WebSocket和SSE的区别？你为什么选WebSocket？
  - SQL注入怎么防？你的项目做了什么安全措施？
  - Human-in-the-loop在你项目中怎么实现的？
  - 你项目的Agent评估结果怎么样？哪些case表现不好？为什么？
  - 如果让你重新设计，你会改什么？
- [ ] **产出：** 深度技术问答文档

### Day 37 — 8月21日（周四）：模拟面试 & 项目讲解

- [ ] 对着镜子/录屏，用2分钟讲清楚项目（练3遍以上）
- [ ] 找朋友或用AI模拟技术面试
- [ ] 练习"追问"场景：面试官深挖细节时怎么回答
- [ ] **产出：** 流畅的项目讲解 + 模拟面试录音复盘

### Day 38 — 8月22日（周五）：简历定稿 & 岗位调研

- [ ] 简历定稿，突出Agent项目经验
- [ ] 调研目标公司和岗位：
  - 国内：字节(Coze)、蚂蚁(百灵)、百度(文心)、月之暗面、智谱、MiniMax
  - 海外：Anthropic、LangChain、CrewAI、OpenAI
- [ ] 整理每家公司的Agent产品方向，准备针对性回答
- [ ] **产出：** 定稿简历 + 目标公司清单

### Day 39 — 8月24日（周日）：开始投递

- [ ] 第一批投递（5-10家）
- [ ] 优先投内推渠道（脉脉、LinkedIn、牛客）
- [ ] 准备每家公司的定制化自我介绍
- [ ] **产出：** 第一批投递完成

### Day 40+ — 8月25日起：持续投递 & 面试迭代

- [ ] 每天投2-3家，保持节奏
- [ ] 每次面试后复盘，补充薄弱环节
- [ ] 根据面试反馈迭代项目和回答
- [ ] 保持学习：关注Agent领域最新动态（Twitter/GitHub/arxiv）

---

## 关键资源

| 资源 | 链接 | 用途 |
|------|------|------|
| LangGraph官方文档 | https://langchain-ai.github.io/langgraph/ | 第二、三阶段核心参考 |
| LangGraph教程 | https://langchain-ai.github.io/langgraph/tutorials/ | 跟着做demo |
| MCP协议规范 | https://modelcontextprotocol.io/ | 第四阶段MCP开发 |
| LangSmith | https://smith.langchain.com/ | Agent可观测性 |
| Tavily API | https://tavily.com/ | 网络搜索工具 |
| RAGFlow文档 | https://ragflow.io/ | RAG知识库 |

## 每日学习模板

```
## 日期：____

### 今日目标
- 

### 学习内容 & 笔记
- 

### 代码产出
- 

### 遇到的问题
- 

### 明日计划
- 
```

---

## 里程碑检查点

| 检查点 | 日期 | 验收标准 |
|--------|------|----------|
| ✅ 能画出完整架构图并讲清楚 | 7月18日 | 不看代码，2分钟讲完 |
| ✅ LangGraph独立写多Agent | 7月24日 | demo能跑通 |
| ✅ 重构完成，去掉deepagents | 8月5日 | 所有功能正常 |
| ✅ 加分项全部完成 | 8月14日 | MCP/评估/安全都有 |
| ✅ GitHub项目可展示 | 8月18日 | README专业，能一键跑 |
| ✅ 能流畅回答面试题 | 8月22日 | 模拟面试通过 |
| ✅ 开始投递 | 8月24日 | 第一批5-10家 |

---

> **核心原则：** 每天4小时，2小时学/读，2小时写代码。不要只看不写，也不要只写不理解。面试官要的不是你做了什么，而是你为什么这样做、遇到问题怎么解决的。
