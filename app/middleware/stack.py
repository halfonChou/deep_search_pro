from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    TodoListMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)

from app.agents.deps import AgentDeps
from app.infra.llm import build_fallback_model
from app.middleware.budget import BudgetMiddleware
from app.middleware.observability import EventEmitMiddleware
from app.middleware.sql_guard import SqlGuardMiddleware


def build_middleware_stack(deps: AgentDeps):
    setting = deps.settings
    return [
        EventEmitMiddleware(deps.bus),
        BudgetMiddleware(setting),
        ModelCallLimitMiddleware(run_limit=setting.model_call_run_limit,
                                 thread_limit=setting.model_call_thread_limit,
                                 exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=setting.tool_call_run_limit,
                                thread_limit=setting.tool_call_thread_limit),
        ToolCallLimitMiddleware(tool_name="internet_search",
                                run_limit=setting.tool_call_run_limit,),
        SqlGuardMiddleware(setting),
        ToolRetryMiddleware(
            max_retries=setting.tool_retry_max,
            jitter=True,
            initial_delay=setting.tool_retry_initial_delay,
            backoff_factor=setting.tool_retry_backoff,
        ),
        ModelRetryMiddleware(max_retries=2),
        *([ModelFallbackMiddleware(*build_fallback_model(setting))]
            if setting.fallback_models else []),
        TodoListMiddleware(),
        ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(
                trigger=setting.context_edit_trigger_tokens,
                keep=setting.context_edit_keep_recent,
                exclude_tools=["write_todos"]
            )],
        ),
    ]
