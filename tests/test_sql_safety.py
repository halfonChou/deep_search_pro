"""SQL 安全校验模块测试。

覆盖：只读校验、危险关键字、多语句、注释绕过、白名单、自动 LIMIT。
"""

import pytest

from app.tools.sql_safety import assert_read_only, assert_table_allowed, enforce_limit


# =========================================================================
# assert_read_only — 合法语句
# =========================================================================

class TestAssertReadOnlyPass:
    """应当通过的只读语句。"""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM users",
        "SELECT id, name FROM users WHERE age > 18",
        "select count(*) from orders",                    # 小写
        "SHOW TABLES",
        "DESCRIBE users",
        "DESC users",
        "EXPLAIN SELECT * FROM users",
        "WITH cte AS (SELECT 1) SELECT * FROM cte",
        "SELECT * FROM users;",                           # 尾部单分号允许
        "SELECT * FROM update_log",                       # 表名含 update 不误报
        "SELECT * FROM users WHERE name = 'DROP TABLE'",  # 字符串内关键字不误报
    ])
    def test_valid_queries(self, sql: str) -> None:
        assert_read_only(sql)  # 不抛异常即通过


# =========================================================================
# assert_read_only — 拦截
# =========================================================================

class TestAssertReadOnlyBlock:
    """应当被拦截的危险语句。"""

    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            assert_read_only("")

    def test_whitespace_only(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            assert_read_only("   ")

    @pytest.mark.parametrize("sql", [
        "DROP TABLE users",
        "DELETE FROM users WHERE 1=1",
        "UPDATE users SET admin=1",
        "INSERT INTO users VALUES (1,'hack')",
        "ALTER TABLE users ADD COLUMN pwned INT",
        "TRUNCATE TABLE users",
        "CREATE TABLE evil (id INT)",
        "GRANT ALL ON *.* TO 'hacker'",
        "REVOKE ALL ON *.* FROM 'admin'",
    ])
    def test_forbidden_statements(self, sql: str) -> None:
        with pytest.raises(ValueError):
            assert_read_only(sql)

    def test_multi_statement_semicolon(self) -> None:
        with pytest.raises(ValueError, match="多语句"):
            assert_read_only("SELECT 1; DROP TABLE users")

    def test_comment_bypass_line(self) -> None:
        """行注释内藏 SELECT，真实语句是 DROP。"""
        with pytest.raises(ValueError):
            assert_read_only("-- SELECT 1\nDROP TABLE users")

    def test_comment_bypass_block(self) -> None:
        """块注释包裹 SELECT，真实语句是 DELETE。"""
        with pytest.raises(ValueError):
            assert_read_only("/* SELECT */ DELETE FROM users")

    def test_into_outfile(self) -> None:
        with pytest.raises(ValueError, match="INTO OUTFILE"):
            assert_read_only("SELECT * FROM users INTO OUTFILE '/tmp/data.csv'")

    def test_into_dumpfile(self) -> None:
        with pytest.raises(ValueError, match="INTO DUMPFILE"):
            assert_read_only("SELECT 0x41 INTO DUMPFILE '/tmp/shell.php'")

    def test_union_based_injection_with_drop(self) -> None:
        """UNION 注入尝试夹带 DROP。"""
        with pytest.raises(ValueError, match="多语句"):
            assert_read_only("SELECT * FROM users UNION SELECT 1; DROP TABLE users")

    def test_select_with_subquery_delete(self) -> None:
        """子查询里藏 DELETE — 虽然语法不合法，但安全层应拦截。"""
        with pytest.raises(ValueError):
            assert_read_only("SELECT * FROM (DELETE FROM users) AS t")


# =========================================================================
# assert_table_allowed
# =========================================================================

class TestAssertTableAllowed:

    def test_allowed(self) -> None:
        assert_table_allowed("users", ["users", "orders"])

    def test_allowed_with_backticks(self) -> None:
        assert_table_allowed("`users`", ["users", "orders"])

    def test_not_allowed(self) -> None:
        with pytest.raises(ValueError, match="不在允许访问的列表中"):
            assert_table_allowed("secrets", ["users", "orders"])

    def test_empty_allowlist_permits_all(self) -> None:
        assert_table_allowed("any_table", [])  # 不抛异常

    def test_invalid_table_name_injection(self) -> None:
        with pytest.raises(ValueError, match="非法表名"):
            assert_table_allowed("users; DROP TABLE users", ["users"])

    def test_invalid_table_name_spaces(self) -> None:
        with pytest.raises(ValueError, match="非法表名"):
            assert_table_allowed("users orders", ["users"])

    def test_invalid_table_name_slash(self) -> None:
        with pytest.raises(ValueError, match="非法表名"):
            assert_table_allowed("../../etc/passwd", [])

    def test_empty_name(self) -> None:
        with pytest.raises(ValueError, match="非法表名"):
            assert_table_allowed("", ["users"])


# =========================================================================
# enforce_limit
# =========================================================================

class TestEnforceLimit:

    def test_adds_limit_when_missing(self) -> None:
        result = enforce_limit("SELECT * FROM users")
        assert result == "SELECT * FROM users LIMIT 100"

    def test_custom_limit(self) -> None:
        result = enforce_limit("SELECT * FROM users", row_limit=50)
        assert result == "SELECT * FROM users LIMIT 50"

    def test_preserves_existing_limit(self) -> None:
        result = enforce_limit("SELECT * FROM users LIMIT 10")
        assert "LIMIT 10" in result
        assert result.count("LIMIT") == 1

    def test_strips_trailing_semicolon(self) -> None:
        result = enforce_limit("SELECT * FROM users;")
        assert result == "SELECT * FROM users LIMIT 100"

    def test_case_insensitive_limit_detection(self) -> None:
        result = enforce_limit("SELECT * FROM users limit 20")
        assert result.count("limit") + result.count("LIMIT") == 1
