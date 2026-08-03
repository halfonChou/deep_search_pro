# scripts/probe_api.py —— Day 1 第一件事
import inspect
from importlib import metadata

import deepagents, langchain, langgraph
from deepagents import create_deep_agent
import langchain.agents.middleware as mw


def _version(pkg: str) -> str:
    """取已安装包版本。langgraph 1.x 移除了 __version__ 属性，统一走 importlib.metadata。"""
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "?" + getattr(__import__(pkg), "__version__", "?")


print("deepagents", _version("deepagents"))
print("langchain ", _version("langchain"))
print("langgraph ", _version("langgraph"))
print("\ncreate_deep_agent 签名：")
print(inspect.signature(create_deep_agent))
print("\n可用中间件 / 类型：")
for n in ["SummarizationMiddleware","HumanInTheLoopMiddleware","ModelCallLimitMiddleware",
          "ToolCallLimitMiddleware","ModelFallbackMiddleware","ToolRetryMiddleware",
          "ModelRetryMiddleware","ContextEditingMiddleware","ClearToolUsesEdit",
          "TodoListMiddleware","AgentMiddleware","ExtendedModelResponse",
          "AgentState","ModelRequest","ModelResponse",
          "wrap_tool_call","wrap_model_call","before_model","after_model","hook_config"]:
    print(f"  {'OK  ' if hasattr(mw, n) else 'MISS'} {n}")

print("\n关键签名：")
for n in ["SummarizationMiddleware","ToolRetryMiddleware","ToolCallLimitMiddleware",
          "ModelCallLimitMiddleware","ContextEditingMiddleware"]:
    if hasattr(mw, n):
        print(f"  {n}{inspect.signature(getattr(mw, n).__init__)}")

# ★ Day 3 依赖：ToolCallRequest 到底有没有 runtime 属性
from langchain.tools.tool_node import ToolCallRequest
print("\nToolCallRequest 字段：",
      [a for a in dir(ToolCallRequest) if not a.startswith("_")])

# ★ 异步 hook 变体是否存在
print("\nAgentMiddleware 的 hook 方法：",
      [a for a in dir(mw.AgentMiddleware) if a.endswith(("_model","_tool_call","_agent"))])

# ★ Day 6 依赖
# CompiledSubAgent 在 deepagents 0.6+ 是一个 TypedDict（dict 子类），
# inspect.signature 对它无效，改成打印字段结构。
from deepagents import CompiledSubAgent
print("\nCompiledSubAgent：TypedDict(dict) 配置结构")
print("  annotations:", getattr(CompiledSubAgent, "__annotations__", None))
print("  required   :", getattr(CompiledSubAgent, "__required_keys__", None))