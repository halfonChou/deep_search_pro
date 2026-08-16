"""中间件栈集中装配（顺序只在这一处出现）。

装配顺序的三条依据（面试高频追问）：
1. before_* 正序、after_* 倒序、wrap_* 嵌套——第一个中间件包住所有后面的。
   所以观测放最外层，才能量到含重试在内的真实耗时。
2. SqlGuardMiddleware 必须在 ToolRetryMiddleware 外层。
   反过来的话，一条 DROP TABLE 会被重试 3 次才被拦。
3. BudgetMiddleware 在所有重试之前。预算已经耗尽时，重试只是继续烧钱。

Day 10 新增：
- SummarizationMiddleware：超过 token 阈值时 LLM 摘要压缩历史。
  ★★ 注意：deepagents 的默认栈里已经有一个 SummarizationMiddleware（第 5 位）。
  这里显式配置是为了覆盖默认参数，用我们自己的 trigger / keep / model 设置。
  如果默认参数够用，可以注释掉这一段，但保留代码以备自定义。
- ContextEditingMiddleware 的 exclude_tools=["write_todos"] 保证计划不被裁剪。
"""

from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    TodoListMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)

from app.agents.deps import AgentDeps
from app.infra.llm import build_chat_model, build_fallback_model
from app.middleware.budget import BudgetMiddleware
from app.middleware.observability import (
    CacheStatsMiddleware,
    EventEmitMiddleware,
    ToolRetryNotifyMiddleware,
)
from app.middleware.sql_guard import SqlGuardMiddleware


def build_middleware_stack(deps: AgentDeps):
    s = deps.settings
    return [
        # ---- 自研①：最外层，要观测到后面所有层的行为 ----
        EventEmitMiddleware(deps.bus),

        # ---- 自研⑤：打印 prompt 缓存命中率（诊断用，可随时注释掉）----
        CacheStatsMiddleware(),

        # ---- 自研③：预算超了直接 jump_to="end"，不浪费后面的重试 ----
        BudgetMiddleware(s),

        # ---- 内置：模型调用次数硬闸 ----
        ModelCallLimitMiddleware(
            run_limit=s.model_call_run_limit,
            thread_limit=s.model_call_thread_limit,
            exit_behavior="end",
        ),

        # ---- 内置：全局 + 分工具次数闸 ----
        ToolCallLimitMiddleware(
            run_limit=s.tool_call_run_limit,
            thread_limit=s.tool_call_thread_limit,
        ),
        ToolCallLimitMiddleware(
            tool_name="internet_search",
            run_limit=s.search_tool_run_limit,
        ),

        # ---- 自研②：SQL 拦截要在重试之前，非法 SQL 不该被重试 3 次 ----
        SqlGuardMiddleware(s),

        # ---- 内置：瞬时故障退避重试 ----
        ToolRetryMiddleware(
            max_retries=s.tool_retry_max,
            jitter=True,
            initial_delay=s.tool_retry_initial_delay,
            backoff_factor=s.tool_retry_backoff,
        ),
        ModelRetryMiddleware(max_retries=2),

        # ---- 自研④：装在重试内层，才看得见「第几次重试」。
        # 外层的 EventEmitMiddleware 只在重试耗尽后收到异常，推不出中间过程。
        ToolRetryNotifyMiddleware(deps.bus),

        # ---- 内置：主模型不可用时降级 ----
        *([ModelFallbackMiddleware(*build_fallback_model(s))]
          if s.fallback_models else []),

        # ---- 内置：TodoList 提供 write_todos → 任务规划 ----
        TodoListMiddleware(),

        # ---- Day 10：摘要中间件（trigger=60K < 裁剪 trigger=80K）----
        # 先摘要、后裁剪。摘要是有损但保语义的，裁剪是机械丢弃。
        # 给摘要先动手的机会，只有摘要之后还超才动裁剪。
        SummarizationMiddleware(
            model=build_chat_model(s, s.summarize_model or s.llm_model_cheap),
            trigger=("tokens", s.summarize_trigger_tokens),
            keep=("messages", s.summarize_keep_messages),
        ),

        # ---- Day 10：最内层，紧贴模型调用做 token 裁剪 ----
        # exclude_tools=["write_todos"]：计划绝不能被裁剪，否则 agent 忘记自己在干什么
        ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(
                trigger=s.context_edit_trigger_tokens,
                keep=s.context_edit_keep_recent,
                exclude_tools=["write_todos"],
            )],
        ),
    ]
