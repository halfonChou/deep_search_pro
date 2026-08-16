import asyncio
from types import SimpleNamespace

from app.infra.event_bus import EventBus
from app.services.task_service import TaskRecord, TaskService


async def main():
    settings = SimpleNamespace(max_concurrent_tasks=5)
    svc = TaskService(agent=None, bus=EventBus(), sessions=None, settings=settings)

    class FakeTask:
        def cancelled(self):
            return False
        def exception(self):
            return None

    fake_task_b = FakeTask()   # ← 先造出来

    svc._task["A"] = TaskRecord(thread_id="A", state="running")
    svc._task["B"] = TaskRecord(thread_id="B", state="running", task=fake_task_b)  # ← 存进 record

    svc._on_done("B", fake_task_b)   # ← 传的是同一个对象，通过身份校验

    print("A status:", svc.status("A"))
    print("B status:", svc.status("B"))


asyncio.run(main())
