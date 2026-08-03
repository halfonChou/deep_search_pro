from dataclasses import dataclass
from pathlib import Path

@dataclass
class RunContext:
    thread_id: str
    session_dir: Path