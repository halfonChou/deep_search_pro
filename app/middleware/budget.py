from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, NotRequired

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    hook_config,
)
from langchain.agents.middleware.types import ResponseT
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.typing import ContextT

from app.config import Settings

logger = logging.getLogger(__name__)

class BudgetState(AgentState):
    tokens_used: NotRequired[int]
    cost_usd: NotRequired[float]

def _extract_usage(response: Any) -> tuple[int, int] | None:
    usage = getattr(response, "usage_metadata", None)

    if not usage:
        for msg in reversed(getattr(response, "result", None) or []):
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                break
    if not usage and isinstance(response, dict):
        usage = response.get("usage_metadata")

    if not usage:
        return None
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


class BudgetMiddleware(AgentMiddleware[BudgetState]):
    state_schema = BudgetState

    def __init__(self, settings: Settings):
        super().__init__()
        self._s = settings

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: BudgetState, runtime: Runtime[Any]) -> dict[str, Any] | None:
        used = state.get("tokens_used", 0)
        cost = state.get("cost_usd", 0)

        over_tokens = used >= self._s.budget_max_tokens
        over_cost = cost >= self._s.budget_max_cost_usd

        if not (over_tokens or over_cost):
            return None

        hit = "token 用量" if over_tokens else "成本"
        logger.warning(
            f"[Budget] 熔断：{hit} 超限 | "
            f"tokens={used}/{self._s.budget_max_tokens} "
            f"cost=${cost:.4f}/${self._s.budget_max_cost_usd:.2f}"
        )

        return {
            "messages": [
                AIMessage(
                    f"⚠️ 本次任务已达预算上限"
                    f"（已用 {used:,} tokens / ${cost:.3f}，"
                    f"上限 {self._s.budget_max_tokens:,} tokens / "
                    f"${self._s.budget_max_cost_usd:.2f}）。\n"
                    f"以下是基于已收集信息的结论，未覆盖的部分我会明确标注为信息缺口。"
                )
            ],
            "jump_to": "end",
        }

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT] | AIMessage | ExtendedModelResponse[ResponseT]:
        response = await handler(request)

        usage = _extract_usage(response)
        if usage is None:
            logger.warning(
                "[Budget] 未取到 usage_metadata，本次调用未计入预算。"
                "流式调用请确认模型已开启 stream_usage=True"
                "（OpenAI 协议下 stream=True 默认不返回 usage），否则预算形同虚设。"
            )
            return response

        ti, to = usage
        delta_cost = (
            ti * self._s.price_per_1m_input + to * self._s.price_per_1m_output
        ) / 1_000_000

        new_tokens = request.state.get("tokens_used", 0) + ti + to
        new_cost = request.state.get("cost_usd", 0) + delta_cost

        logger.debug(
            "[Budget] +%s tokens (in=%s out=%s) +$%.5f → 累计 %s tokens / $%.4f",
            ti + to, ti, to, delta_cost, new_tokens, new_cost,
        )

        return ExtendedModelResponse(
            model_response=response,
            command=Command(update={"tokens_used": new_tokens, "cost_usd": new_cost}),
        )
