import asyncio
import logging
import time
from dataclasses import dataclass, field

from app.agents.context import RunContext
from app.agents.events import AgentEvent
from app.agents.stream import run_agent_stream
from app.config import Settings
from app.infra.event_bus import EventBus
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

@dataclass
class TaskRecord:
    """一个任务完整的记录：状态 + asyncio + 创建时间"""
    thread_id: str
    state:str = "pending"
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.monotonic)

class TaskService:
    def __init__(self, agent, bus: EventBus, sessions: SessionService, settings: Settings):
        self._agent = agent
        self._bus = bus
        self._sessions = sessions
        self._settings = settings
        self._task : dict[str, TaskRecord] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)

    async def submit(self, query:str, thread_id:str):
        if thread_id in self._task:
            return thread_id
        record = TaskRecord(thread_id=thread_id)
        self._task[thread_id] = record

        # 把执行打包，包装为字典，然后再启动
        record.task = asyncio.create_task(self._run(query, thread_id))
        record.task.add_done_callback(lambda t: self._on_done(thread_id,t))
        return thread_id

    async def _run(self, query:str, thread_id:str):
        async with self._sem:
            record = self._task.get(thread_id)
            if record:
                record.state = "running"
            await self._bus.publish(
                thread_id,
                AgentEvent(
                    type="task_result", thread_id=thread_id,
                    message="任务开始"
                ),
            )
            ctx = RunContext(thread_id=thread_id,
                             session_dir=self._sessions.dir_for(thread_id=thread_id))
            try:
                await run_agent_stream(self._agent,query,ctx,self._bus)
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
                               message=f"任务失败: {e}")
                )
            finally:
                self._bus.drop(thread_id)

    def _on_done(self, thread_id, task:asyncio.Task):
        if task.exception() and not task.cancelled():
            logger.warning("任务 %s 未有捕获异常： %s", thread_id, task.exception())
        self._task.pop(thread_id, None)

    def status(self, thread_id):
        record = self._task.get(thread_id)
        if record is None:
            return {"thread_id":thread_id, "state":"not_found"}
        return {"thread_id":thread_id, "state":record.state}

    async def cancel(self, thread_id):
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

    async def decide(self, thread_id, decisions: list[dict]):
        """human in the loop"""
        record = self._task.get(thread_id)
        if record is None:
            record = TaskRecord(thread_id=thread_id)
            self._task[thread_id] = record

        record.state = "running"
        ctx = RunContext(thread_id=thread_id,
                         session_dir=self._sessions.dir_for(thread_id=thread_id))
        record.task = asyncio.create_task(
            self._resume(thread_id, ctx,decisions))
        record.task.add_done_callback(lambda t: self._on_done(thread_id,t))

    async def _resume(self, thread_id: str, ctx: RunContext, decisions: list[dict]):
        """恢复中断任务的执行体，复刻 _run 的状态推进 + 事件发布。"""
        try:
            await run_agent_stream(
                self._agent, query="", ctx=ctx, bus=self._bus,
                resume={"decisions": decisions},
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
