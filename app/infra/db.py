"""异步 MySQL 连接池。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncmy

from app.config import Settings

logger = logging.getLogger(__name__)


class Database:

    def __init__(self, settings: Settings):
        self._settings = settings
        self._pool: asyncmy.Pool | None= None
        pass

    async def connect(self) -> None:
        if self._pool is not None:
            return
        s = self._settings
        self._pool = await asyncmy.create_pool(
            host = s.mysql_host,
            port = s.mysql_port,
            user = s.mysql_user,
            password = s.mysql_password,
            db=s.mysql_database,
            minsize=s.mysql_pool_min,
            maxsize=s.mysql_pool_max,
            charset = "utf8mb4",
            autocommit=True,
            connect_timeout=10,
        )
        logging.info(
            "MySQL 连接池已建立: %s:%s/%s (min=%d, max=%d)",
            s.mysql_host, s.mysql_port, s.mysql_database,
            s.mysql_pool_min, s.mysql_pool_max,)

    async def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
            logger.info("数据库连接池已关闭！！！")

    async def fetch(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        timeout: float = 30.0,
    ) -> tuple[list[str], list[tuple]]:
        if self._pool is None:
            raise RuntimeError("数据库连接池未初始化，请调用connect进行初始化操作")

        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await asyncio.wait_for(
                        cur.execute(sql, params),
                        timeout=timeout,
                    )
                    if cur.description is None:
                        return [],[]
                    columns = [c[0] for c in cur.description ]
                    rows = await cur.fetchall()
                    return columns, list(rows)
        except TimeoutError as e:
            raise TimeoutError(f"查询超时（{timeout}s）: {sql[:100]}") from e
        except Exception as e:
            logger.error("数据库查询失败: %s | SQL: %s", e, sql[:200])
            raise
