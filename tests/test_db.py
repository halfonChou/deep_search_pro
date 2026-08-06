"""数据库模块测试。

安全校验用例必过，真实数据库查询在无 DB 环境时 skip。
"""

import asyncmy
import pytest

from app.config import Settings
from app.infra.db import Database
from app.tools.sql_safety import assert_read_only, assert_table_allowed, enforce_limit

# =========================================================================
# Database 类基本行为
# =========================================================================

class TestDatabaseInit:

    def test_pool_is_none_before_connect(self) -> None:
        """构造后池子应为 None，不自动连接。"""
        settings = Settings(
            llm_model="test", llm_base_url="http://localhost",
            llm_api_key="test", mysql_password="test",
            mysql_database="test", tavily_api_key="test", embed_model="test",
        )
        db = Database(settings)
        assert db._pool is None

    @pytest.mark.asyncio
    async def test_connect_with_bad_host_raises(self) -> None:
        """连接不存在的数据库应抛异常。"""
        settings = Settings(
            llm_model="test", llm_base_url="http://localhost",
            llm_api_key="test", mysql_host="127.0.0.1", mysql_port=39999,
            mysql_password="test", mysql_database="test",
            tavily_api_key="test", embed_model="test",
        )
        db = Database(settings)
        # 连接不存在的 MySQL → asyncmy 抛 OperationalError（PEP 249 标准异常）
        with pytest.raises(asyncmy.errors.OperationalError):
            await db.connect()

    @pytest.mark.asyncio
    async def test_fetch_without_connect_raises(self) -> None:
        """未调用 connect 就 fetch 应抛 RuntimeError。"""
        settings = Settings(
            llm_model="test", llm_base_url="http://localhost",
            llm_api_key="test", mysql_password="test",
            mysql_database="test", tavily_api_key="test", embed_model="test",
        )
        db = Database(settings)
        with pytest.raises(RuntimeError, match="未初始化"):
            await db.fetch("SELECT 1")


# =========================================================================
# SQL 安全校验与工具构建（不依赖真实 DB）
# =========================================================================

class TestSqlToolsIntegration:

    def test_malicious_sql_blocked_by_safety(self) -> None:
        """恶意 SQL 被 assert_read_only 拦截。"""
        with pytest.raises(ValueError):
            assert_read_only("DROP TABLE users")

    def test_table_not_in_allowlist(self) -> None:
        """不在白名单的表被拦截。"""
        with pytest.raises(ValueError):
            assert_table_allowed("secrets", ["users", "orders"])

    def test_limit_auto_appended(self) -> None:
        """无 LIMIT 的 SELECT 自动加上。"""
        result = enforce_limit("SELECT * FROM users", 50)
        assert "LIMIT 50" in result

    def test_build_sql_tools_returns_four(self) -> None:
        """build_sql_tools 应返回四个工具（Day 6 新增 describe_table）。"""
        from unittest.mock import MagicMock

        from app.tools.sql_tools import build_sql_tools

        mock_db = MagicMock()
        settings = Settings(
            llm_model="test", llm_base_url="http://localhost",
            llm_api_key="test", mysql_password="test",
            mysql_database="test", tavily_api_key="test", embed_model="test",
        )
        tools = build_sql_tools(mock_db, settings)
        assert len(tools) == 4
