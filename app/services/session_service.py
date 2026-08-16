import asyncio
import json
import re
import time
from pathlib import Path

from app.config import Settings

_SUMMARY_MAX = 100

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

    import asyncio


    async def record_report(self, thread_id: str, topic: str, summary: str, path: Path) -> None:
        #                                                              ↑ 返回类型改成 None（本来就不 return）

        # ★ 原来超长直接 raise ValueError —— 这是错的。
        #   模型多写 5 个字，工具就报错，而此时文件已经写到磁盘上了：
        #   用户能拿到报告，模型却收到「失败」，它会困惑地重试一次，白烧一轮。
        #   摘要长一点不是错误，截断就行。
        summary = summary.strip()[:_SUMMARY_MAX]
        topic = topic.strip()[:50]

        entry = {
            "thread_id": thread_id,
            "topic": topic,
            "summary": summary,
            "path": str(path),
            "ts": time.time(),
        }

        def _append() -> None:
            index_file = self._settings.report_index_file
            index_file.parent.mkdir(exist_ok=True, parents=True)
            with index_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        async with self._lock:
            await asyncio.to_thread(_append)  # ★ 别在事件循环里做同步文件 IO

    async def list_reports(self, keyword: str | None = None, limit: int | None = None) -> list[dict]:
        limit = limit or self._settings.report_index_query_limit  # ★ 用上那个从没被读过的配置项

        index_file = self._settings.report_index_file
        if not index_file.exists():
            return []

        kw = keyword.lower().strip() if keyword else None

        def _read() -> list[dict]:
            result = []
            with index_file.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if kw:
                        # ★ 原来 topic 那边忘了 .lower()，大小写不一致时匹配不到
                        haystack = f"{entry.get('topic', '')} {entry.get('summary', '')}".lower()
                        if kw not in haystack:
                            continue
                    result.append(entry)
            return result

        async with self._lock:
            result = await asyncio.to_thread(_read)

        result.sort(key=lambda x: x.get("ts", 0), reverse=True)
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
