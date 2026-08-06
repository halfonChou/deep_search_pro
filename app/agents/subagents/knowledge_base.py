"""知识库子 Agent 工厂 —— 声明式子 Agent（Day 9 前为桩）。

为什么是桩：RAG 检索（嵌入 + Chroma）在 Day 9 实现。
今天先返回一个只有 list_knowledge_bases 桩工具的版本，
把 description 结构定下来，主 Agent 的路由逻辑今天就能测。
"""
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import tool

from app.agents.deps import AgentDeps
from app.prompt import sub_agent_prompts


def _build_knowledge_tools():
    """知识库工具的桩版本（Day 9 换成真实 RAG 检索）。"""

    @tool
    async def list_knowledge_bases() -> str:
        """列出当前可用的知识库。"""
        return "目前可用的知识库：药品知识库（阿莫西林、布洛芬等常用药的存储/使用/安全文档）"

    return [list_knowledge_bases]


def build_knowledge_base_agent(deps: AgentDeps) -> dict:
    """构建知识库子 Agent。"""
    p = sub_agent_prompts()["knowledge-base"]

    return {
        "name": "knowledge-base",
        "description": p["description"],           # 主 Agent 靠这段决定要不要派活
        "system_prompt": p["system_prompt"],
        "tools": _build_knowledge_tools(),
        "middleware": [
            ToolCallLimitMiddleware(
                tool_name="list_knowledge_bases",
                run_limit=5,
            ),
        ],
    }
