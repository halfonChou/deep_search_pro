from __future__ import annotations

from typing import Protocol

from app.agents.events import AgentEvent
from app.infra.event_bus import EventBus

# protocol 接口的规定

class EventEmitter(Protocol):
    """事件发射器接口：必须实现emit方法"""
    async def emit(self, event: AgentEvent) -> None: ...

class RecordingEmitter:
    def __init__(self):
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


class ConsoleEmitter:
    async def emit(self, event: AgentEvent) -> None:
        print(f"[{event.type}] {event.thread_id}: {event.message}")

class NullEmitter:
    """静默丢弃所有事件，用于不需要事件推送的场景。"""
    async def emit(self, event: AgentEvent) -> None:
        pass

class WebSocketEmitter:
    """把事件发布到 EventBus 由 WebScoket进行"""
    def __init__(self, bus:EventBus, thread_id:str):
        self._bus = bus
        self._thread_id = thread_id
    async def emit(self, event: AgentEvent) -> None:
        await self._bus.publish(self._thread_id, event)
