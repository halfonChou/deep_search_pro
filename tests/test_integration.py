"""Day 11 集成测试。

覆盖端到端关键路径：
1. EventBus 发布/订阅/重放/丢弃
2. TaskService 提交→事件流→完成
3. TaskService 取消传播
4. TaskService 幂等提交
5. HITL 审批恢复（decide → _resume）
6. SessionService 完整流程
7. 结构化日志 ThreadIdFilter
8. offload_if_large 与 run_agent_stream 联动（mock）
"""

import asyncio
import logging
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agents.events import AgentEvent
from app.config import Settings
from app.infra.event_bus import EventBus
from app.logging_config import ThreadIdFilter, current_thread_id, setup_logging
from app.services.session_service import SessionService
from app.services.task_service import TaskRecord, TaskService

# ============================================================
# 辅助工厂
# ============================================================

def _make_settings(**overrides) -> Settings:
    defaults = dict(
        llm_model="test",
        llm_base_url="http://localhost",
        llm_api_key="sk-test",
        mysql_password="test",
        mysql_database="test",
        tavily_api_key="tvly-test",
        embed_model="test",
        offload_threshold_bytes=100,
        offload_summary_chars=20,
        scratch_dir="/scratch",
        max_concurrent_tasks=2,
        event_queue_maxsize=100,
        session_ttl_hours=24,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ============================================================
# 1. EventBus 集成
# ============================================================

@pytest.mark.asyncio
async def test_eventbus_publish_subscribe():
    """发布事件后订阅者能收到。"""
    bus = EventBus(maxsize=100)
    events_received = []

    async def consumer():
        async for event in bus.subscribe("t1"):
            events_received.append(event)
            if event.type == "task_result":
                break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)

    await bus.publish("t1", AgentEvent(type="token", thread_id="t1", message="hello"))
    await bus.publish("t1", AgentEvent(type="task_result", thread_id="t1", message="done"))

    await asyncio.wait_for(task, timeout=2.0)
    assert len(events_received) == 2
    assert events_received[0].type == "token"
    assert events_received[1].type == "task_result"


@pytest.mark.asyncio
async def test_eventbus_history_replay():
    """晚连接的订阅者能收到历史缓冲。"""
    bus = EventBus(maxsize=100, history_limit=50)

    # 先发布，再订阅
    await bus.publish("t1", AgentEvent(type="token", thread_id="t1", message="earlier"))
    await bus.publish("t1", AgentEvent(type="task_result", thread_id="t1", message="fin"))

    events = []
    async for event in bus.subscribe("t1"):
        events.append(event)
        if event.type == "task_result":
            break

    assert len(events) == 2
    assert events[0].message == "earlier"


@pytest.mark.asyncio
async def test_eventbus_drop_clears():
    """drop 清空订阅者和历史。"""
    bus = EventBus(maxsize=100)
    await bus.publish("t1", AgentEvent(type="token", thread_id="t1", message="hi"))
    bus.drop("t1")
    assert "t1" not in bus._subscribers
    assert "t1" not in bus._history


# ============================================================
# 2. TaskService 完整生命周期
# ============================================================

@pytest.mark.asyncio
async def test_task_submit_and_complete():
    """提交任务 → agent 运行 → 状态变 done。"""
    settings = _make_settings()
    bus = EventBus(maxsize=100)
    sessions = MagicMock(spec=SessionService)
    sessions.dir_for.return_value = Path("/tmp/test_session")

    # mock agent：astream 产出一个 token 事件就结束
    async def fake_astream(*args, **kwargs):
        yield {"type": "messages", "data": (MagicMock(content="answer"), {})}

    agent = MagicMock()
    agent.astream = fake_astream

    svc = TaskService(agent=agent, bus=bus, sessions=sessions, settings=settings)
    tid = await svc.submit("test query", "thread-001")

    assert tid == "thread-001"
    # 等待任务完成
    await asyncio.sleep(0.3)
    # ★ 修复 _evict() 反向条件后：任务结束写 finished_at，记录保留到 TTL 过期，
    #   所以这里查到的是 done。原断言 not_found 编码的是"任务一结束记录就被误删"的 bug 行为。
    status = svc.status("thread-001")
    assert status["state"] == "done"
    assert status["running"] is False


@pytest.mark.asyncio
async def test_task_idempotent_submit():
    """同一 thread_id 重复提交直接返回，不起第二个任务。"""
    settings = _make_settings()
    bus = EventBus(maxsize=100)
    sessions = MagicMock(spec=SessionService)
    sessions.dir_for.return_value = Path("/tmp/test_session")

    # 让 agent 永远不结束
    async def slow_stream(*args, **kwargs):
        await asyncio.sleep(100)
        yield {"type": "messages", "data": (MagicMock(content=""), {})}

    agent = MagicMock()
    agent.astream = slow_stream

    svc = TaskService(agent=agent, bus=bus, sessions=sessions, settings=settings)
    tid1 = await svc.submit("q1", "thread-dup")
    tid2 = await svc.submit("q2", "thread-dup")

    assert tid1 == tid2
    # 只有一个 TaskRecord
    assert len(svc._task) == 1

    # 清理
    await svc.cancel("thread-dup")


