from app.agents.deps import AgentDeps
from app.middleware.observability import EventEmitMiddleware


def build_middleware_stack(deps: AgentDeps):
    return [
        EventEmitMiddleware(deps.bus),
    ]
