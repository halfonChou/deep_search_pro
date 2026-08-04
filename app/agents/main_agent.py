from deepagents import create_deep_agent

from app.agents.context import RunContext
from app.agents.deps import AgentDeps
from app.infra.llm import build_chat_model
from app.middleware.stack import build_middleware_stack
from app.prompt import main_agent_prompt


def build_main_agent(deps: AgentDeps, checkpointer=None):
    return create_deep_agent(
        model=build_chat_model(deps.settings),
        tools=[],
        system_prompt=main_agent_prompt(),
        subagents=[],
        middleware=build_middleware_stack(deps),
        context_schema=RunContext,
        checkpointer=checkpointer,
    )
