from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

# dataclass 自从生成init方法

EventType = Literal[
    "session_created",
    "tool_start",
    "tool_end",
    "subagent_call",
    "token",
    "task_result",
    "error",
]
@dataclass
class AgentEvent:
    type: EventType
    thread_id: str
    message: str = ""
    data: dict[str,Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda : datetime.now(UTC).isoformat())
