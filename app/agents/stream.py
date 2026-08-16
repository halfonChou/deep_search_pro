"""Agent 流式执行 + 事件发布。

前端要「实时看到任务被推上去」，靠的就是这里往 EventBus 发的事件：
- token        : 模型逐字输出
- plan_update  : todos 待办清单发生变化（write_todos 工具写状态时触发）
- subagent_call: 主 Agent 把活派给了某个子 Agent
- interrupt    : 命中 HITL，等待人工审批
- task_result  : 本轮跑完，附最终回答
"""

import json
import logging
import time
from typing import Any

from langgraph.types import Command

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus

logger = logging.getLogger(__name__)

# __interrupt__ = (
#     Interrupt(
#         value={
#             'action_requests': [
#                 {'name': 'execute_sql_query',
#                  'args': {'query': 'SELECT * FROM sales_record'},
#                  'description': "Tool execution requires approval..."}
#             ],
#             'review_configs': [
#                 {'action_name': 'execute_sql_query',
#                  'allowed_decisions': ['approve', 'edit', 'reject']}
#             ]
#         },
#         id='44e6a515aee60a83ca8275a1b75e3323'
#     ),
# )

def _serialize_interrupt(interrupt_value: Any):
    """把 __interrupt__ 摊平成前端能用的结构。

    ★★ 为什么必须带上 id（这里踩过坑）：
    主 Agent 一轮里可能派出**多个**子 Agent，每个都停在自己的审批点上，
    于是同时挂起多个 interrupt。这种情况下 LangGraph 不接受笼统的
    `Command(resume=<单个值>)`，会直接报：
        "When there are multiple pending interrupts, you must specify
         the interrupt id when resuming."
    必须传 `Command(resume={中断id: 决策, ...})` 逐个对应。
    所以事件里一定要把每个中断的 id 带给前端，前端提交决策时再原样传回来。

    原来的实现只取 interrupt_value[0]，**多中断时后面几条直接被丢掉**，
    前端只看得到一张审批卡片，恢复时必然失败。

    返回结构：
        {
          "interrupts": [{"id": ..., "action_requests": [...], "review_configs": [...]}, ...],
          "action_requests": [...],   # 第一条摊平在顶层，兼容旧前端
          "review_configs": [...],
        }
    """
    items = interrupt_value if isinstance(interrupt_value, (tuple, list)) else [interrupt_value]

    parsed: list[dict] = []
    for item in items:
        value = getattr(item, "value", None)
        iid = getattr(item, "id", None)
        if value is None:
            # 兜底：不认识的形状，原样兜住，绝不抛异常
            value = item if isinstance(item, dict) else {"raw": repr(item)}
        entry = dict(value) if isinstance(value, dict) else {"action_requests": [value]}
        entry["id"] = iid
        parsed.append(entry)

    if not parsed:
        return {"interrupts": [], "action_requests": []}

    head = parsed[0]
    return {
        "interrupts": parsed,
        "action_requests": head.get("action_requests", []),
        "review_configs": head.get("review_configs", []),
    }


def _unpack(chunk: Any) -> tuple[str, Any]:
    """兼容两种 chunk 形态：{'type':..,'data':..} 和 LangGraph 原生的 (mode, payload)。"""
    if isinstance(chunk, dict) and "type" in chunk and "data" in chunk:
        return chunk["type"], chunk["data"]
    if isinstance(chunk, tuple) and len(chunk) == 2:
        return chunk[0], chunk[1]
    return "unknown", chunk


def _normalize_todos(raw: Any) -> list[dict] | None:
    """把 deepagents 的 todos 状态统一成 [{content, status}, ...]。"""
    if not isinstance(raw, list):
        return None
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            content = item.get("content") or item.get("task") or item.get("title") or ""
            status = item.get("status", "pending")
        else:
            content = getattr(item, "content", None) or str(item)
            status = getattr(item, "status", "pending")
        out.append({"content": str(content), "status": str(status)})
    return out


