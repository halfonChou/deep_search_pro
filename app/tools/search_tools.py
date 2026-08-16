import asyncio
import logging
from typing import Annotated, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import InjectedToolArg, tool
from tavily import TavilyClient

from app.config import Settings
from app.tools._offload import offload_if_large

logger = logging.getLogger(__name__)


_SEARCH_TIMEOUT = 20
_SEARCH_ATTEMPTS = 2
_SEARCH_RETRY_DELAY = 1.0


try:
    from tavily import AsyncTavilyClient
except ImportError:  # pragma: no cover
    AsyncTavilyClient = None


def _format_results(result: dict, snippet_chars: int = 500) -> str:
    """把 Tavily 的原始 dict 压成紧凑文本。

    以前是 str(result) 直接丢给模型：一次搜索 6 万多字符，
    里面绝大部分是 raw_content（整页正文）和一堆用不上的字段。
    """
    lines: list[str] = []

    if answer := result.get("answer"):
        lines.append(f"【检索摘要】{answer}\n")

    for i, item in enumerate(result.get("results", []), 1):
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip().replace("\n", " ")
        if len(content) > snippet_chars:
            content = content[:snippet_chars] + "…"
        score = item.get("score")
        score_text = f"（相关度 {score:.2f}）" if isinstance(score, int | float) else ""
        lines.append(f"{i}. {title}{score_text}\n   来源：{url}\n   内容：{content}")

    if not lines:
        return "网络搜索未获得有效结果。"
    return "\n".join(lines)


def build_search_tools(settings: Settings):
    """构建网络搜索工具。

    ★★ 这里是全项目最容易被忽略的性能杀手：
    TavilyClient.search() 是**同步阻塞**的。写在 async def 里不会报错，
    但它会把整个 asyncio 事件循环焊死十几秒——期间其他子 Agent 跑不动、
    WebSocket 推不出事件、FastAPI 连别的 HTTP 请求都接不了。

    LangGraph 的 ToolNode 本来会用 asyncio.gather 并发执行同一轮里的多个
    tool_call，被这一行堵住后，"并行"直接退化成严格串行。
    """
    async_client = AsyncTavilyClient(api_key=settings.tavily_api_key) if AsyncTavilyClient else None
    sync_client = TavilyClient(api_key=settings.tavily_api_key) if async_client is None else None

    if async_client is None:
        logger.warning(
            "未找到 AsyncTavilyClient，退回 asyncio.to_thread 方案。"
            "建议升级：pip install -U tavily-python"
        )

    async def _search(**kwargs) -> dict:
        if async_client is not None:
            return await async_client.search(**kwargs)
        # 兜底：把阻塞调用甩进线程池，事件循环照样不被占住
        return await asyncio.to_thread(lambda: sync_client.search(**kwargs))

    @tool
    async def internet_search(
            query: str,
            topic: Literal["news", "finance", "general"] = "general",
            max_results: int = 5,
            runtime: Annotated[ToolRuntime | None, InjectedToolArg] = None,
    ):
        """
            根据用户问题进行网络搜索。仅搜索公开网络信息。
            返回每条结果的标题、来源 URL 和内容摘要。
        """
        logger.info("internet_search 被调用 | query=%s | topic=%s", query, topic)

        result = None
        last_error = ""

        for attempt in range(1, _SEARCH_ATTEMPTS + 1):
            try:
                result = await asyncio.wait_for(
                    _search(
                        query=query,
                        topic=topic,
                        max_results=min(max_results, 8),
                        include_raw_content=False,
                        include_answer=True,
                    ),
                    timeout=_SEARCH_TIMEOUT,
                )
                if attempt > 1:
                    logger.info("internet_search 第 %d 次尝试成功 | query=%s", attempt, query)
                break
            except TimeoutError:
                last_error = f"超时({_SEARCH_TIMEOUT}s)"
            except Exception as e:
                # CancelledError 继承自 BaseException，不会被这里吞掉，
                # 所以任务取消仍然能正常传播。
                last_error = f"{type(e).__name__}: {e}"

            if attempt < _SEARCH_ATTEMPTS:
                logger.warning(
                    "internet_search 第 %d 次失败(%s)，%.0fs 后重试 | query=%s",
                    attempt, last_error, _SEARCH_RETRY_DELAY, query,
                )
                await asyncio.sleep(_SEARCH_RETRY_DELAY)
            else:
                logger.warning(
                    "internet_search %d 次尝试均失败(%s) | query=%s",
                    _SEARCH_ATTEMPTS, last_error, query,
                )

        if result is None:
            # 仍然返回字符串而不是抛异常：抛出去会被 ToolRetryMiddleware
            # 再重试 3 次、每次退避，白等 90 秒。
            return f"网络搜索未获得有效结果（{last_error}）。"

        text = _format_results(result)
        logger.info(
            "internet_search 返回 | 结果数=%d | 压缩后字符数=%d",
            len(result.get("results", [])), len(text),
        )

        return await offload_if_large(
            text, runtime=runtime, hint="search", settings=settings,
        )

    return [internet_search]
