"""Day 7 SqlGuardMiddleware 单测。

验证四件事：
1. 非法 SQL（DROP）在 handler 执行前被拦截 → 返回 status="error" ToolMessage，handler 不被调用
2. 合法 SQL 放行 → handler 被调用
3. 非 SQL 工具不受影响（放行）
4. 【拦截优先于重试】SqlGuard 装在 ToolRetry 外层 → DROP 只被拦 1 次，重试完全不触发
   （handler 调用次数 = 0，就是"非法 SQL 不会进重试圈"的单元级证据）
"""
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.messages import ToolMessage

from app.config import Settings
from app.middleware.sql_guard import SqlGuardMiddleware


def _make_settings(**overrides):
    defaults = {
        "llm_model": "test", "llm_base_url": "http://localhost", "llm_api_key": "test",
        "mysql_password": "test", "mysql_database": "test", "tavily_api_key": "test",
        "embed_model": "test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class _Req:
    """手工扮演 ToolCallRequest，带 SqlGuard 需要的字段 + ToolRetry 需要的 .tool。

    真实 ToolCallRequest 有三个字段：tool_call(dict) / tool(工具对象) / state。
    ToolRetryMiddleware 会访问 request.tool（拿到工具对象做重试），所以桩必须带。
    """

    def __init__(self, name, args, id="call_1"):
        self.tool_call = {"name": name, "args": args, "id": id}
        self.tool = None          # ToolRetry 会读它；单测不真正重试，置 None 即可
        self.state = {}


async def _ok_handler(request):
    return "executed"


async def test_drop_intercepted_handler_not_called():
    """非法 SQL → 返回 status="error" 的 ToolMessage，handler 一次都不调用。"""
    settings = _make_settings()
    mw = SqlGuardMiddleware(settings)
    req = _Req("execute_sql_query", {"query": "DROP TABLE drugs"})

    result = await mw.awrap_tool_call(req, _ok_handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "安全拦截" in result.content
    assert result.tool_call_id == "call_1"


async def test_valid_select_passes_through():
    """合法 SELECT → 放行，handler 正常执行。"""
    settings = _make_settings()
    mw = SqlGuardMiddleware(settings)
    req = _Req("execute_sql_query", {"query": "SELECT * FROM drugs"})

    result = await mw.awrap_tool_call(req, _ok_handler)

    assert result == "executed"


async def test_non_sql_tool_not_intercepted():
    """非 SQL 工具（如 write_todos）不受影响，直接放行。"""
    settings = _make_settings()
    mw = SqlGuardMiddleware(settings)
    req = _Req("write_todos", {"todos": ["a"]})

    result = await mw.awrap_tool_call(req, _ok_handler)

    assert result == "executed"


async def test_guard_outer_to_retry_drop_not_retried():
    """核心验收：SqlGuard 在 ToolRetry 外层 → DROP 被拦，重试完全不触发。

    组合方式：guard 包住 retry（外层调用内层）。
    证据：内层 handler 调用次数 = 0 —— 重试根本没机会执行它。
    若顺序反了（retry 在外），非法 SQL 会被重试 3 次，handler 会执行 3 次。
    """
    settings = _make_settings()
    guard = SqlGuardMiddleware(settings)
    retry = ToolRetryMiddleware(
        max_retries=3, initial_delay=0.01, backoff_factor=1.0, jitter=False,
    )

    calls = []

    async def real_handler(request):
        calls.append(request)
        return "ok"

    async def inner(request):          # 内层 = 重试中间件包住真正的 handler
        return await retry.awrap_tool_call(request, real_handler)

    req = _Req("execute_sql_query", {"query": "DROP TABLE drugs"})

    result = await guard.awrap_tool_call(req, inner)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert calls == []                  # handler 0 次调用 = 重试 0 次触发


async def test_guard_outer_to_retry_valid_sql_still_executes():
    """顺序对了：合法 SQL 穿过 guard → retry → 真正执行。"""
    settings = _make_settings()
    guard = SqlGuardMiddleware(settings)
    retry = ToolRetryMiddleware(
        max_retries=3, initial_delay=0.01, backoff_factor=1.0, jitter=False,
    )

    calls = []

    async def real_handler(request):
        calls.append(request)
        return "ok"

    async def inner(request):
        return await retry.awrap_tool_call(request, real_handler)

    req = _Req("execute_sql_query", {"query": "SELECT * FROM drugs"})

    result = await guard.awrap_tool_call(req, inner)

    assert result == "ok"
    assert len(calls) == 1
