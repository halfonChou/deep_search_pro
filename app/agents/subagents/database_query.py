"""数据库查询子 Agent 工厂。

构建一个专注数据库查询的子 Agent，绑定 SQL 工具和专用提示词。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, TypedDict

from deepagents import CompiledSubAgent
from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.agents.deps import AgentDeps
from app.infra.llm import build_chat_model
from app.prompt import sub_agent_prompts
from app.tools.sql_safety import assert_read_only, assert_table_allowed
from app.tools.sql_tools import build_sql_tools

MAX_SQL_ATTEMPTS = 3


class DBQueryState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    schema_cache: dict[str, list[str]]
    pending_sql: str
    sql_attempts: int


def make_db_agent_node(deps: AgentDeps, tools:list):
    """
    db_agent：节点工厂
    节点函数接收当前state，返回一个增量
    """
    model = build_chat_model(deps.settings).bind_tools(tools)

    base_prompt = sub_agent_prompts()["database_query"]["system_prompt"]

    async def db_agent(state: DBQueryState):
        system = base_prompt
        if state.get("schema_cache"):
            cache_lines = [f"{t}:{','.join(cols)}" for t, cols in state["schema_cache"].items()]
            system = base_prompt + "\n\n已知表结构，无需重复查询：\n" + "\n".join(cache_lines)

        response = await model.ainvoke([{"role": "system", "content": system}, *state["messages"]])

        return {"messages": [response]}
    return db_agent


def make_rewrite_node(deps: AgentDeps):
    """rewrite_sql 节点工厂，把校验错误原因反馈给我模型人模型写好"""
    async def rewrite_sql(state: DBQueryState):
        last = state["messages"][-1]
        tool_call = last.tool_calls[0]
        name,args = tool_call["name"],tool_call["args"]

        try:
            if name == "execute_sql_query":
                assert_read_only(args["query"])
                error = "未知原因"
            else:
                assert_table_allowed(args["table_name"], deps.settings.sql_table_allowlist)
                error = "未知原因"
        except ValueError as e:
            error = str(e)

        feedback = ToolMessage(
            content=f"【SQL 安全拦截】{error}，请改写 SQL 后重试。",
            tool_call_id=tool_call["id"],
            status="error"
        )
        return {"messages": [feedback], "sql_attempts": state.get("sql_attempts", 0) + 1}
    return rewrite_sql


def give_up_node(state: DBQueryState):
    return {
        "messages": [
            BaseMessage(
                content=f"经过 {MAX_SQL_ATTEMPTS} 次尝试，仍无法构建合法SQL，已放弃！\n请检查表名或者改用 get_table_data 查看数据",
                role="assistant",
            )
        ]
    }


def _is_sql_tool(name:str):
    return name in {"execute_sql_query", "get_table_data", "describe_table"}


def _precheck_ok(tool_call, deps: AgentDeps) -> bool:
    name, args = tool_call["name"], tool_call["args"]
    try:
        if name == "execute_sql_query":
            assert_read_only(args["query"])
        else:
            assert_table_allowed(args["table_name"], deps.settings.sql_table_allowlist)
        return True
    except (ValueError, KeyError):
        return False


def make_router(deps: AgentDeps):
    def route_after_db_agent(state: DBQueryState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        if state.get("sql_attempts", 0) > MAX_SQL_ATTEMPTS:
            return "give_up"
        tool_call = last.tool_calls[0]
        name = tool_call["name"]
        if _is_sql_tool(name) and not _precheck_ok(tool_call, deps):
            return "rewrite_sql"
        return "db_tools"
    return route_after_db_agent


def build_database_subagent(deps: AgentDeps):
    tools = build_sql_tools(deps.db, deps.settings)

    g = StateGraph(DBQueryState)
    g.add_node("db_agent", make_db_agent_node(deps, tools))
    g.add_node("db_tools", ToolNode(tools))
    g.add_node("rewrite_sql", make_rewrite_node(deps))
    g.add_node("give_up", give_up_node)

    g.add_edge(START, "db_agent")
    g.add_conditional_edges(
        "db_agent", make_router(deps),
        {"db_tools": "db_tools", "rewrite_sql": "rewrite_sql",
         "give_up": "give_up", END: END},
    )
    g.add_edge("db_tools", "db_agent")
    g.add_edge("rewrite_sql", "db_agent")
    g.add_edge("give_up", END)

    return CompiledSubAgent(
        name="database-query",
        description=sub_agent_prompts()["database_query"]["description"],
        runnable=g.compile(),   # checkpointer 由父图提供，子图不单独编译
    )
