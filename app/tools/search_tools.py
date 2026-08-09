import logging
from typing import Literal

from langchain_core.tools import tool
from tavily import TavilyClient

from app.config import Settings

# ★★ 模块级 logger，名字自动是 "app.tools.search_tools"，
# 日志里能一眼看出是哪个模块打的
logger = logging.getLogger(__name__)


def build_search_tools(settings: Settings):
    client = TavilyClient(api_key=settings.tavily_api_key)

    @tool
    async def internet_search(
            query: str,
            topic: Literal["news", "finance", "general"] = "general",
            max_results: int = 10,
            include_raw_content: bool = True,
    ):
        """
            根据用户问题进行网络搜索。仅搜索公开网络信息。
        """
        # ★★ 桩 1：证明这个工具到底有没有被调用。
        # 子 Agent 是独立子图，主流程看不到它内部，只能靠日志。
        logger.info("internet_search 被调用 | query=%s | topic=%s", query, topic)

        result = client.search(
            query=query,
            topic=topic,
            max_results=max_results,
            include_raw_content=include_raw_content,
        )

        # ★★ 桩 2：量返回体积。这是 Day 10 上下文卸载的基准值。
        size = len(str(result))
        logger.info(
            "internet_search 返回 | 结果数=%d | 字符数=%d %s",
            len(result.get("results", [])),
            size,
            "⚠️ 超过 4KB，Day 10 该卸载" if size > 4096 else "",
        )
        return result

    return [internet_search]