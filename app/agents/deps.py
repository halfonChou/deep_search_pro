from dataclasses import dataclass, field

from app.config import Settings
from app.infra.db import Database
from app.infra.event_bus import EventBus


@dataclass
class AgentDeps:
    settings: Settings
    bus: EventBus
    thread_id: str = ""
    tools: list = field(default_factory=list)
    db: Database | None = None
    retriever: object | None = None
    pdf_converter: object | None = None
    extra_tools: list = field(default_factory=list)
