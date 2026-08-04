from typing import Literal

from langchain_core.tools import tool
from tavily import TavilyClient

from app.config import Settings


def build_search_tools(settings:Settings):
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

        return client.search(
            query=query,
            topic=topic,
            max_results=max_results,
            include_raw_content=include_raw_content,
        )

    return [internet_search]
