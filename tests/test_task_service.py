"""TaskService 边界测试。

覆盖文档要求 4 个用例：
1. 幂等提交：同 thread_id 重复提交不重复起任务
2. 取消：cancel 后状态变 cancelled，且 await 能正常返回
3. 并发上限：超过 max_concurrent_tasks 的任务排队等待
4. 晚订阅补发：订阅者能收到任务运行中的事件
"""
import asyncio

import pytest

from app.infra.event_bus import EventBus
from app.services.session_service import SessionService
from app.services.task_service import TaskService


class _FakeAgent:
    """假 agent：跑完发一个 token 事件就结束，模拟真实 agent 的流式输出。"""

    def __init__(self, delay: float = 0.01):
        self._delay = delay
        self.calls = 0

    async def astream(self, *args, **kwargs):
        self.calls += 1
        await asyncio.sleep(self._delay)
        yield {"type": "messages", "data": (type("T", (), {"content": "hi"}), {})}


def _make_settings(tmp_path, **overrides):
    from app.config import Settings

    defaults = {
        "llm_model": "test",
        "llm_base_url": "http://localhost",
        "llm_api_key": "test",
        "mysql_password": "test",
        "mysql_database": "test",
        "tavily_api_key": "test",
        "embed_model": "test",
        "data_dir": tmp_path,
        "max_concurrent_tasks": 2,   # 并发上限设为 2，方便测排队
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def task_service(tmp_path):
    """构造一个带假 agent 的 TaskService。"""
    settings = _make_settings(tmp_path)
    bus = EventBus(maxsize=10)
    sessions = SessionService(settings)
    agent = _FakeAgent()
    return TaskService(agent=agent, bus=bus, sessions=sessions, settings=settings)


async def test_submit_starts_task_and_status_running(task_service):
    """提交任务 → 状态 running（任务在跑）。"""
    tid = await task_service.submit(query="查布洛芬", thread_id="t1")
    assert tid == "t1"
    # sleep(0) 让出控制权，事件循环才会调度 _run 真正启动
    await asyncio.sleep(0)
    assert task_service.status("t1")["state"] == "running"
    # 等任务跑完
    await asyncio.sleep(0.1)
    assert task_service.status("t1")["state"] in ("done", "not_found")


async def test_submit_idempotent_same_thread(task_service):
    """幂等：同 thread_id 重复提交，不重复起任务。"""
    agent = task_service._agent
    await task_service.submit("查布洛芬", "t1")
    await task_service.submit("查布洛芬", "t1")   # 重复提交（第一个任务还在 _task 里）
    # 等唯一那个任务真正跑完 → agent 应该只被调用一次
    await asyncio.sleep(0.1)
    assert agent.calls == 1


async def test_cancel_changes_state(task_service):
    """取消任务 → 状态变 cancelled。"""
    settings = task_service._settings
    # 用一个慢 agent 让任务在跑，方便取消
    slow = _FakeAgent(delay=1.0)
    bus = EventBus(maxsize=10)
    sessions = SessionService(settings)
    svc = TaskService(agent=slow, bus=bus, sessions=sessions, settings=settings)

    await svc.submit("慢查询", "t2")
    await asyncio.sleep(0)   # 等 _run 启动，状态变 running
    assert svc.status("t2")["state"] == "running"

    ok = await svc.cancel("t2")
    assert ok is True
    # 取消后状态是 cancelled（或任务已被移除，返回 not_found）
    state = svc.status("t2")["state"]
    assert state in ("cancelled", "not_found")


async def test_concurrency_limit_queues(task_service):
    """并发上限：同时提交超过 max_concurrent_tasks 个任务，后面的排队。"""
    # max_concurrent_tasks=2，提交 3 个任务
    await task_service.submit("任务1", "t1")
    await task_service.submit("任务2", "t2")
    await task_service.submit("任务3", "t3")

    # 3 个任务都在登记表里（t3 在排队）
    assert "t1" in task_service._task
    assert "t2" in task_service._task
    assert "t3" in task_service._task

    # 等所有任务跑完。
    # ★ 等的是 finished_at 而不是 state=="done"：state 由 _run() 在协程体里设，
    #   finished_at 由 _on_done 回调设，而 done_callback 要等下一轮事件循环才触发。
    #   盯 state 会在回调跑完之前就跳出循环 —— 那是个竞态。
    for _ in range(50):
        if all(rec.finished_at is not None for rec in task_service._task.values()):
            break
        await asyncio.sleep(0.05)

    # ★ 修复 _evict() 反向条件后的正确行为（原断言 `_task == {}` 编码的是 bug 行为）：
    #   任务结束只写 finished_at，记录要留到超过 _RECORD_TTL(15min) 才清理。
    #   记录立刻消失恰恰是 bug —— 那会让 status()/cancel()/幂等提交全部失效。
    assert set(task_service._task) == {"t1", "t2", "t3"}
    assert all(rec.state == "done" for rec in task_service._task.values())
    assert all(rec.finished_at is not None for rec in task_service._task.values())


async def test_late_subscriber_receives_events(task_service):
    """晚订阅者能收到任务运行中的事件（EventBus 历史重放）。"""
    bus = task_service._bus
    # 先订阅再提交任务，这样事件进订阅者队列
    await task_service.submit("查布洛芬", "t9")
    sub = bus.subscribe("t9")

    # 任务开始时会发 task_result 事件，晚订阅者通过历史重放拿到
    event = await asyncio.wait_for(sub.__anext__(), timeout=2)
    assert event.type == "task_result"
