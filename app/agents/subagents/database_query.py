"""数据库查询子 Agent 工厂。

构建一个专注数据库查询的子 Agent，绑定 SQL 工具和专用提示词。
"""

from __future__ import annotations

from app.agents.main_agent import AgentDeps
from app.infra.llm import build_chat_model
from app.prompt import sub_agent_prompts
from app.tools.sql_tools import build_sql_tools


def build_database_agent(deps: AgentDeps):
    """构建数据库查询子 Agent。

    Args:
        deps: 统一依赖容器，包含 settings、emitter、db 等。

    Returns:
        可调用的 Agent（具体类型取决于你用 LangGraph 还是 LangChain）。
    """
    # 用 deps 里的配置构建 LLM
    model = build_chat_model(deps.settings)

    # 用 deps 里的 db、emitter、settings 构建 SQL 工具
    tools = build_sql_tools(
        db=deps.db,
        settings=deps.settings,
    )

    # 加载数据库子 Agent 的专用提示词
    prompts = sub_agent_prompts()
    system_prompt = prompts.get("database_query", "你是一个数据库查询助手。")

    # 把 LLM 和工具绑定
    agent = model.bind_tools(tools)

    return {
        "agent": agent,
        "system_prompt": system_prompt,
        "tools": tools,
    }
