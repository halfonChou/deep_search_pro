"""EventBus 单测 —— fan-out + 历史重放版语义。

验证三个新能力：
1. 晚连接订阅者能重放历史缓冲（订阅前的事件也拿得到）
2. 多个订阅者各拿各的，不互相抢事件（fan-out）
3. 历史缓冲有上限，不会被无限累积撑爆内存
"""
import asyncio

from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus


async def test_subscribe_receives_buffered_events():
    """发布后订阅：订阅者能收到事件。"""
    bus = EventBus(maxsize=10)
    event = AgentEvent(type="tool_start", thread_id="tool_001", message="hello")

    await bus.publish("tool_001", event)

    sub = bus.subscribe("tool_001")
    re = await anext(sub)

    assert re.type == "tool_start"
    assert re.message == "hello"


async def test_late_subscriber_gets_history():
    """晚连接订阅者能收到订阅前缓冲的历史事件（历史重放）。"""
    bus = EventBus(maxsize=2, history_limit=100)

    await bus.publish("t1", AgentEvent(type="tool_start", thread_id="t1", message="first"))
    await bus.publish("t1", AgentEvent(type="tool_end", thread_id="t1", message="second"))

    # 订阅前已发布 2 条 → 晚订阅者重放后应都能拿到
    subscriber = bus.subscribe("t1")
    e1 = await anext(subscriber)
    e2 = await anext(subscriber)

    assert e1.message == "first"
    assert e2.message == "second"


async def test_fanout_no_stealing():
    """两个订阅者各拿各的，谁都不抢（fan-out 核心）。"""
    bus = EventBus(maxsize=10)
    await bus.publish("t1", AgentEvent(type="tool_start", thread_id="t1", message="event"))

    # 两个订阅者各自拿到同一份事件
    sub1 = bus.subscribe("t1")
    sub2 = bus.subscribe("t1")
    r1 = await anext(sub1)
    r2 = await anext(sub2)

    assert r1.message == "event"
    assert r2.message == "event"    # 两个都拿到，不互相抢


async def test_history_limit_bounded():
    """历史缓冲有上限：只保留最近 history_limit 条，更旧的被裁剪。"""
    bus = EventBus(maxsize=10, history_limit=2)

    await bus.publish("t1", AgentEvent(type="tool_start", thread_id="t1", message="first"))
    await bus.publish("t1", AgentEvent(type="tool_end", thread_id="t1", message="second"))
    await bus.publish("t1", AgentEvent(type="task_result", thread_id="t1", message="third"))

    # 历史只留最近 2 条 → 晚订阅者只能拿到 second/third
    subscriber = bus.subscribe("t1")
    e1 = await anext(subscriber)
    e2 = await anext(subscriber)

    assert e1.message == "second"    # "first" 被裁剪掉了
    assert e2.message == "third"


async def test_max_subscribers_rejected():
    """订阅者数量超过上限 → 拒绝新订阅。"""
    bus = EventBus(maxsize=10, max_subscribers_per_thread=2)
    # 手动挂上 2 个订阅者队列，模拟已有 2 个客户端在订
    bus._queue("t1").add(asyncio.Queue())
    bus._queue("t1").add(asyncio.Queue())

    # 第 3 个订阅者应被拒绝（subscribe 在检查上限时抛 RuntimeError）
    try:
        sub3 = bus.subscribe("t1")
        await sub3.__anext__()
        raise AssertionError("应该拒绝第 3 个订阅者")
    except RuntimeError:
        pass
