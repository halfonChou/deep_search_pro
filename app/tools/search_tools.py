from typing import Literal

from langchain_core.tools import tool
from tavily import TavilyClient

from app.agents.events import AgentEvent
from app.config import Settings
from app.infra.emitter import EventEmitter


def build_search_tools(emitter:EventEmitter,settings:Settings):
    client = TavilyClient(api_key = settings.tavily_api_key)
    @tool
    async def internet_search(
            query:str,
            topic: Literal["news","finance","general"] = "general",
            max_results:int = 10,
            include_raw_content:bool = True,
    ):
        """
            根据用户问题进行网络搜索。仅搜索公开网络信息。
        """
        await emitter.emit(
            AgentEvent(
                type="tool_start",
                thread_id="",
                message="网络搜索工具",
                data={"query":query, "topic":topic},
            )
        )

        return client.search(
            query=query,
            topic=topic,
            max_results=max_results,
            include_raw_content=include_raw_content,
        )

    return [internet_search]
