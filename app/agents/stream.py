from typing import Any

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus


def _serialize_interrupt(interrupt_value: Any):
    if isinstance(interrupt_value, list):
        return{
            "action_requests":[
                getattr(item, "action_requests", None) or item
                for item in interrupt_value
            ]
        }
    return {"raw":interrupt_value}


async def run_agent_stream(agent, query:str, ctx:RunContext, bus:EventBus):
    config = {"configurable":{"thread_id":ctx.thread_id}}

    async for chunk in agent.astream(
        {"messages":[{"role":"user", "content":query}]},
        config=config,
        context=ctx,
        stream_mode=["updates","messages"],
        version="v2",
    ):
        if chunk["type"]=="message":
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
                AgentEvent(type="interrupt", thread_id=ctx.thread_id,message="等待人工审批"),
                            data=_serialize_interrupt(chunk["data"]["__interrupt"]),
            )
