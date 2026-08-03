from app.agents.deps import AgentDeps
from app.infra.llm import build_chat_model
from app.prompt import main_agent_prompt
from deepagents import create_deep_agent
from app.agents.context import RunContext
from app.tools.doc_tools import build_doc_tools
from app.tools.search_tools import build_search_tools

def build_main_agent(deps: AgentDeps, checkpointer=None):
    return create_deep_agent(
        model=build_chat_model(deps.settings),
        tools=[],
        system_prompt=main_agent_prompt(),
        subagents=[],
        middleware=[],
        context_schema=RunContext,
        checkpointer=checkpointer,
    )