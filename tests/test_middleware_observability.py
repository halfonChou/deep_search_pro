"""EventEmitMiddleware 单测。

验证三件事：
1. 工具成功 → 事件序列 tool_start → tool_end，且 elapsed_ms 合理
2. 工具抛异常 → 事件序列 tool_start → tool_error，且异常原样抛出（不被吞）
3. thread_id 从 runtime.context 的 RunContext 取，不是空串（修缺口 G4）
"""
from pathlib import Path

import pytest

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.middleware.observability import EventEmitMiddleware


class RecordingBus:
    """把 publish 的事件收进列表的假 EventBus，替代真实 EventBus 的订阅机制。"""

    def __init__(self):
        self.events: list[AgentEvent] = []

    async def publish(self, thread_id: str, event: AgentEvent) -> None:
        event.thread_id = thread_id      # 模拟真实 EventBus：用发布时的 thread_id 覆盖
        self.events.append(event)


class _FakeRuntime:
    """手工扮演 runtime：挂一个 context，模拟"在图里"的正常情况。"""

    def __init__(self, ctx):
        self.context = ctx


class _FakeRequest:
    """手工扮演 ToolCallRequest：字段对齐探测到的真实 dataclass。"""

    def __init__(self, runtime):
        self.tool_call = {"name": "search_tool", "args": {"q": "布洛芬"}, "id": "call_1"}
        self.tool = None
        self.state = {}
        self.runtime = runtime


async def _ok_handler(request):
    return "ok result"


async def _boom_handler(request):
    raise ValueError("boom")


@pytest.fixture
def ctx():
    return RunContext(thread_id="t-123", session_dir=Path("/tmp/whatever"))


async def test_tool_start_then_end(ctx):
    bus = RecordingBus()
    mw = EventEmitMiddleware(bus)
    runtime = _FakeRuntime(ctx)
    req = _FakeRequest(runtime)

    result = await mw.awrap_tool_call(req, _ok_handler)

    assert result == "ok result"
    types = [e.type for e in bus.events]
    assert types == ["tool_start", "tool_end"]

    start, end = bus.events
    assert start.thread_id == "t-123"            # 不是空串，修了 G4
    assert start.data["tool"] == "search_tool"
    assert end.data["elapsed_ms"] >= 0


async def test_tool_error_emitted_and_re_raised(ctx):
    bus = RecordingBus()
    mw = EventEmitMiddleware(bus)
    req = _FakeRequest(_FakeRuntime(ctx))

    with pytest.raises(ValueError, match="boom"):
        await mw.awrap_tool_call(req, _boom_handler)

    types = [e.type for e in bus.events]
    assert types == ["tool_start", "tool_error"]

    err_event = bus.events[-1]
    assert err_event.thread_id == "t-123"
    assert err_event.data["error"] == "ValueError"


async def test_plan_update_emitted_from_todos(ctx):
    """aafter_model 从 state 抽出 todos 发 plan_update。"""
    bus = RecordingBus()
    mw = EventEmitMiddleware(bus)
    state = {"todos": ["搜索", "对比", "出报告"]}

    await mw.aafter_model(state, _FakeRuntime(ctx))

    assert len(bus.events) == 1
    ev = bus.events[0]
    assert ev.type == "plan_update"
    assert ev.thread_id == "t-123"


async def test_runtime_none_falls_back_to_unknown():
    """runtime 为 None（图外调用）→ 不崩，thread_id 兜底为 unknown。"""
    bus = RecordingBus()
    mw = EventEmitMiddleware(bus)
    req = _FakeRequest(runtime=None)

    result = await mw.awrap_tool_call(req, _ok_handler)

    assert result == "ok result"
    assert bus.events[0].thread_id == "unknown"
