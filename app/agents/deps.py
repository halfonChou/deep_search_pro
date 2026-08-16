"""Agent 依赖容器。

从 main_agent.py 迁出，斩断 agents <-> tools 的循环依赖。
Day 10 更新：加入 sessions 字段，供 report_tools 查历史报告索引。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.config import Settings
from app.infra.db import Database
from app.infra.event_bus import EventBus

if TYPE_CHECKING:
    from app.services.session_service import SessionService


@dataclass
class AgentDeps:
    settings: Settings
    bus: EventBus
    db: Database | None = None
    retriever: object | None = None
    sessions: SessionService | None = None
    extra_tools: list = field(default_factory=list)
