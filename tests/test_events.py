from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus

async def test_subscribe_receives_buffered_events():
    bus = EventBus(maxsize=10)
    event = AgentEvent(type="tool_start", thread_id="tool_001", message="hello")

    await bus.publish("tool_001", event)

    sub = bus.subscribe("tool_001")
    re = await anext(sub)

    assert re.type == "tool_start"
    assert re.message == "hello"

async def test_oldest_event_dropped_when_full():
    """队列满时丢弃最旧的事件。"""
    bus = EventBus(maxsize=2)

    await bus.publish("t1", AgentEvent(type="tool_start", thread_id="t1", message="first"))
    await bus.publish("t1", AgentEvent(type="tool_end", thread_id="t1", message="second"))
    # 队列已满（2个），再放一个会丢掉最旧的 "first"
    await bus.publish("t1", AgentEvent(type="task_result", thread_id="t1", message="third"))

    subscriber = bus.subscribe("t1")
    e1 = await anext(subscriber)
    e2 = await anext(subscriber)

    assert e1.message == "second"    # "first" 被丢了
    assert e2.message == "third"