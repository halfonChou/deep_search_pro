from typing import Any

from langgraph.types import Command

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus

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
    if isinstance(interrupt_value, tuple) and interrupt_value:
        inner = interrupt_value[0]
        value = getattr(inner, "value", None)
        if value is not None:
            return value
        return {"raw": interrupt_value}
    if isinstance(interrupt_value, list):
        return {"action_requests": interrupt_value}
    return {"raw":interrupt_value}


async def run_agent_stream(agent, query:str, ctx:RunContext, bus:EventBus, resume: dict | None = None):
    config = {"configurable":{"thread_id":ctx.thread_id}}

    if resume is not None:
        input_ = Command(resume=resume)
    else:
        input_ = {"messages":[{"role":"user", "content":query}]}
    async for chunk in agent.astream(
        input_,
        config=config,
        context=ctx,
        stream_mode=["updates","messages"],
        version="v2",
    ):
        if chunk["type"]=="messages":
            token,_meat = chunk["data"]
            if token.content:
                await bus.publish(
                    ctx.thread_id,
                    AgentEvent(type="token", thread_id=ctx.thread_id,
                               message=token.content)
                )
        elif chunk["type"]=="updates" and "__interrupt__" in chunk["data"]:
            await bus.publish(
                ctx.thread_id,
                AgentEvent(type="interrupt", thread_id=ctx.thread_id,
                           message="等待人工审批"),
                            data=_serialize_interrupt(chunk["data"]["__interrupt__"]),
            )
