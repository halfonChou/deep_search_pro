"""probe_day3.py —— Day 3 探测 v2：精确检查 ToolCallRequest / ModelRequest 的字段
运行：python scripts/probe_day3.py
"""
import dataclasses
import inspect

from langchain.agents.middleware import ModelRequest
from langchain.tools.tool_node import ToolCallRequest


def dump_fields(cls):
    print(f"\n== {cls.__name__} ==")
    try:
        fields = dataclasses.fields(cls)
        print("  dataclass fields:")
        for f in fields:
            print(f"    - {f.name}: {f.type}" + (f"  (default={f.default!r})" if f.default is not dataclasses.MISSING else "  [必填，无默认]"))
    except TypeError:
        print("  不是 dataclass；annotations:", getattr(cls, "__annotations__", None))
    # 辅助：直接看 annotations
    ann = getattr(cls, "__annotations__", {})
    print("  __annotations__ keys:", list(ann.keys()))
    if "runtime" in ann:
        print(f"  ★ runtime 存在，类型: {ann['runtime']}")
    else:
        print("  ★ runtime 不在 annotations 里")
    if "state" in ann:
        print(f"  ★ state 存在，类型: {ann['state']}")


for cls in (ToolCallRequest, ModelRequest):
    dump_fields(cls)

# 打印 ToolCallRequest 源码，一锤定音
print("\n" + "=" * 60)
print("ToolCallRequest 源码（打印前 40 行）：")
try:
    src = inspect.getsource(ToolCallRequest)
    print("\n".join(src.splitlines()[:40]))
except (OSError, TypeError) as e:
    print("  取不到源码:", e)
    # 兜底：打印文件路径
    try:
        print("  定义于:", inspect.getfile(ToolCallRequest))
    except TypeError:
        pass