def _text_of(content: Any) -> str:
    """LLM chunk 的 content 可能是 str，也可能是 [{'type':'text','text':..}, ...]。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


async def run_agent_stream(agent, query: str, ctx: RunContext, bus: EventBus, resume: dict | None = None):
    config = {"configurable": {"thread_id": ctx.thread_id}}

    if resume is not None:
        input_ = Command(resume=resume)
    else:
        input_ = {"messages": [{"role": "user", "content": query}]}

    last_todos_sig: str | None = None
    final_text: list[str] = []
    interrupted = False
    last_step_ts = time.perf_counter()

    async for chunk in agent.astream(
        input_,
        config=config,
        context=ctx,
        stream_mode=["updates", "messages"],
        version="v2",
    ):
        mode, data = _unpack(chunk)

        if mode == "messages":
            token, _meta = data
            text = _text_of(getattr(token, "content", ""))
            if text:
                final_text.append(text)
                await bus.publish(
                    ctx.thread_id,
                    AgentEvent(type="token", thread_id=ctx.thread_id, message=text),
                )

        elif mode == "updates" and isinstance(data, dict):
            # 诊断用：把每个 updates chunk 的 key 打出来。
            # 排查「审批卡片没弹出来」时，就靠这行确认 __interrupt__ 到底有没有冒到父图。
            logger.debug("[updates] keys=%s", list(data))

            if "__interrupt__" in data:
                interrupted = True
                logger.info("[interrupt] 收到中断，等待人工审批")
                await bus.publish(
                    ctx.thread_id,
                    AgentEvent(
                        type="interrupt", thread_id=ctx.thread_id,
                        message="等待人工审批",
                        data=_serialize_interrupt(data["__interrupt__"]),
                    ),
                )
                continue

            # 扫每个节点的状态增量，看 todos 有没有变
            for node_name, update in data.items():
                # 心跳日志：卡住时能在终端看出停在哪个节点、上一步隔了多久。
                # 中间件钩子（XxxMiddleware.before_model 之类）耗时恒为 0，纯噪音，滤掉。
                if "Middleware" not in node_name:
                    now = time.perf_counter()
                    logger.info("[step] 节点=%s | 距上一步 %.1fs", node_name, now - last_step_ts)
                    last_step_ts = now

                if not isinstance(update, dict):
                    continue

                todos = _normalize_todos(update.get("todos"))
                if todos is not None:
                    sig = json.dumps(todos, ensure_ascii=False, sort_keys=True)
                    if sig != last_todos_sig:
                        last_todos_sig = sig
                        done = sum(1 for t in todos if t["status"] == "completed")
                        await bus.publish(
                            ctx.thread_id,
                            AgentEvent(
                                type="plan_update", thread_id=ctx.thread_id,
                                message=f"计划更新：{done}/{len(todos)} 已完成",
                                data={"todos": todos, "node": node_name},
                            ),
                        )

                # 子 Agent 委托：节点名里带 task / subagent 的当作一次委托
                if node_name and ("task" in node_name or "subagent" in node_name):
                    await bus.publish(
                        ctx.thread_id,
                        AgentEvent(
                            type="subagent_call", thread_id=ctx.thread_id,
                            message=f"节点 {node_name} 产出更新",
                            data={"node": node_name},
                        ),
                    )

    if interrupted:
        # 停在审批点上，这一轮还没结束，不发收尾事件
        return

    logger.info("[stream] 本轮结束，未命中中断")
    await bus.publish(
        ctx.thread_id,
        AgentEvent(
            type="task_result", thread_id=ctx.thread_id,
            message="任务结束",
            data={"final": await _final_answer(agent, config, final_text)},
        ),
    )


async def _final_answer(agent, config, streamed: list[str]) -> str:
    """取最终回答：从 checkpoint 里收集本轮所有 AI 消息的正文。

    ★★ 这里踩过一个坑，别改回去：
    最初的写法是「倒着找第一条**没有 tool_calls** 的 AI 消息」，结果只拿到
    「我已完成了查询，如还有问题请随时告诉我」这种收尾客套话，正文全丢了。

    原因是一条 AI 消息**可以同时带正文和 tool_calls**。模型经常这样安排：
        turn N   : 写出完整答案正文 + 顺手调一次 write_todos   ← 被旧逻辑跳过
        turn N+1 : 只说一句"已完成"                            ← 被旧逻辑选中
    跳过带 tool_calls 的消息，等于把最有价值的那一条扔了。

    现在改成：从末尾往回走，遇到 HumanMessage 就停（那是本轮的起点），
    把中间所有 AI 消息的正文按原顺序拼起来。ToolMessage 自动跳过。

    只会拿到主 Agent 自己的消息——子 Agent 的 messages 不会合并回主状态
    （deepagents 的 _EXCLUDED_STATE_KEYS 里排除了 messages），所以不会串味。
    """
    try:
        snapshot = await agent.aget_state(config)
        messages = (getattr(snapshot, "values", None) or {}).get("messages") or []

        parts: list[str] = []
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "human":
                break                      # 走到本轮用户提问，停
            if getattr(msg, "type", None) != "ai":
                continue                   # ToolMessage / SystemMessage 跳过
            text = _text_of(getattr(msg, "content", "")).strip()
            if text:
                parts.append(text)

        if parts:
            return "\n\n".join(reversed(parts))   # 反转回时间正序
    except Exception:
        logger.exception("读取最终回答失败，退回流式拼接")

    return "".join(streamed)[-8000:]
