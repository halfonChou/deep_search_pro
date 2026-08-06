"""Day 6 数据库子图单测：状态流转 / 改写循环 / 上限退出。"""
from unittest.mock import MagicMock

from langgraph.graph import END

from app.agents.subagents.database_query import (
    MAX_SQL_ATTEMPTS,
    _is_sql_tool,
    _precheck_ok,
    make_router,
)


class FakeAIMessage:
    """模拟带 tool_calls 的 AIMessage，避免依赖 langchain_core。"""

    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls


class FakeToolMessage:
    """模拟 ToolMessage（无 tool_calls 属性）。"""


def _make_state(messages, sql_attempts=0):
    return {"messages": messages, "schema_cache": {}, "pending_sql": "", "sql_attempts": sql_attempts}


def _make_deps():
    """构造一个最小 AgentDeps，settings 里带 sql_table_allowlist。"""
    from app.agents.deps import AgentDeps
    from app.config import Settings

    settings = Settings(
        llm_model="test", llm_base_url="http://localhost",
        llm_api_key="test", mysql_password="test",
        mysql_database="test", tavily_api_key="test", embed_model="test",
    )
    return AgentDeps(settings=settings, bus=MagicMock(), db=MagicMock())


# ===== 分支 1：无 tool_call → END =====
def test_route_ends_when_no_tool_call():
    router = make_router(_make_deps())
    state = _make_state([FakeToolMessage()])   # 最后一条消息没有 tool_calls
    assert router(state) == END  # END 是 langgraph 常量，实际值 "__end__"


# ===== 分支 2：改写超限 → give_up =====
def test_route_gives_up_when_attempts_exceeded():
    router = make_router(_make_deps())
    # sql_attempts 超过 MAX_SQL_ATTEMPTS，即使有 tool_call 也 give_up
    state = _make_state(
        [FakeAIMessage(tool_calls=[{"name": "execute_sql_query", "args": {}}])],
        sql_attempts=MAX_SQL_ATTEMPTS + 1,
    )
    assert router(state) == "give_up"  # ← 你应该断言这个值


# ===== 分支 3：SQL 校验失败 → rewrite_sql =====
def test_route_rewrites_bad_sql():
    router = make_router(_make_deps())
    state = _make_state([
        FakeAIMessage(tool_calls=[{"name": "execute_sql_query", "args": {"query": "DROP TABLE drugs"}}]),
    ])
    assert router(state) == "rewrite_sql"  # ← 你应该断言这个值


# ===== 分支 4：正常 → db_tools =====
def test_route_runs_tools_for_good_sql():
    router = make_router(_make_deps())
    state = _make_state([
        FakeAIMessage(tool_calls=[{"name": "execute_sql_query", "args": {"query": "SELECT * FROM drugs"}}]),
    ])
    assert router(state) == "db_tools"  # ← 你应该断言这个值


# ===== 辅助函数：_is_sql_tool =====
def test_is_sql_tool():
    assert _is_sql_tool("execute_sql_query")
    assert _is_sql_tool("get_table_data")
    assert _is_sql_tool("describe_table")
    assert not _is_sql_tool("internet_search")  # ← 你应该断言这个值


# ===== 辅助函数：_precheck_ok =====
def test_precheck_rejects_forbidden_sql():
    deps = _make_deps()
    assert not _precheck_ok({"name": "execute_sql_query", "args": {"query": "DROP TABLE x"}}, deps)  # ← 断言 False
    assert _precheck_ok({"name": "execute_sql_query", "args": {"query": "SELECT * FROM x"}}, deps)  # ← 断言 True
