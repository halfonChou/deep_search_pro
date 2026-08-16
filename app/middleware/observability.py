"""事件观测中间件。

两个中间件，位置不同、职责不同：

- EventEmitMiddleware：装在**最外层**，量到的是「含重试在内」的真实耗时，
  负责推 tool_start / tool_end / tool_error / plan_update。
- ToolRetryNotifyMiddleware：装在 ToolRetryMiddleware 的**内层**，
  每一次失败的尝试都会经过它，所以它才看得见「第几次重试」。
  外层那个只在重试耗尽后才收到异常。

★★ 关于 GraphBubbleUp（两个中间件都必须放行）：
LangGraph 用异常来传递「控制流信号」，而不只是传递错误：
    GraphInterrupt → GraphBubbleUp → Exception
`interrupt()`（HITL 审批）和 `Command(goto=...)` 都是这么冒上去的。
它们**不是失败**，是「这一步先暂停/跳转」的信号，必须原样往上传。

写成 `except Exception` 会把它们一起抓住。即使之后 `raise` 了不影响功能，
也会误报一条 tool_error / 重试事件——前端看到的就是「派发子 Agent 失败」，
而实际上任务只是在等人审批。
LangChain 内置的 ToolRetryMiddleware 就专门先 `except GraphBubbleUp: raise`，
我们这两个自研中间件也必须照做。
"""

import json
import logging
import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import StateT
from langchain.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.typing import ContextT

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus

logger = logging.getLogger(__name__)


def _normalize_todos(raw: Any) -> list[dict]:
    """把 todos 统一成 [{content, status}]，前端只认这个形状。"""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            content = item.get("content") or item.get("task") or item.get("title") or ""
            status = item.get("status", "pending")
        else:
            content = getattr(item, "content", None) or str(item)
            status = getattr(item, "status", "pending")
        content = str(content).strip()
        if content:
            out.append({"content": content, "status": str(status)})
    return out


class EventEmitMiddleware(AgentMiddleware):
    def __init__(self, bus: EventBus):
        super().__init__()
        self._bus = bus
        # 计划去重：aafter_model 每轮都会触发，todos 没变就别刷屏
        self._last_plan_sig: dict[str, str] = {}

    def _tid(self, runtime: Runtime[RunContext]):
        if runtime is None:
            return "unknown"
        ctx = getattr(runtime, "context", None)
        return getattr(ctx, "thread_id", "") or "unknown"

    async def _emit(self, tid: str, **kw):
        await self._bus.publish(tid, AgentEvent(thread_id=tid, **kw))

    async def awrap_tool_call(
        self,
        request,
        handler,
    ) -> ToolMessage | Command[Any]:
        tid = self._tid(request.runtime)
        name = request.tool_call["name"]
        t0 = time.perf_counter()

        await self._emit(tid, type="tool_start", message=f"调用 {name}",
                         data={"tool": name, "args": request.tool_call["args"]})

        try:
            result = await handler(request)
        except GraphBubbleUp:
            # ★ 中断 / 父级命令：不是失败，是「暂停等审批」。
            #   原样放行，不发 tool_error，也不发 tool_end（这次调用还没真正结束）。
            raise
        except Exception as e:
            await self._emit(tid, type="tool_error", message=f"{name} 失败：{e}",
                             data={"tool": name, "error": type(e).__name__, "final": True})
            raise

        await self._emit(tid, type="tool_end", message=f"{name} 完成",
                         data={"tool": name, "elapsed_ms": int((time.perf_counter() - t0) * 1000)})
        return result

    async def aafter_model(self, state: StateT, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        tid = self._tid(runtime)
        todos = _normalize_todos(state.get("todos"))
        if not todos:
            return None

        sig = json.dumps(todos, ensure_ascii=False, sort_keys=True)
        if self._last_plan_sig.get(tid) == sig:
            return None
        self._last_plan_sig[tid] = sig

        done = sum(1 for t in todos if t["status"] == "completed")
        await self._emit(tid, type="plan_update",
                         message=f"计划更新 {done}/{len(todos)}",
                         data={"todos": todos})
        return None


class CacheStatsMiddleware(AgentMiddleware):
    """每次模型调用后打印 prompt 缓存命中情况。

    百炼的隐式缓存是自动开启的，不需要传任何参数——但默认你看不到有没有命中。
    命中数在 usage.prompt_tokens_details.cached_tokens，LangChain 把它映射到
    usage_metadata["input_token_details"]["cache_read"]。

    前提：build_chat_model 里必须有 stream_usage=True，
    否则流式调用下 usage 整个是空的，这里永远打印 0。
    """

    def __init__(self):
        super().__init__()
        self._total_in = 0
        self._total_cached = 0

    async def aafter_model(self, state: StateT, runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None

        usage = getattr(messages[-1], "usage_metadata", None)
        if not usage:
            return None

        input_tokens = int(usage.get("input_tokens", 0) or 0)
        details = usage.get("input_token_details") or {}
        cached = int(details.get("cache_read", 0) or 0)

        self._total_in += input_tokens
        self._total_cached += cached

        rate = cached / input_tokens * 100 if input_tokens else 0.0
        total_rate = self._total_cached / self._total_in * 100 if self._total_in else 0.0

        logger.info(
            "[cache] 本次输入 %d token，命中缓存 %d（%.0f%%）| 累计命中率 %.0f%%",
            input_tokens, cached, rate, total_rate,
        )
        return None


class ToolRetryNotifyMiddleware(AgentMiddleware):
    """装在重试中间件内层，把每一次失败的尝试推给前端。

    没有它，前端只能看到「重试 3 次全挂了」的最终异常，
    看不到中间「正在第 2 次重试」的过程。
    """

    def __init__(self, bus: EventBus):
        super().__init__()
        self._bus = bus
        self._attempts: dict[tuple[str, str], int] = {}

    def _tid(self, runtime: Runtime[RunContext]):
        ctx = getattr(runtime, "context", None) if runtime is not None else None
        return getattr(ctx, "thread_id", "") or "unknown"

    async def awrap_tool_call(self, request, handler) -> ToolMessage | Command[Any]:
        tid = self._tid(request.runtime)
        name = request.tool_call["name"]
        key = (tid, request.tool_call.get("id") or name)

        try:
            result = await handler(request)
        except GraphBubbleUp:
            # ★ 同上：中断不是失败，不该被计成「第 N 次重试」。
            #   注意这里也不 pop _attempts —— 审批完恢复时这次调用会重跑，
            #   届时才知道它到底成没成。
            raise
        except Exception as e:
            n = self._attempts.get(key, 0) + 1
            self._attempts[key] = n
            await self._bus.publish(
                tid,
                AgentEvent(
                    type="tool_error", thread_id=tid,
                    message=f"{name} 第 {n} 次尝试失败，准备重试：{type(e).__name__}",
                    data={"tool": name, "attempt": n, "error": type(e).__name__, "final": False},
                ),
            )
            raise

        self._attempts.pop(key, None)
        return result
