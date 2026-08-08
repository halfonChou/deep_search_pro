"""探测 __interrupt__ 的真实结构（Day 7）。

目的：不猜 langgraph/deepagents 的中断值长什么样，直接触发一次看实物。
用法：
    python scripts/learn/probe_interrupt.py

输出：中断发生时，把 __interrupt__ 的原始值完整打印出来。
"""
import asyncio

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

import deepagents
from deepagents import create_deep_agent


# ---------- 1. 一个真正的 SQL 工具 ----------
@tool
async def execute_sql_query(query: str) -> str:
    """执行一条只读 SQL。"""
    return f"[fake-db] {query}"


# ---------- 2. 假模型：两轮对话 ----------
class FakeSQLModel(FakeMessagesListChatModel):
    """假模型：第一轮返回带 tool_calls 的 AIMessage，第二轮返回最终回答。"""

    def __init__(self, **kwargs):
        # responses 是 pydantic 必填字段，必须在构造时传入
        super().__init__(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "execute_sql_query",
                        "args": {"query": "SELECT * FROM sales_record"},
                        "id": "call_probe_1",
                    }],
                ),
                # 第 2 轮（工具执行后）：输出最终回答
                AIMessage(content="已完成查询，这是结果摘要。"),
            ],
            **kwargs,
        )

    def bind_tools(self, tools, **kwargs):
        # deepagents 会把工具说明书绑定给模型；假模型直接忽略，返回自身即可
        return self


# ---------- 3. 主流程 ----------
async def main():
    print("deepagents", deepagents.__version__)

    agent = create_deep_agent(
        model=FakeSQLModel(),
        tools=[execute_sql_query],
        interrupt_on={
            "execute_sql_query": {"allowed_decisions": ["approve", "edit", "reject"]},
        },
        checkpointer=MemorySaver(),   # HITL 必须配 checkpointer
    )

    config = {"configurable": {"thread_id": "probe-t1"}}
    print("\n=== astream 开始 ===")
    async for chunk in agent.astream(
        {"messages": [{"role": "user", "content": "帮我查一下销售数据"}]},
        config=config,
        stream_mode=["updates", "messages"],
        version="v2",
    ):
        if chunk["type"] == "updates":
            print("--- updates chunk ---")
            for node, data in chunk["data"].items():
                print(f"node={node}")
                print(repr(data)[:2000])
                if node == "__interrupt__":
                    print("\n===== 关键：__interrupt__ 的值 =====")
                    for i, item in enumerate(data):
                        print(f"\n--- item {i} ---")
                        print("type:", type(item))
                        print("repr:", repr(item)[:3000])
                        # 尝试挖 action_requests
                        ar = getattr(item, "action_requests", None)
                        print("action_requests:", repr(ar)[:3000])
                        if ar:
                            for j, req in enumerate(ar):
                                print(f"  req {j}:", repr(req)[:1500])
        elif chunk["type"] == "messages":
            token, _meta = chunk["data"]
            if getattr(token, "content", ""):
                print(f"[token] {token.content}", end="", flush=True)
    print("\n=== 结束 ===")


if __name__ == "__main__":
    asyncio.run(main())
