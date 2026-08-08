import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.config import Settings
from app.tools.sql_safety import SQL_TOOLS, check_sql_call

logger = logging.getLogger(__name__)


class SqlGuardMiddleware(AgentMiddleware):

    def __init__(self, settings:Settings):
        super().__init__()
        self._s = settings

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        name = request.tool_call["name"]

        if name not in SQL_TOOLS:
            return await handler(request)

        args = request.tool_call["args"]

        reason = check_sql_call(name, args, self._s)

        if reason is not None:
            logger.warning("[SQL Guard] 拦截 %s: %s | agrs = %s", name, reason, args)
            return ToolMessage(
                content=(
                    f"[安全拦截] {reason}。\n"
                    f"本系统只允许只读查询 (SELECT / SHOW / DESCRIBE / EXPLAIN)。\n"
                    f"请根据上述规则改写后重试"
                ),
                tool_call_id = request.tool_call["id"],
                status="error"
            )
        return await handler(request)
