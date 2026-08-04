import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import StateT
from langchain.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.typing import ContextT

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus


class EventEmitMiddleware(AgentMiddleware):
    def __init__(self, bus: EventBus):
        super().__init__()
        self._bus = bus

    def _tid(self, runtime:Runtime[RunContext]):
        if runtime is None:
            return "unknown"
        ctx = getattr(runtime, "context", None)
        return getattr(ctx, "thread_id", "") or "unknown"

    async def _emit(self, tid:str, **kw):
        await self._bus.publish(tid, AgentEvent(thread_id=tid, **kw))

    async def awrap_tool_call(
        self,
        request,
        handler,
    ) -> ToolMessage | Command[Any]:
        tid = self._tid(request.runtime)
        name = request.tool_call["name"]
        t0 = time.perf_counter()

        await self._emit(tid,  type="tool_start", message=f"调用{name}",
                         data={"tool":name, "args":request.tool_call["args"]})

        try:
            result = await handler(request)
        except Exception as e:
            await self._emit(tid, type="tool_error", message=f"调用{name} 失败：{e}",
                             data={"tool": name, "error": type(e).__name__})
            raise

        await self._emit(tid, type="tool_end", message=f"调用 {name} 结束",
                         data={"tool": name, "elapsed_ms": int((time.perf_counter() - t0) * 1000)})
        return result

    async def aafter_model(self, state: StateT, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        tid = self._tid(runtime)
        if todos := state.get("todos"):
            await self._emit(tid, type="plan_update", message="计划已更新",
                             data={"todos":todos})
        return None
