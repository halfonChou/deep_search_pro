from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import tool

from app.agents.deps import AgentDeps
from app.infra.llm import build_chat_model
from app.prompt import sub_agent_prompts
from app.tools.rag_tools import build_rag_tools


def _build_degraded_tools() -> list:

    @tool
    async def rag_search(query: str) -> str:
        """在企业知识库中检索与查询相关的文档片段。

        适用场景：药品存储规范、使用说明、安全须知等企业内部文档查询。
        返回匹配的文档片段及来源信息，如无匹配则明确说明。
        """
        return (
            f"知识库当前不可用，无法检索「{query}」。"
            "请改用网络搜索获取公开资料，并在回答中标注信息来源性质。"
        )

    return [rag_search]


def build_knowledge_base_agent(deps: AgentDeps) -> dict:
    p = sub_agent_prompts()["knowledge-base"]

    tools = build_rag_tools(deps.retriever) if deps.retriever is not None else _build_degraded_tools()

    return {
        "name": "knowledge-base",
        # ★ 必须传实例，不能传字符串。
        # deepagents 的 resolve_model 对字符串会走 init_chat_model(model)，
        # 既推断不出 DashScope 的 provider（报 Unable to infer model provider），
        # 也没地方传 base_url / api_key。传实例它会原样放行。
        "model": build_chat_model(deps.settings, deps.settings.llm_model_fast),
        "description": p["description"],           # 主 Agent 靠这段决定要不要派活
        "system_prompt": p["system_prompt"],
        "tools": tools,
        "middleware": [
            ToolCallLimitMiddleware(
                tool_name="rag_search",
                run_limit=5,
            ),
        ],
    }
