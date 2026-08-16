"""Day 6 数据库子图单测：状态流转 / 改写循环 / 上限退出。"""
from unittest.mock import MagicMock

from langgraph.graph import END

from app.agents.subagents.database_query import (
    MAX_SQL_ATTEMPTS,
    _is_sql_tool,
    _precheck_ok,
    build_database_subagent,
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


# ===== 分支 4：低风险 SQL → db_tools（不经审批直接执行）=====
def test_route_runs_tools_for_low_risk_sql():
    """列名明确 + 带 WHERE 的查询是低风险，assess_sql_risk 返回 None，直接放行。

    ★ 原用例用的是 `SELECT * FROM drugs`，现在会被 assess_sql_risk 判为高风险
      （"使用了 SELECT *，会返回全部列"）而路由到 approve_sql —— 那是**正确行为**，
      不是 bug。所以这里换成一条真正低风险的 SQL 来测 db_tools 这条分支。
    """
    router = make_router(_make_deps())
    state = _make_state([
        FakeAIMessage(tool_calls=[
            {"name": "execute_sql_query", "args": {"query": "SELECT name FROM drugs WHERE id = 1"}},
        ]),
    ])
    assert router(state) == "db_tools"


# ===== 分支 5：高风险 SQL → approve_sql（人工审批）=====
def test_route_requires_approval_for_select_star():
    """SELECT * 属于高风险，必须停在审批点，不能直接执行。"""
    router = make_router(_make_deps())
    state = _make_state([
        FakeAIMessage(tool_calls=[{"name": "execute_sql_query", "args": {"query": "SELECT * FROM drugs"}}]),
    ])
    assert router(state) == "approve_sql"


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

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.types import Command

    async def test_sql_requires_approval(deps_with_fake_model):
        """★ 防回归：execute_sql_query 必须停在审批点，不能直接执行。"""
        sub = build_database_subagent(deps_with_fake_model)
        graph = sub.runnable.copy(update={"checkpointer": MemorySaver()})
        config = {"configurable": {"thread_id": "hitl-1"}}

        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": "查销售记录"}]}, config
        )

        # 1. 停在中断上了，没跑完
        assert "__interrupt__" in result

        # 2. 中断值的形状对，前端能渲染
        value = result["__interrupt__"][0].value
        assert value["action_requests"][0]["name"] == "execute_sql_query"

        # 3. 批准后能继续执行
        final = await graph.ainvoke(
            Command(resume={"decisions": [{"type": "approve"}]}), config
        )
        assert final["messages"][-1].content
