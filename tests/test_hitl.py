"""Day 7 HITL（人工审批）单测。

分三层验证：
1. _serialize_interrupt：把探测到的 __interrupt__ 实物结构（tuple 包 Interrupt.value）
   转成前端能用的 {action_requests, review_configs}。
2. _serialize_interrupt：兜底分支（list / raw）不崩。
3. run_agent_stream 的 resume 分支：resume 传入时，input 是 Command(resume=...)，
   而不是初始 dict —— 这是"审批后从 checkpoint 恢复"的单元级证据。
"""

from langgraph.types import Command, Interrupt

from app.agents.context import RunContext
from app.agents.stream import _serialize_interrupt, run_agent_stream

# ===== 1. _serialize_interrupt：主分支（tuple + Interrupt.value）=====

def test_serialize_interrupt_main_tuple():
    """探测到的实物：tuple 包 Interrupt，value 里是 action_requests + review_configs。"""
    interrupt = (
        Interrupt(
            value={
                "action_requests": [
                    {"name": "execute_sql_query",
                     "args": {"query": "SELECT * FROM sales_record"},
                     "description": "Tool execution requires approval"},
                ],
                "review_configs": [
                    {"action_name": "execute_sql_query",
                     "allowed_decisions": ["approve", "edit", "reject"]},
                ],
            },
            id="44e6a515",
        ),
    )

    result = _serialize_interrupt(interrupt)

    assert "action_requests" in result
    assert result["action_requests"][0]["name"] == "execute_sql_query"
    assert result["review_configs"][0]["allowed_decisions"] == ["approve", "edit", "reject"]


def test_serialize_interrupt_fallback_list():
    """兜底：老版本可能是 list，原样包一层 action_requests，不崩。"""
    result = _serialize_interrupt([{"name": "x", "args": {}}])
    assert result["action_requests"][0]["name"] == "x"


def test_serialize_interrupt_fallback_raw():
    """兜底：未知结构，包一层 raw，绝不抛异常。"""
    result = _serialize_interrupt({"weird": "shape"})
    assert result["raw"] == {"weird": "shape"}


# ===== 2. run_agent_stream 的 resume 分支 =====

class _RecordingAgent:
    """记录 astream 收到的 input，验证 resume 时是 Command 而非初始 dict。"""

    def __init__(self):
        self.seen_inputs = []
        self._emitted = False

    async def astream(self, input_, **kwargs):
        self.seen_inputs.append(input_)
        # 模拟中断后恢复：直接吐一个 updates 说完成了
        if not self._emitted:
            self._emitted = True
            yield {"type": "updates", "data": {"__end__": None}}
        else:
            yield {"type": "updates", "data": {"__end__": None}}


class _RecordingBus:
    def __init__(self):
        self.events = []

    async def publish(self, thread_id, event):
        self.events.append((thread_id, event))


async def test_resume_passes_command_to_astream():
    """resume 传入时 → astream 收到的是 Command(resume=...)，不是初始 dict。"""
    agent = _RecordingAgent()
    bus = _RecordingBus()
    ctx = RunContext(thread_id="t1", session_dir=None)

    await run_agent_stream(agent, query="", ctx=ctx, bus=bus,
                           resume={"decisions": [{"type": "approve"}]})

    input_ = agent.seen_inputs[0]
    assert isinstance(input_, Command)
    # Command.resume 里带着我们透传的 decisions
    assert input_.resume == {"decisions": [{"type": "approve"}]}


async def test_no_resume_passes_initial_dict():
    """没有 resume → astream 收到的是初始 dict（含用户 query）。"""
    agent = _RecordingAgent()
    bus = _RecordingBus()
    ctx = RunContext(thread_id="t1", session_dir=None)

    await run_agent_stream(agent, query="查一下", ctx=ctx, bus=bus)

    input_ = agent.seen_inputs[0]
    assert isinstance(input_, dict)
    assert input_["messages"][0]["content"] == "查一下"
