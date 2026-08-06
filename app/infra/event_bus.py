import asyncio
import logging

from app.agents.events import AgentEvent

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self, maxsize: int = 1000, max_subscribers_per_thread=10, history_limit: int = 100):
        self._subscribers: dict[str, set[asyncio.Queue[AgentEvent]]] = {}
        self._history: dict[str, list[AgentEvent]] = {}
        self._maxsize = maxsize
        self._history_limit = history_limit
        self._max_subscribers = max_subscribers_per_thread

    def _queue(self, thread_id: str):
        if thread_id not in self._subscribers:
            self._subscribers[thread_id] = set()
        return self._subscribers[thread_id]

    def _push_history(self, thread_id: str, event: AgentEvent):
        history = self._history.setdefault(thread_id, [])
        history.append(event)
        if len(history) > self._history_limit:
            del history[: len(history) - self._history_limit]

    async def publish(self, thread_id: str, event: AgentEvent):
        # 删除并且获取队列
        self._push_history(thread_id,event)
        queue = self._queue(thread_id)
        for q in queue:
            if q.full():
                q.get_nowait()
                logger.info("Queue is full for thread %s, dropping oldest", thread_id)
            await q.put(event)


    async def subscribe(self, thread_id: str):
        queue = self._queue(thread_id)
        if len(queue) >= self._max_subscribers:
            raise RuntimeError(f"Thread {thread_id} 订阅者已经达到上限 {self._max_subscribers}")
        q: asyncio.Queue[AgentEvent] = asyncio.Queue(maxsize=self._maxsize)
        queue.add(q)
        try:
            # 重放历史：队列满就用 put_nowait 放弃更旧的，绝不阻塞（否则晚连接会死锁）
            for event in self._history.get(thread_id, []):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    break
            while True:
                event = await q.get()
                yield event
        finally:
            self._unsubscribe(thread_id, q)

    def _unsubscribe(self, thread_id: str, q: asyncio.Queue[AgentEvent]):
        queue = self._subscribers.get(thread_id)
        if queue is not None:
            queue.discard(q)
            if not queue:
                self._subscribers.pop(thread_id, None)

    def drop(self, thread_id: str):
        self._subscribers.pop(thread_id, None)
        self._history.pop(thread_id, None)
