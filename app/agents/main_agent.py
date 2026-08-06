from deepagents import create_deep_agent

from app.agents.context import RunContext
from app.agents.deps import AgentDeps
from app.agents.subagents.database_query import build_database_subagent
from app.agents.subagents.knowledge_base import build_knowledge_base_agent
from app.agents.subagents.network_search import build_network_search_agent
from app.infra.llm import build_chat_model
from app.middleware.stack import build_middleware_stack
from app.prompt import main_agent_prompt


def build_main_agent(deps: AgentDeps, checkpointer=None):
    """构建主 Agent，挂上子 Agent（任务规划与委托，Day 5）。

    主 Agent 是"项目经理"：收到任务先 write_todos 规划，
    再按 description 决定把活派给哪个子 Agent。
    """
    subagents = [
        build_network_search_agent(deps),
        build_knowledge_base_agent(deps),
        build_database_subagent(deps),
    ]
    return create_deep_agent(
        model=build_chat_model(deps.settings),
        tools=[],
        system_prompt=main_agent_prompt(),
        subagents=subagents,
        middleware=build_middleware_stack(deps),
        context_schema=RunContext,
        checkpointer=checkpointer,
    )
