"""任务生命周期管理。

asyncio.create_task 裸用会导致任务无人管、异常静默丢失，
所以统一收进这里：信号量限流 + 弱引用跟踪 + 取消传播 + 幂等提交。

Day 11 更新：在 _run 入口设置 contextvars thread_id，
让所有下游日志自动带上 thread_id，并发任务可区分。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.agents.stream import run_agent_stream
from app.config import Settings
from app.infra.event_bus import EventBus
from app.logging_config import current_thread_id
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    """一个任务完整的记录：状态 + asyncio.Task + 创建时间"""
    thread_id: str
    state: str = "pending"
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    error: str | None = None

_ACTIVE_STATES = {"pending", "running"}
_MAX_RECORDS = 200
_RECORD_TTL = 15 * 60

class TaskService:
    def __init__(self, agent, bus: EventBus, sessions: SessionService, settings: Settings):
        self._agent = agent
        self._bus = bus
        self._sessions = sessions
        self._settings = settings
        self._task: dict[str, TaskRecord] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)

    async def submit(self, query: str, thread_id: str):
        """幂等：同 thread_id 已在跑则直接返回，不重复起任务。"""
        old = self._task.get(thread_id)

        if old is not None and old.state in _ACTIVE_STATES:
            return thread_id

        self._task.pop(thread_id, None)

        record = TaskRecord(thread_id=thread_id)

        self._task[thread_id] = record
        record.task = asyncio.create_task(self._run(query, thread_id))
        record.task.add_done_callback(lambda t: self._on_done(thread_id, t))
        return thread_id

    async def _run(self, query: str, thread_id: str):
        # Day 11：设置 contextvars，让所有下游日志自动带 thread_id
        current_thread_id.set(thread_id)

        async with self._sem:
            record = self._task.get(thread_id)
            if record:
                record.state = "running"
            await self._bus.publish(
                thread_id,
                AgentEvent(
                    type="task_result", thread_id=thread_id,
                    message="任务开始",
                ),
            )
            ctx = RunContext(
                thread_id=thread_id,
                session_dir=self._sessions.dir_for(thread_id=thread_id),
            )
            try:
                await run_agent_stream(self._agent, query, ctx, self._bus)
                if record:
                    record.state = "done"
            except asyncio.CancelledError:
                if record:
                    record.state = "cancelled"
                raise
            except Exception as e:
                logger.exception("任务 %s 失败", thread_id)
                if record:
                    record.state = "error"
                await self._bus.publish(
                    thread_id,
                    AgentEvent(type="error", thread_id=thread_id,
                               message=f"任务失败: {e}"),
                )
            finally:
                # ★ 只清历史缓冲，不要动订阅者。
                # 原来这里是 bus.drop()，会把前端那条还活着的 WebSocket 从
                # 订阅者集合里摘掉 —— 同一会话跑第二个任务时，前端全程收不到事件。
                self._bus.clear_history(thread_id)

    def _evict(self):
        now = time.monotonic()

        for tid, rec in list(self._task.items()):
            if rec.finished_at is not None and now - rec.finished_at > _RECORD_TTL:
                del self._task[tid]

        finished = [tid for tid, rec in list(self._task.items()) if rec.finished_at is not None]
        overflow = len(finished) - _MAX_RECORDS
        for tid in finished[:overflow] if overflow > 0 else []:
            del self._task[tid]

    def _on_done(self, thread_id: str, task: asyncio.Task) -> None:
        record = self._task.get(thread_id)

        if record is None or record.task is not  task:
            return

        if not task.cancelled() and (exc := task.exception()) is not None:
            logger.warning("任务 %s 未捕获异常: %s", thread_id, exc)
            record.error = f"{type(exc).__name__}: {exc}"

        if record.state in _ACTIVE_STATES:
            record.state = "cancelled" if task.cancelled() else "error"

        record.finished_at = time.monotonic()
        record.task = None
        self._evict()

    def status(self, thread_id: str):
        record = self._task.get(thread_id)
        if record is None:
            return {"thread_id": thread_id, "state": "not_found"}
        return {
            "thread_id": thread_id,
            "state": record.state,
            "error": record.error,
            "running": record.state in _ACTIVE_STATES,
        }

    async def cancel(self, thread_id: str):
        record = self._task.get(thread_id)
        if record is None or record.task is None:
            return False
        record.task.cancel()
        try:
            await record.task
        except (asyncio.CancelledError, Exception):
            pass
        record.state = "cancelled"
        return True

    @staticmethod
    def _build_resume(decisions) -> dict:
        """把前端提交的决策转成 LangGraph 认识的 resume 载荷。

        ★★ 两种形态，因为挂起的中断可能不止一个：

        1. 单个中断 —— 前端传列表 [{"type": "approve"}]
           → resume = {"decisions": [...]}，就是 interrupt() 的返回值本身

        2. 多个中断 —— 前端传字典 {中断id: [{"type": "approve"}], ...}
           → resume = {中断id: {"decisions": [...]}, ...}

        第 2 种是必须的：主 Agent 一轮里派出多个子 Agent 时，每个都会停在
        自己的审批点，于是同时挂起多个 interrupt。这时候 LangGraph 拒绝笼统的
        单值 resume，报「When there are multiple pending interrupts, you must
        specify the interrupt id when resuming」——它无法知道你这个决策
        是给哪一个中断的。
        """
        if isinstance(decisions, dict):
            return {
                iid: (ds if isinstance(ds, dict) else {"decisions": ds})
                for iid, ds in decisions.items()
            }
        return {"decisions": decisions}

    async def decide(self, thread_id: str, decisions):
        """HITL 审批恢复。decisions 可以是列表（单中断）或 {中断id: 决策}（多中断）。"""
        record = self._task.get(thread_id)
        if record is None:
            record = TaskRecord(thread_id=thread_id)
            self._task[thread_id] = record

        record.state = "running"
        ctx = RunContext(
            thread_id=thread_id,
            session_dir=self._sessions.dir_for(thread_id=thread_id),
        )
        resume = self._build_resume(decisions)
        logger.info(
            "[hitl] 恢复任务 %s | 中断数=%d",
            thread_id, len(resume) if isinstance(decisions, dict) else 1,
        )
        record.task = asyncio.create_task(
            self._resume(thread_id, ctx, resume),
        )
        record.task.add_done_callback(lambda t: self._on_done(thread_id, t))

    async def _resume(self, thread_id: str, ctx: RunContext, resume: dict):
        """恢复中断任务的执行体。"""
        # Day 11：设置 contextvars
        current_thread_id.set(thread_id)

        try:
            await run_agent_stream(
                self._agent, query="", ctx=ctx, bus=self._bus,
                resume=resume,
            )
            record = self._task.get(thread_id)
            if record:
                record.state = "done"
        except asyncio.CancelledError:
            record = self._task.get(thread_id)
            if record:
                record.state = "cancelled"
            raise
        except Exception as e:
            logger.exception("任务 %s 恢复失败", thread_id)
            record = self._task.get(thread_id)
            if record:
                record.state = "error"
            await self._bus.publish(
                thread_id,
                AgentEvent(type="error", thread_id=thread_id,
                           message=f"任务恢复失败: {e}"),
            )
