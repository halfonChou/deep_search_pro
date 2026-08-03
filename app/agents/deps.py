from dataclasses import dataclass, field
from pathlib import Path

from app.config import Settings
from app.infra.db import Database
from app.infra.event_bus import EventBus
from app.infra.emitter import EventEmitter


@dataclass
class AgentDeps:
    settings: Settings
    bus: EventBus
    emitter: EventEmitter          # 暂留，Day 3 删
    session_dir: Path              # 暂留，Day 3 迁到 RunContext
    thread_id: str = ""
    tools: list = field(default_factory=list)
    db: Database | None = None
    retriever: object | None = None
    pdf_converter: object | None = None
    extra_tools: list = field(default_factory=list)