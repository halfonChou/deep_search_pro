from langchain.agents.middleware import ToolCallLimitMiddleware

from app.agents.deps import AgentDeps
from app.prompt import sub_agent_prompts
from app.tools.search_tools import build_search_tools


def build_network_search_agent(deps: AgentDeps):
    """
    构建网络搜索子agent
    返回dict 声明子agent的配置， 由create_deep_agent 编译
    """
    p = sub_agent_prompts()["network-search"]

    return {
        "name": "network-search",
        "description": p["description"],
        "system_prompt": p["system_prompt"],
        "tools": build_search_tools(deps.settings),
        "middleware": [
            ToolCallLimitMiddleware(
                tool_name="internet_search",
                run_limit=deps.settings.search_tool_run_limit,
            ),
        ],
    }

