import asyncio

from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus


async def main():
    bus = EventBus()
    thread_id = "t1"

    # 手工造 3 个订阅者的队列，模拟同一个 thread_id 下开了 3 个窗口
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    q3: asyncio.Queue = asyncio.Queue()

    subscribers = bus._queue(thread_id)   # 拿到内部那个 set
    subscribers.add(q1)
    subscribers.add(q2)
    subscribers.add(q3)

    # 关键：给 q1 的 put 方法打个补丁——
    # "q1.put 执行完之后，立刻模拟 q2 对应的窗口断开连接"
    # 对应真实场景里：publish() 在给 q1 塞信的 await 期间，
    # q2 的 WebSocket 断开触发了 finally 里的 discard(q2)
    original_put = q1.put

    async def put_then_disconnect(event):
        await original_put(event)
        subscribers.discard(q2)   # 模拟 q2 中途断开
        print("[模拟] q2 已断开，订阅者从 3 个变成 2 个")

    q1.put = put_then_disconnect

    event = AgentEvent(type="task_result", thread_id=thread_id, message="hello")

    try:
        await bus.publish(thread_id, event)
        print("✅ publish 正常完成，没有抛异常")
    except RuntimeError as e:
        print(f"❌ publish 崩溃了：{e}")

    print("q1 收到消息数:", q1.qsize())
    print("q2 收到消息数:", q2.qsize())
    print("q3 收到消息数:", q3.qsize())


asyncio.run(main())
