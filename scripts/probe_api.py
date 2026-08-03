# scripts/probe_api.py —— Day 1 第一件事：探测真实 API 签名
# 版本漂移是这类项目最大的坑，先探测再写代码，后续 10 天都对照这份输出
import inspect

import deepagents
import langchain
import langgraph

from deepagents import CompiledSubAgent, create_deep_agent
import langchain.agents.middleware as mw

print("deepagents", deepagents.__version__)
print("langchain ", langchain.__version__)
print("langgraph ", langgraph.__version__)
print("\ncreate_deep_agent 签名：")
print(inspect.signature(create_deep_agent))

print("\n可用中间件 / 类型：")
for n in ["SummarizationMiddleware", "HumanInTheLoopMiddleware", "ModelCallLimitMiddleware",
          "ToolCallLimitMiddleware", "ModelFallbackMiddleware", "ToolRetryMiddleware",
          "ModelRetryMiddleware", "ContextEditingMiddleware", "ClearToolUsesEdit",
          "TodoListMiddleware", "AgentMiddleware", "ExtendedModelResponse",
          "AgentState", "ModelRequest", "ModelResponse",
          "wrap_tool_call", "wrap_model_call", "before_model", "after_model", "hook_config"]:
    print(f"  {'OK  ' if hasattr(mw, n) else 'MISS'} {n}")

print("\n关键签名：")
for n in ["SummarizationMiddleware", "ToolRetryMiddleware", "ToolCallLimitMiddleware",
          "ModelCallLimitMiddleware", "ContextEditingMiddleware"]:
    if hasattr(mw, n):
        print(f"  {n}{inspect.signature(getattr(mw, n).__init__)}")

# ★ Day 3 依赖：ToolCallRequest 到底有没有 runtime 属性
from langchain.tools.tool_node import ToolCallRequest
print("\nToolCallRequest 字段：",
      [a for a in dir(ToolCallRequest) if not a.startswith("_")])

# ★ 异步 hook 变体是否存在
print("\nAgentMiddleware 的 hook 方法：",
      [a for a in dir(mw.AgentMiddleware) if a.endswith(("_model", "_tool_call", "_agent"))])

# ★ Day 6 依赖
print("\nCompiledSubAgent:", inspect.signature(CompiledSubAgent))
