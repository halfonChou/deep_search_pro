"""数据库查询子 Agent 工厂。

构建一个专注数据库查询的子 Agent，绑定 SQL 工具和专用提示词。
"""

from __future__ import annotations

import logging

from deepagents import CompiledSubAgent
from deepagents.middleware.filesystem import FilesystemState
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.agents.deps import AgentDeps
from app.infra.llm import build_chat_model
from app.prompt import sub_agent_prompts
from app.tools.schema_cache import load_schema
from app.tools.sql_safety import assert_read_only, assert_table_allowed, assess_sql_risk
from app.tools.sql_tools import build_sql_tools

logger = logging.getLogger(__name__)

MAX_SQL_ATTEMPTS = 3

# execute_sql_query 零结果时返回文案的开头，用来识别「SQL 合法但没查到东西」。
# ★ 必须和 sql_tools.execute_sql_query 里的措辞保持一致，改一处要改两处。
_ZERO_RESULT_MARK = "查询返回 0 行"


class DBQueryState(FilesystemState):
    schema_cache: dict[str, list[str]]
    pending_sql: str
    sql_attempts: int


def make_db_agent_node(deps: AgentDeps, tools:list):
    """
    db_agent：节点工厂
    节点函数接收当前state，返回一个增量
    """
    model = build_chat_model(deps.settings, deps.settings.llm_model_fast).bind_tools(tools)

    base_prompt = sub_agent_prompts()["database-query"]["system_prompt"]

    async def db_agent(state: DBQueryState):
        system = base_prompt
        if state.get("schema_cache"):
            cache_lines = [f"{t}:{','.join(cols)}" for t, cols in state["schema_cache"].items()]
            system = (
                base_prompt
                + "\n\n【已探测到的表结构】以下是当前数据库的真实结构，"
                  "**直接据此写 SQL，不要再调 list_sql_table / describe_table 探路**"
                  "（每探一次多花一轮模型往返）。只有 SQL 报「字段不存在」时才需要核对：\n"
                + "\n".join(cache_lines)
            )

        response = await model.ainvoke([{"role": "system", "content": system}, *state["messages"]])

        return {"messages": [response]}
    return db_agent


def make_load_schema_node(deps: AgentDeps):
    """入口节点：把表结构填进 state.schema_cache。

    ★ 关键：探测走的是普通 SQL（查 information_schema），毫秒级，
    **不消耗任何模型调用**。而让模型自己 list_sql_table → describe_table 去探，
    是两轮大模型往返、四五十秒。所以这一步是纯赚。

    结果由 schema_cache.load_schema 做三级缓存（内存 → 磁盘 → 真探测），
    第二次跑同一个库时连 SQL 都不用发。
    """
    async def load_schema_node(state: DBQueryState):
        if state.get("schema_cache"):
            return {}                      # 本轮已有，不重复
        cache = await load_schema(deps.db, deps.settings)
        return {"schema_cache": cache} if cache else {}
    return load_schema_node


def make_approval_node(deps: AgentDeps):
    """人工审批节点。

    ★ 这个节点必须保持「无副作用」：interrupt() 抛出后，用户审批完恢复执行时，
      LangGraph 会把这个节点**从头重跑一遍**。如果 interrupt() 之前有写库、
      发消息之类的动作，就会执行两次。
    """
    async def approve_sql(state: DBQueryState):
        last = state["messages"][-1]
        tool_call = last.tool_calls[0]

        # 把「为什么这条被拦下来」一并告诉人——审批卡片上只显示一句 SQL 时，
        # 人根本无从判断该不该批。给出理由，审批才不是走过场。
        reason = assess_sql_risk(tool_call["name"], tool_call["args"], deps.settings)

        # ★ 中断值的形状刻意和 deepagents 保持一致，
        #   这样 stream.py 的 _serialize_interrupt 和前端的审批卡片一行都不用改。
        payload = interrupt({
            "action_requests": [{
                "name": tool_call["name"],
                "args": tool_call["args"],
                "description": f"⚠️ {reason or '高风险操作'}。该 SQL 将直接在业务库上执行，请审批。",
            }],
            "review_configs": [{
                "action_name": tool_call["name"],
                "allowed_decisions": ["approve", "edit", "reject"],
            }],
        })

        # payload 就是 run_agent_stream 里 Command(resume=...) 传进来的东西，
        # 即 {"decisions": [{"type": "approve"}]}
        decisions = (payload or {}).get("decisions") or []
        decision = decisions[0] if decisions else {"type": "approve"}
        kind = decision.get("type", "approve")

        if kind == "reject":
            reason = decision.get("message") or "用户拒绝执行该 SQL"
            return {"messages": [ToolMessage(
                content=f"【人工拒绝】{reason}。\n"
                        f"请调整查询思路后重试，或改用 get_table_data 查看数据。",
                tool_call_id=tool_call["id"],
                status="error",
            )]}

        if kind == "edit":
            new_args = decision.get("args") or tool_call["args"]
            # ★ model_copy 保留原 message 的 id，add_messages 遇到同 id 会**覆盖**而不是追加，
            #   于是模型原来那条 tool_call 被人工改过的版本替换掉。
            patched = last.model_copy(update={
                "tool_calls": [{**tool_call, "args": new_args}, *last.tool_calls[1:]],
            })
            return {"messages": [patched]}

        return {}    # approve：什么都不改，原样放行到 db_tools

    return approve_sql


