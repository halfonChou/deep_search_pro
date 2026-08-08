"""Day 8 弹性 + 预算中间件单测。

覆盖四块：
1. ToolRetry 本身：偶发错误重试成功、非白名单错误不重试（retry_on 排除 ValueError）
2. EventEmit 包 ToolRetry 时看到的事件形状（验证"最外层只看到最终结果"这个结论）
3. BudgetMiddleware：熔断判断（before_model）+ 记账（awrap_model_call）+ 取不到用量的 fail-loud
4. stack.py 顺序回归：build_middleware_stack 产出的顺序和有无 fallback 的条件装配
"""
import logging
import time

import pytest
from langchain.agents.middleware import (
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.messages import AIMessage, ToolMessage

from app.agents.deps import AgentDeps
from app.config import Settings
from app.infra.event_bus import EventBus
from app.middleware.budget import BudgetMiddleware
from app.middleware.observability import EventEmitMiddleware
from app.middleware.sql_guard import SqlGuardMiddleware
from app.middleware.stack import build_middleware_stack


def _make_settings(**overrides):
    """复用 test_sql_guard.py 的写法：Settings 必填项给假值，其余走默认/覆盖。"""
    defaults = {
        "llm_model": "test", "llm_base_url": "http://localhost", "llm_api_key": "test",
        "mysql_password": "test", "mysql_database": "test", "tavily_api_key": "test",
        "embed_model": "test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class _ToolReq:
    """手搓 ToolCallRequest，字段跟 test_sql_guard.py 里的 _Req 一致。"""

    def __init__(self, name="internet_search", args=None, id="call_1", state=None):
        self.tool_call = {"name": name, "args": args or {}, "id": id}
        self.tool = None
        self.state = state or {}
        self.runtime = None

class _ModelReq:
    """手搓 ModelRequest，BudgetMiddleware 只用得到 .state。"""

    def __init__(self, state):
        self.state = state


class _FakeMessage:
    """手搓 AIMessage，只需要 usage_metadata 这一个属性。"""

    def __init__(self, usage_metadata=None):
        self.usage_metadata = usage_metadata


class _FakeModelResponse:
    """手搓 ModelResponse，形状对应今天探测出来的真实结构：result 是消息列表。"""

    def __init__(self, result):
        self.result = result


# ===== 1. ToolRetryMiddleware 本身：感冒重试成功 / 骨折不重试 =====

async def test_tool_retry_succeeds_after_transient_failures():
    """前两次 ConnectionError（感冒），第三次成功 —— 重试 3 次，耗时落在退避区间内。

    initial_delay=1.0, backoff_factor=2.0, jitter=True：
    等待 1：0.75~1.25s；等待 2：1.5~2.5s；总退避区间 [2.25, 3.75]（验收标准原文数字）。
    """
    retry = ToolRetryMiddleware(
        max_retries=3, initial_delay=1.0, backoff_factor=2.0, jitter=True,
        retry_on=(ConnectionError, TimeoutError), on_failure="continue",
    )
    calls = []

    async def flaky_handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise ConnectionError("网络抖了一下")
        return ToolMessage(content="ok", tool_call_id="call_1")

    t0 = time.perf_counter()
    result = await retry.awrap_tool_call(_ToolReq(), flaky_handler)
    elapsed = time.perf_counter() - t0

    assert len(calls) == 3                       # 重试了 2 次，第 3 次成功
    assert result.content == "ok"
    assert 2.25 <= elapsed <= 3.75                # 验收标准里的原始区间


async def test_tool_retry_does_not_retry_value_error():
    """ValueError（骨折）不在 retry_on 白名单里 —— 只调 1 次，异常原样抛出。"""
    retry = ToolRetryMiddleware(
        max_retries=3, initial_delay=0.01, backoff_factor=1.0, jitter=False,
        retry_on=(ConnectionError, TimeoutError), on_failure="continue",
    )
    calls = []

    async def bad_input_handler(request):
        calls.append(request)
        raise ValueError("参数本身就不合法")

    with pytest.raises(ValueError):
        await retry.awrap_tool_call(_ToolReq(), bad_input_handler)

    assert len(calls) == 1                        # 没有被重试，白等的 3 次没有发生


# ===== 2. EventEmit 包 ToolRetry：验证"外层只看到最终结果"这个推论 =====

async def test_event_emit_sees_single_start_end_around_successful_retry():
    """EventEmit 在 Retry 外层 → 中间的失败重试对它不可见，
    只会看到 1 次 tool_start + 1 次 tool_end（不是每次重试都单独报事件）。

    这是我们今天推导出来的结论：重试发生在 Retry 内部的循环里，
    EventEmit 调用的 handler 就是"Retry 包好的那一整块"，只在最外层拿到最终结果。
    """
    bus = EventBus()
    emit = EventEmitMiddleware(bus)
    retry = ToolRetryMiddleware(
        max_retries=3, initial_delay=0.01, backoff_factor=1.0, jitter=False,
        retry_on=(ConnectionError, TimeoutError), on_failure="continue",
    )
    calls = []

    async def flaky_handler(request):
        calls.append(request)
        if len(calls) < 2:
            raise ConnectionError("抖一下")
        return ToolMessage(content="ok", tool_call_id="call_1")

    async def inner(request):                     # emit 调用的 handler = retry 包好的整体
        return await retry.awrap_tool_call(request, flaky_handler)

    await emit.awrap_tool_call(_ToolReq(), inner)

    events = bus._history.get("unknown", [])       # request.runtime=None → _tid 兜底成 "unknown"
    types = [e.type for e in events]
    assert types == ["tool_start", "tool_end"]     # 只有 1 组，不是 "tool_error, tool_error, tool_end"
    assert len(calls) == 2                          # 内部确实重试了 1 次，只是外层看不见这个过程


# ===== 3. BudgetMiddleware：熔断判断 =====

async def test_budget_before_model_blocks_when_tokens_over_limit():
    settings = _make_settings(budget_max_tokens=100, budget_max_cost_usd=100.0)
    mw = BudgetMiddleware(settings)

    result = mw.before_model({"tokens_used": 150, "cost_usd": 0.0}, runtime=None)

    assert result is not None
    assert result["jump_to"] == "end"
    assert "预算上限" in result["messages"][0].content


async def test_budget_before_model_blocks_when_cost_over_limit():
    settings = _make_settings(budget_max_tokens=1_000_000, budget_max_cost_usd=0.01)
    mw = BudgetMiddleware(settings)

    result = mw.before_model({"tokens_used": 0, "cost_usd": 0.5}, runtime=None)

    assert result is not None
    assert result["jump_to"] == "end"


async def test_budget_before_model_allows_when_under_limit():
    """没超预算 → 返回 None，图不做任何合并，正常往下走（第一轮 state 里还没有这两个 key 也不报错）。"""
    settings = _make_settings(budget_max_tokens=100, budget_max_cost_usd=1.0)
    mw = BudgetMiddleware(settings)

    result = mw.before_model({}, runtime=None)     # 第一轮：tokens_used/cost_usd 都不存在

    assert result is None


# ===== 4. BudgetMiddleware：记账（wrap_model_call） =====

async def test_budget_wrap_model_call_accumulates_usage():
    settings = _make_settings(price_per_1m_input=0.5, price_per_1m_output=2.0)
    mw = BudgetMiddleware(settings)

    response = _FakeModelResponse(result=[
        _FakeMessage(usage_metadata={"input_tokens": 1000, "output_tokens": 500}),
    ])

    async def handler(request):
        return response

    result = await mw.awrap_model_call(_ModelReq(state={"tokens_used": 200, "cost_usd": 0.01}), handler)

    update = result.command.update
    assert update["tokens_used"] == 200 + 1500                        # 累加，不是覆盖
    assert round(update["cost_usd"], 6) == round(0.01 + 0.0015, 6)     # (1000*0.5+500*2)/1e6
    assert result.model_response is response                           # 响应本身原样传下去


async def test_budget_wrap_model_call_missing_usage_fails_loud(caplog):
    """取不到 usage_metadata → 不伪造成 0，打 warning，原样放行响应（不包信封）。"""
    settings = _make_settings()
    mw = BudgetMiddleware(settings)

    response = _FakeModelResponse(result=[_FakeMessage(usage_metadata=None)])

    async def handler(request):
        return response

    with caplog.at_level(logging.WARNING):
        result = await mw.awrap_model_call(_ModelReq(state={}), handler)

    assert result is response                       # 没有信封，说明没有累加动作发生
    assert "未取到 usage_metadata" in caplog.text    # fail-loud：必须留下痕迹，不能悄悄按 0 处理


# ===== 5. stack.py：顺序与条件装配回归 =====

def _build_deps(**settings_overrides):
    settings = _make_settings(**settings_overrides)
    return AgentDeps(settings=settings, bus=EventBus())


def test_stack_order_matches_design():
    """9(或10)层顺序必须和 §1.3 一致，改错顺序这个测试第一个报警。"""
    stack = build_middleware_stack(_build_deps())
    types = [type(m) for m in stack]

    assert types[0] is EventEmitMiddleware                 # ①最外层
    assert types[1] is BudgetMiddleware                    # ②预算在所有限流/重试之前
    assert types[2] is ModelCallLimitMiddleware             # ③
    assert types[3] is ToolCallLimitMiddleware              # ④全局工具闸
    assert types[4] is ToolCallLimitMiddleware              # ⑤单独卡搜索
    assert types[5] is SqlGuardMiddleware                   # ⑥必须在 ToolRetry 之前
    assert types[6] is ToolRetryMiddleware                  # ⑦
    assert types[7] is ModelRetryMiddleware                 # ⑧
    assert types[-1] is ContextEditingMiddleware            # 最内层，紧贴模型


def test_stack_skips_fallback_when_not_configured():
    """fallback_models 为空（默认）→ 栈里不出现 ModelFallbackMiddleware。"""
    stack = build_middleware_stack(_build_deps(fallback_models=[]))
    assert not any(isinstance(m, ModelFallbackMiddleware) for m in stack)


def test_stack_includes_fallback_when_configured():
    """配了 fallback_models → 栈里恰好出现 1 个 ModelFallbackMiddleware，夹在 ModelRetry 和 ContextEditing 之间。"""
    stack = build_middleware_stack(_build_deps(fallback_models=["test-fallback-model"]))
    fallback_indices = [i for i, m in enumerate(stack) if isinstance(m, ModelFallbackMiddleware)]

    assert len(fallback_indices) == 1
    idx = fallback_indices[0]
    assert isinstance(stack[idx - 1], ModelRetryMiddleware)
    assert isinstance(stack[idx + 1], ContextEditingMiddleware)


# ===== 6.（需要你本地先探测确认字段名）search_tool_run_limit 熔断后继续 =====

def _ai_with_tool_calls(tool_calls):
    """手搓一条带 tool_calls 的 AIMessage，模拟"模型刚决定要调这些工具"。"""
    msg = AIMessage(content="")
    msg.tool_calls = tool_calls
    return msg


def test_search_tool_limit_blocks_third_call_but_continues():
    """run_limit=2：第 3 次请求被挡（伪造 ToolMessage），不抛异常，也不 jump_to（continue 是默认行为）。"""
    limiter = ToolCallLimitMiddleware(tool_name="internet_search", run_limit=2)
    state = {"run_tool_call_count": {}, "thread_tool_call_count": {}}

    for i in range(1, 3):                          # 前 2 次：应该被放行，只更新计数
        state["messages"] = [_ai_with_tool_calls([
            {"id": f"call_{i}", "name": "internet_search", "args": {}},
        ])]
        result = limiter.after_model(state, runtime=None)
        assert "messages" not in (result or {})     # 放行 = 没有伪造错误消息
        state.update(result or {})

    assert state["run_tool_call_count"]["internet_search"] == 2

    state["messages"] = [_ai_with_tool_calls([                       # 第 3 次：该被挡
        {"id": "call_3", "name": "internet_search", "args": {}},
    ])]
    result = limiter.after_model(state, runtime=None)

    assert "jump_to" not in result                  # exit_behavior 默认 continue，不结束
    blocked_msg = result["messages"][0]
    assert isinstance(blocked_msg, ToolMessage)
    assert blocked_msg.status == "error"
    assert blocked_msg.tool_call_id == "call_3"      # 精确挡住第 3 个，不是随便哪个


def test_general_and_specific_tool_limiters_do_not_clobber_each_other():
    """回应今天上午的疑虑：通用限流器（__all__）和搜索限流器（internet_search）
    共用 run_tool_call_count 这同一个字段，但各占一格，不会互相冲掉对方的计数。
    """
    general = ToolCallLimitMiddleware(run_limit=40)                  # count_key = "__all__"
    search = ToolCallLimitMiddleware(tool_name="internet_search", run_limit=5)  # count_key = "internet_search"

    state = {"run_tool_call_count": {}, "thread_tool_call_count": {}}
    state["messages"] = [_ai_with_tool_calls([
        {"id": "c1", "name": "internet_search", "args": {}},
    ])]

    state.update(general.after_model(state, runtime=None) or {})     # 通用限流器先跑（栈里排更前面）
    state.update(search.after_model(state, runtime=None) or {})      # 搜索限流器后跑

    assert state["run_tool_call_count"]["__all__"] == 1              # 通用格子没被搜索限流器冲掉
    assert state["run_tool_call_count"]["internet_search"] == 1      # 搜索格子也正确记上了
