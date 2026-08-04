from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

# dataclass 自从生成init方法

EventType = Literal[
    "session_created", "plan_update",          # 规划
    "subagent_call", "subagent_result",        # 委托
    "tool_start", "tool_end", "tool_error",    # 工具
    "token", "task_result", "error",           # 输出
    "interrupt", "budget_warning",             # 审批 / 预算
]
@dataclass
class AgentEvent:
    type: EventType
    thread_id: str
    message: str = ""
    data: dict[str,Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda : datetime.now(UTC).isoformat())
