"""主 Agent 构建工厂。

构建主 Agent，挂上子 Agent（任务规划与委托）。
主 Agent 是"项目经理"：收到任务先 write_todos 规划，
再按 description 决定把活派给哪个子 Agent。

Day 10 更新：加入 report_tools（list_past_reports），
让主 Agent 能查历史报告避免重复调研。
"""

from deepagents import create_deep_agent

from app.agents.context import RunContext
from app.agents.deps import AgentDeps
from app.agents.subagents.database_query import build_database_subagent
from app.agents.subagents.knowledge_base import build_knowledge_base_agent
from app.agents.subagents.network_search import build_network_search_agent
from app.infra.llm import build_chat_model
from app.middleware.stack import build_middleware_stack
from app.prompt import main_agent_prompt
from app.tools.doc_tools import build_doc_tools
from app.tools.report_tools import build_report_tools


def build_main_agent(deps: AgentDeps, checkpointer=None):
    """构建主 Agent 单例。

    注意：这是单例——整个应用只建一次，挂在 app.state.agent 上。
    per-request 的 thread_id / session_dir 通过 invoke 时的 context= 传入，
    不再通过闭包捕获。这是 Day 1 引入 RunContext 的原因。
    """
    subagents = [
        build_network_search_agent(deps),
        build_knowledge_base_agent(deps),
        build_database_subagent(deps),
    ]

    # Day 10：report_tools 需要 SessionService，但构建时还没有。
    # 这里通过延迟导入 + 惰性获取解决：report_tools 内部调 sessions.list_reports()，
    # sessions 实例在 lifespan 里才创建。我们在 main.py 里确保 sessions 先于 agent 创建。
    tools = build_doc_tools(deps.sessions) if deps.sessions is not None else []
    if deps.sessions is not None:
        tools += build_report_tools(deps.sessions)

    return create_deep_agent(
        model=build_chat_model(deps.settings),
        tools=tools,
        system_prompt=main_agent_prompt(),
        subagents=subagents,
        middleware=build_middleware_stack(deps),
        context_schema=RunContext,
        checkpointer=checkpointer,
    )
