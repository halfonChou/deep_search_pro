# 上下文管理：三层策略

## 概述

DeepSearch Pro 的单次任务可能触发 15+ 轮对话，每轮包含搜索原文（50KB+）、SQL 结果集、RAG 片段等大量数据。如果全部留在上下文里，很快就会触及模型的 context window 上限。

我们用三层策略逐级压制上下文膨胀，每一层解决不同粒度的问题。

## 三层策略

### 第一层：卸载（Offload）

**手段**：工具主动调用 `offload_if_large()`，把超过 4KB 的结果写入虚拟文件系统 `/scratch/`（L0 草稿层），只回 200 字摘要 + 文件路径。

**触发条件**：单条工具结果 > `offload_threshold_bytes`（默认 4096 字节）。

**代价**：模型需要额外一次 `read_file` 才能看到细节。

**为什么需要**：这是最省钱的一层。一次带 `include_raw_content` 的搜索可能返回 50KB 原文，根本不该进上下文。需要时再读，绝大多数时候摘要就够用。

### 第二层：摘要（Summarization）

**手段**：`SummarizationMiddleware`，由 LLM 把长历史压缩成摘要。

**触发条件**：总 token > `summarize_trigger_tokens`（默认 60,000）。

**代价**：一次额外 LLM 调用；有信息损失风险。

**为什么需要**：保留语义连贯性。多轮对话必须有摘要，否则第 10 轮时前 5 轮的上下文就丢了。

### 第三层：裁剪（Context Editing）

**手段**：`ContextEditingMiddleware` + `ClearToolUsesEdit`，机械地把旧的工具输出替换为 `[cleared]`。

**触发条件**：总 token > `context_edit_trigger_tokens`（默认 80,000）。

**代价**：旧工具结果不可恢复。

**为什么需要**：当摘要之后还超，需要一个零 LLM 成本的机械兜底。

## 关键取舍：为什么摘要阈值（60K）低于裁剪阈值（80K）？

先摘要、后裁剪。摘要是有损但保语义的，裁剪是机械丢弃。给摘要先动手的机会，只有摘要之后还超才动裁剪。

如果反过来配（裁剪 60K，摘要 80K），工具结果被 `[cleared]` 之后再摘要，摘要器看到一堆 `[cleared]` 什么也总结不出来。

## 特殊保护

`exclude_tools=["write_todos"]`：write_todos 产出的计划绝不能被裁剪，否则 agent 忘记自己在干什么，后续步骤全乱。

## 落盘层级区分

- `/scratch/`（L0）：虚拟文件系统，落在 `checkpoints.sqlite` 里。搜索原文、SQL 结果集等中间资料走这里。用户看不到。
- `data/sessions/<thread_id>/`（L2）：真实磁盘。最终报告走这里，用户能通过 HTTP 下载。
- **绝不能搞混**：把搜索原文落到 L2，用户下载目录就被垃圾塞满了。

## 验证要点

1. 长对话跑到第 15 轮不报 context length exceeded。
2. 日志能看到三层依次触发：先出现落盘（write_file）→ 再出现摘要 → 最后出现裁剪。
3. 裁剪后 write_todos 的结果仍在上下文里。
4. 单条 50KB 搜索结果只有 200 字进入消息历史。
5. `data/sessions/<tid>/` 里只有报告，没有搜索原文垃圾。
