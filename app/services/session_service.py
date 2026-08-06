import asyncio
import json
import re
import time
from pathlib import Path

from app.config import Settings


class SessionService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = asyncio.Lock()

    def dir_for(self, thread_id: str) -> Path:
        """会话的目录仅由服务端从 thread_id 推导"""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",thread_id):
            raise ValueError(f"非法 thread_id：{thread_id}")
        d = (self._settings.data_dir / "session" / thread_id).resolve()
        d.mkdir(exist_ok=True, parents=True)
        return d

    async def record_report(self, thread_id: str, summary:str, topic:str, path:Path) -> dict:
        if len(summary) > 100:
            raise ValueError(f"summary 字数过长，超出100字，实际长度{len(summary)}字")
        entry = {
            "thread_id": thread_id,
            "summary": summary,
            "topic": topic,
            "path": str(path),
            "ts":time.time(),
        }
        index_file = self._settings.report_index_file
        async with self._lock:
            # 先给文件锁住
            index_file.parent.mkdir(exist_ok=True, parents=True)
            with index_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def list_reports(self, keyword:str|None = None, limit:int=20) -> list:
        """查询历史报告"""
        index_file = self._settings.report_index_file
        if not index_file.exists():
            return []
        result = []
        async with self._lock:
            with index_file.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if keyword and keyword.lower() not in entry.get("summary", "").lower() and keyword.lower() not in entry.get("topic", ""):
                        continue
                    result.append(entry)
        result.sort(key=lambda x: x['ts', 0], reverse=True)
        return result[:limit]

    async def cleanup_expired(self, ttl_hours:int):
        """后台携程 按照TTL清理过期会话"""
        sessions_root = self._settings.data_dir / "session"

        if not sessions_root.exists():
            return 0
        cutoff = time.time() - ttl_hours * 60 * 60
        removed = 0
        for child in sessions_root.iterdir():
            if not child.is_dir():
                continue
            if child.stat().st_mtime < cutoff:
                import shutil
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed
