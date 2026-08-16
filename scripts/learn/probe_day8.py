"""probe_day8.py —— Day 8 探测：确认 wrap_model_call 这条链上的三个名字和形状。
运行：python scripts/probe_day8.py

要回答三个问题：
  ① ExtendedModelResponse / hook_config 这两个名字能不能导入？
  ② awrap_model_call 拿到的 response 是什么类型、usage_metadata 挂在哪一层？
  ③ before_model 的返回值里 jump_to 是不是合法 key？
"""
import inspect

import langchain.agents.middleware as mw

# ---------- ① 名字能不能导入 ----------
NAMES = [
    "AgentMiddleware", "AgentState", "ModelRequest", "ModelResponse",
    "ExtendedModelResponse", "hook_config",
    "ModelCallLimitMiddleware", "ToolCallLimitMiddleware",
    "ToolRetryMiddleware", "ModelRetryMiddleware",
    "ModelFallbackMiddleware", "ContextEditingMiddleware",
    "ClearToolUsesEdit",
]
print("== ① 导入检查 ==")
for n in NAMES:
    print(f"  {'✅' if hasattr(mw, n) else '❌'} {n}")

# ---------- ② ModelResponse / ExtendedModelResponse 的字段 ----------
print("\n== ② 响应对象的形状（决定 usage_metadata 去哪取）==")
for name in ("ModelResponse", "ExtendedModelResponse"):
    cls = getattr(mw, name, None)
    if cls is None:
        print(f"  {name}: 不存在")
        continue
    print(f"  {name}.__annotations__ = {list(getattr(cls, '__annotations__', {}).keys())}")
    try:
        print(f"  {name} 源码前 25 行：")
        print("    " + "\n    ".join(inspect.getsource(cls).splitlines()[:25]))
    except (OSError, TypeError) as e:
        print("    取不到源码:", e)

# ---------- ③ hook 签名 ----------
print("\n== ③ AgentMiddleware 上的 hook 签名 ==")
for hook in ("before_model", "wrap_model_call", "awrap_model_call", "after_model"):
    fn = getattr(mw.AgentMiddleware, hook, None)
    print(f"  {hook}: {inspect.signature(fn) if fn else '不存在'}")

# ---------- ④ ModelRequest 有没有 state ----------
print("\n== ④ ModelRequest 字段（累加用量要从 request.state 读）==")
print("  ", list(getattr(mw.ModelRequest, "__annotations__", {}).keys()))