def route_after_approve(state: DBQueryState) -> str:
    """被拒 → 回模型重想；批准/改过 → 去执行。"""
    return "db_agent" if isinstance(state["messages"][-1], ToolMessage) else "db_tools"


def count_zero_result(state: DBQueryState):
    """工具执行完的记账节点：SQL 合法但查回 0 行，也算一次失败尝试。

    ★★ 为什么需要它（这是个真实踩过的坑）：
    原来 sql_attempts 只在 rewrite_sql 里 +1，也就是**只有 SQL 被安全检查拦下**
    才计数。而「SQL 完全合法、成功执行、就是查不到数据」这种情况计数器纹丝不动，
    于是 MAX_SQL_ATTEMPTS 这道闸形同虚设——模型可以换着姿势无限试探。

    实测过一次：连续 11 条合法 SQL 全部返回 0 行（原因是库里根本没有那个时间段的
    数据），模型从「换日期」试到「换药名」再到「探真实取值」，一直停不下来。
    真正兜住它的居然是 HITL 审批——每试一次都得人点一下确认。
    限流不该靠人肉点击来实现。
    """
    last = state["messages"][-1]
    if isinstance(last, ToolMessage) and _ZERO_RESULT_MARK in str(last.content):
        n = state.get("sql_attempts", 0) + 1
        logger.info("[db] SQL 零结果，累计尝试 %d/%d", n, MAX_SQL_ATTEMPTS)
        return {"sql_attempts": n}
    return {}


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
            AIMessage(
                content=(
                    f"已尝试 {MAX_SQL_ATTEMPTS} 次仍未取到数据，停止试探。\n"
                    f"可能的原因（按可能性排序）：\n"
                    f"1. 库里确实没有这个条件下的数据——比如查询的时间区间超出了数据覆盖范围；\n"
                    f"2. 中文字段的实际写法和预期不一致（如「布洛芬」在库里存的是「布洛芬缓释胶囊」）；\n"
                    f"3. 关联字段对不上。\n"
                    f"请把以上情况如实汇报给上级，**不要编造数据**，"
                    f"并说明已经排除了哪些可能。"
                )
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
        if state.get("sql_attempts", 0) >= MAX_SQL_ATTEMPTS:   # 顺手把 > 改成 >=
            return "give_up"

        tool_call = last.tool_calls[0]
        name = tool_call["name"]

        # 先过安全闸：非法 SQL 连审批的资格都没有，直接打回改写。
        # 顺序很重要——不然用户得对着一条 DROP TABLE 点批准还是拒绝。
        if _is_sql_tool(name) and not _precheck_ok(tool_call, deps):
            return "rewrite_sql"

        # ★ 只有「高风险」的 SQL 才走人工审批，不是每条都拦。
        #   理由见 sql_safety.assess_sql_risk 的注释：审批太密 = 审批疲劳 = 等于没有审批。
        if deps.settings.hitl_enabled and name in deps.settings.hitl_interrupt_tools:
            if assess_sql_risk(name, tool_call["args"], deps.settings) is not None:
                return "approve_sql"

        return "db_tools"
    return route_after_db_agent


def build_database_subagent(deps: AgentDeps):
    tools = build_sql_tools(deps.db, deps.settings)

    g = StateGraph(DBQueryState)
    g.add_node("load_schema", make_load_schema_node(deps))
    g.add_node("db_agent", make_db_agent_node(deps, tools))
    g.add_node("approve_sql", make_approval_node(deps))     # ★ 新增
    g.add_node("db_tools", ToolNode(tools))
    g.add_node("count_result", count_zero_result)           # ★ 新增：零结果记账
    g.add_node("rewrite_sql", make_rewrite_node(deps))
    g.add_node("give_up", give_up_node)

    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "db_agent")
    g.add_conditional_edges(
        "db_agent", make_router(deps),
        {"db_tools": "db_tools", "rewrite_sql": "rewrite_sql",
         "approve_sql": "approve_sql",                       # ★ 新增
         "give_up": "give_up", END: END},
    )
    g.add_conditional_edges(                                 # ★ 新增
        "approve_sql", route_after_approve,
        {"db_tools": "db_tools", "db_agent": "db_agent"},
    )
    # ★ 工具执行完先经过记账节点，再回模型：
    #   db_tools → count_result → db_agent
    g.add_edge("db_tools", "count_result")
    g.add_edge("count_result", "db_agent")
    g.add_edge("rewrite_sql", "db_agent")
    g.add_edge("give_up", END)

    return CompiledSubAgent(
        name="database-query",
        description=sub_agent_prompts()["database-query"]["description"],
        runnable=g.compile(),
    )