@pytest.mark.asyncio
async def test_task_cancel():
    """取消正在运行的任务。"""
    settings = _make_settings()
    bus = EventBus(maxsize=100)
    sessions = MagicMock(spec=SessionService)
    sessions.dir_for.return_value = Path("/tmp/test_session")

    async def slow_stream(*args, **kwargs):
        await asyncio.sleep(100)
        yield {"type": "messages", "data": (MagicMock(content=""), {})}

    agent = MagicMock()
    agent.astream = slow_stream

    svc = TaskService(agent=agent, bus=bus, sessions=sessions, settings=settings)
    await svc.submit("q", "thread-cancel")
    await asyncio.sleep(0.1)

    ok = await svc.cancel("thread-cancel")
    assert ok is True


@pytest.mark.asyncio
async def test_task_error_publishes_error_event():
    """agent 抛异常 → 发布 error 事件。"""
    settings = _make_settings()
    bus = EventBus(maxsize=100)
    sessions = MagicMock(spec=SessionService)
    sessions.dir_for.return_value = Path("/tmp/test_session")

    async def error_stream(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # 让函数在语法上是个异步生成器（这行实际执行不到，仅为满足 astream 的签名）

    agent = MagicMock()
    agent.astream = error_stream

    svc = TaskService(agent=agent, bus=bus, sessions=sessions, settings=settings)

    events = []
    async def collect():
        async for event in bus.subscribe("thread-err"):
            events.append(event)
            if event.type == "error":
                break

    collector = asyncio.create_task(collect())
    await svc.submit("q", "thread-err")
    await asyncio.wait_for(collector, timeout=3.0)

    assert any(e.type == "error" for e in events)


# ============================================================
# 3. HITL 审批
# ============================================================

@pytest.mark.asyncio
async def test_task_decide_resume():
    """审批恢复：decide 创建新任务继续执行。"""
    settings = _make_settings()
    bus = EventBus(maxsize=100)
    sessions = MagicMock(spec=SessionService)
    sessions.dir_for.return_value = Path("/tmp/test_session")

    async def fake_astream(*args, **kwargs):
        yield {"type": "messages", "data": (MagicMock(content="resumed"), {})}

    agent = MagicMock()
    agent.astream = fake_astream

    svc = TaskService(agent=agent, bus=bus, sessions=sessions, settings=settings)

    await svc.decide("thread-decide", [{"action": "approve"}])
    assert "thread-decide" in svc._task
    assert svc._task["thread-decide"].state == "running"

    await asyncio.sleep(0.3)


# ============================================================
# 4. SessionService 集成
# ============================================================

@pytest.mark.asyncio
async def test_session_cleanup_expired():
    """过期会话目录被清理。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = _make_settings(data_dir=tmpdir)
        svc = SessionService(settings)

        # 创建一个会话目录
        session_root = Path(tmpdir) / "session"
        session_root.mkdir(parents=True, exist_ok=True)
        old_dir = session_root / "old-session"
        old_dir.mkdir()

        # 把修改时间设为很久以前
        import os
        old_time = time.time() - 48 * 3600  # 48小时前
        os.utime(old_dir, (old_time, old_time))

        removed = await svc.cleanup_expired(ttl_hours=24)
        assert removed == 1
        assert not old_dir.exists()


@pytest.mark.asyncio
async def test_session_dir_validation():
    """非法 thread_id 被拒绝。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = _make_settings(data_dir=tmpdir)
        svc = SessionService(settings)

        with pytest.raises(ValueError, match="非法"):
            svc.dir_for("../../../etc/passwd")


# ============================================================
# 5. 结构化日志 ContextVars
# ============================================================

def test_thread_id_filter_injects_context():
    """ThreadIdFilter 从 contextvars 注入 thread_id。"""
    filt = ThreadIdFilter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)

    # 默认值
    filt.filter(record)
    assert record.thread_id == "-"  # type: ignore[attr-defined]

    # 设置后
    token = current_thread_id.set("my-thread-42")
    try:
        filt.filter(record)
        assert record.thread_id == "my-thread-42"  # type: ignore[attr-defined]
    finally:
        current_thread_id.reset(token)


def test_setup_logging_idempotent():
    """多次调用 setup_logging 不会重复添加 handler。"""
    root = logging.getLogger()
    import sys
    initial_count = sum(
        1 for h in root.handlers
        if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
    )
    setup_logging()
    setup_logging()
    final_count = sum(
        1 for h in root.handlers
        if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
    )
    # 最多增加 1 个
    assert final_count <= initial_count + 1


# ============================================================
# 6. TaskRecord 数据结构
# ============================================================

def test_task_record_defaults():
    """TaskRecord 默认状态和字段。"""
    r = TaskRecord(thread_id="t1")
    assert r.state == "pending"
    assert r.task is None
    assert r.created_at > 0


# ============================================================
# 7. AgentEvent 序列化
# ============================================================

def test_agent_event_serializable():
    """AgentEvent 可以 asdict → JSON。"""
    import json
    evt = AgentEvent(type="token", thread_id="t1", message="hi", data={"key": "val"})
    d = asdict(evt)
    s = json.dumps(d, ensure_ascii=False)
    assert '"token"' in s
    assert '"hi"' in s
