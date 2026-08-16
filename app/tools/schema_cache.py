"""表结构探测 + 缓存。

为什么要有这个东西：
写 SQL 之前必须知道有哪些表、哪些字段。让模型自己去探（list_sql_table →
describe_table → execute_sql_query）意味着**三轮模型往返**，一轮二三十秒，
光探路就烧掉一分钟。

但也不能把表结构硬写进 prompt——那等于给模型喂答案，而且改了表结构 prompt 就在骗人。

正确做法：**探测一次，存下来，之后复用**。
- 探测本身是一条普通 SQL（查 information_schema），毫秒级，不花模型调用
- 结果写到 data/schema_cache.json，进程重启也还在
- 有缓存就直接用，过期或表结构变了才重新探

关键点：这不是"省一次 SQL"，而是"省两次大模型往返"。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from app.config import Settings
from app.infra.db import Database

logger = logging.getLogger(__name__)

# 缓存有效期。表结构不常变，一天探一次足够。
CACHE_TTL_SECONDS = 24 * 3600

# 进程内缓存：同一次运行里多个子 Agent 调用不用反复读文件
_MEMORY_CACHE: dict[str, list[str]] | None = None
_MEMORY_CACHE_TS: float = 0.0

_PROBE_SQL = """
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME, ORDINAL_POSITION
"""


def _cache_file(settings: Settings) -> Path:
    return settings.data_dir / "schema_cache.json"


def _read_disk_cache(settings: Settings) -> dict[str, list[str]] | None:
    path = _cache_file(settings)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("[schema] 缓存文件损坏，将重新探测: %s", path)
        return None

    if payload.get("database") != settings.mysql_database:
        logger.info("[schema] 缓存属于别的库（%s），重新探测", payload.get("database"))
        return None

    age = time.time() - float(payload.get("ts", 0))
    if age > CACHE_TTL_SECONDS:
        logger.info("[schema] 缓存已过期（%.1f 小时），重新探测", age / 3600)
        return None

    tables = payload.get("tables")
    if not isinstance(tables, dict) or not tables:
        return None

    logger.info("[schema] 命中磁盘缓存，%d 张表，年龄 %.1f 小时", len(tables), age / 3600)
    return tables


def _write_disk_cache(settings: Settings, tables: dict[str, list[str]]) -> None:
    path = _cache_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": time.time(),
        "database": settings.mysql_database,
        "tables": tables,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[schema] 已写入缓存 %s（%d 张表）", path, len(tables))


async def probe_schema(db: Database, settings: Settings) -> dict[str, list[str]]:
    """一条 SQL 拿全部表结构。返回 {表名: ["列名 类型 注释", ...]}。"""
    _, rows = await db.fetch(_PROBE_SQL)

    allowlist = set(settings.sql_table_allowlist or [])
    tables: dict[str, list[str]] = {}

    for table_name, column_name, column_type, comment in rows:
        # 白名单非空时只暴露白名单内的表——模型看不到的表就不会去查，
        # 省掉一轮"被 SqlGuard 拦下再改写"的往返
        if allowlist and table_name not in allowlist:
            continue
        desc = f"{column_name} {column_type}"
        if comment:
            desc += f"（{comment}）"
        tables.setdefault(table_name, []).append(desc)

    logger.info("[schema] 探测完成，%d 张表", len(tables))
    return tables


async def load_schema(
    db: Database | None,
    settings: Settings,
    refresh: bool = False,
) -> dict[str, list[str]]:
    """取表结构：内存缓存 → 磁盘缓存 → 真去探测。

    任何一步失败都返回空字典，让模型退回自己用 describe_table 探——
    降级而不是报错。
    """
    global _MEMORY_CACHE, _MEMORY_CACHE_TS

    if db is None:
        logger.warning("[schema] 数据库未连接，跳过探测")
        return {}

    if not refresh:
        if _MEMORY_CACHE and time.time() - _MEMORY_CACHE_TS < CACHE_TTL_SECONDS:
            return _MEMORY_CACHE
        if (disk := _read_disk_cache(settings)) is not None:
            _MEMORY_CACHE, _MEMORY_CACHE_TS = disk, time.time()
            return disk

    try:
        tables = await probe_schema(db, settings)
    except Exception:
        logger.exception("[schema] 探测失败，模型将退回手工 describe_table")
        return {}

    if not tables:
        return {}

    _MEMORY_CACHE, _MEMORY_CACHE_TS = tables, time.time()
    try:
        _write_disk_cache(settings, tables)
    except OSError:
        logger.warning("[schema] 缓存写盘失败，本次仅用内存缓存")
    return tables
