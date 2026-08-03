import asyncio
import logging

from app.agents.events import AgentEvent

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self, maxsize: int = 1000):
        self._queue: dict[str, asyncio.Queue[AgentEvent]] = {}
        self._maxsize = maxsize

    def _get_queue(self, thread_id: str):
        if thread_id not in self._queue:
            self._queue[thread_id] = asyncio.Queue(maxsize=self._maxsize)
        return self._queue[thread_id]

    async def publish(self, thread_id: str, event: AgentEvent):
        queue = self._get_queue(thread_id)
        if queue.full():
            queue.get_nowait()
            logger.info(f"Queue is full for thread {thread_id}")
        await queue.put(event)


    async def subscribe(self, thread_id: str):
        queue = self._get_queue(thread_id)
        while True:
            event = await queue.get()
            yield event


    def drop(self, thread_id: str):
        self._queue.pop(thread_id, None)
