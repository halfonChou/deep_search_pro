from __future__ import annotations

import logging
import re

from app.config import Settings

logger = logging.getLogger(__name__)

_FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "RENAME", "REPLACE", "MERGE",
    "CALL", "EXEC", "EXECUTE", "LOAD",
})

_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "INTO OUTFILE",
    "INTO DUMPFILE"
)

# 匹配 SQL 行注释 (-- ...) 和块注释 (/* ... */)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

# 匹配字符串字面量（单引号），检测前剥离，防止字符串内关键字误报
_STRING_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'")

# 匹配已有的 LIMIT 子句
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)

# 合法表名：字母/数字/下划线，可选反引号包裹
_TABLE_NAME_RE = re.compile(r"^`?[a-zA-Z_][a-zA-Z0-9_]*`?$")

def _strip_comments(sql: str) -> str:
    sql = _BLOCK_COMMENT_RE.sub(' ', sql)
    sql = _LINE_COMMENT_RE.sub(' ', sql)
    return sql

def _strip_strings(sql: str) -> str:
    return _STRING_LITERAL_RE.sub('', sql)

def assert_read_only(sql: str) -> None:
    if not sql or not sql.split():
        raise ValueError("SQL 语句不能为空")

    # 清理后的sql
    clean = _strip_comments(sql)

    stripped = clean.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ValueError("禁止多语句执行，（检测到分号）")

    first_word = stripped.split()[0].upper() if stripped.split() else ""
    allowed_starts = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}
    if first_word not in allowed_starts:
        raise ValueError(f"仅允许只读，不允许以 ‘{first_word}’ 开头的语句")

    no_strings = _strip_strings(stripped).upper()
    tokens = set(re.findall(r"\b[A-Z_]+\b", no_strings))

    for kw in _FORBIDDEN_KEYWORDS:
        if kw in tokens:
            raise ValueError(f"检测到禁止的关键字：{kw}")

    for phrase in _FORBIDDEN_PHRASES:
        if phrase in no_strings:
            raise ValueError(f"检测到禁止的关键字：{phrase}")

def assert_table_allowed(name:str, allowlist:list[str]) -> None:
    clean_name = name.strip().strip("`")
    if not clean_name or not _TABLE_NAME_RE.match(clean_name):
        raise ValueError(f"非法表名：{name}")

    if not allowlist:
        return

    if clean_name not in allowlist and name not in allowlist:
        raise ValueError(f"表 '{clean_name}' 不在允许访问的列表中")

def enforce_limit(sql: str, row_limit:int = 100) -> str:
    stripped = sql.strip().rstrip(";").strip()
    if not _LIMIT_RE.search(stripped):
        stripped = f"{stripped} LIMIT {row_limit}"
    return stripped


# ============================================================
# 统一的 SQL 调用检查入口
#
# 为什么要有这一层，而不是让调用方各自去调三个 assert_*：
#   1. 三个 assert_* 是"抛异常"风格，调用方要写 try/except 才能用；
#      而"判断 + 拿理由"是最常见的需求，抛异常风格逼着调用方跑两遍
#   2. 这里一次返回"理由或 None"，判断和理由同时拿到，不可能不一致。
#   3. 顺带做参数规范化（补 LIMIT），这是 assert_* 做不到的事。
# ============================================================

SQL_TOOLS: frozenset[str] = frozenset({
    "execute_sql_query",
    "get_table_data",
    "describe_table",
})

def check_sql_call(name:str, args:dict, setting: Settings):
    if name not in SQL_TOOLS:
        return None

    try:
        if name == "execute_sql_query":
            query = args.get("query")
            if not isinstance(query, str) or not query.strip():
                return "缺少有效的 query 参数 (应为非空字符串)"
            assert_read_only(query)

            args["query"] = enforce_limit(query, setting.sql_row_limit)

        else:
            table = args.get("table_name")
            if not isinstance(table, str) or not table.strip():
                return "缺少有效的 table_name 参数(应为非空字符串)"
            assert_table_allowed(table, setting.sql_table_allowlist)

    except ValueError as e:
        return str(e)

    except Exception as e:
        logger.exception("SQL 校验器内部异常，已按拒绝处理： tool=%s",name)
        return f"校验器内部异常，已按拒绝处理：{type(e).__name__}"
    return None
