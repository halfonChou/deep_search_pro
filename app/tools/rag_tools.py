import logging
import re
from collections import OrderedDict
from typing import Annotated

from langchain.tools import ToolRuntime
from langchain_core.tools import InjectedToolArg, tool

from app.config import Settings, get_settings
from app.rag.retriever import Retriever
from app.tools._offload import offload_if_large

logger = logging.getLogger(__name__)

# ★ 同查询去重缓存。
#
# 为什么用代码而不是 prompt：实测同一个会话里 rag_search 被用**完全相同**的
# 查询串调了两次，返回一模一样的 3 条片段。prompt 里写"默认只检索 1 次"没压住——
# 因为规则是概率性的，而且和别的规则会打架。
#
# "同一个查询重复检索"这件事有确定的正确答案（第二次就是浪费），
# 凡是能用一行 if 写死的约束，就不该交给模型去权衡。
#
# 命中缓存时**照样把内容返回给模型**（不能让它拿不到数据），
# 但在开头标明这是重复调用，引导它别再试第三次。
_CACHE_MAX = 200
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()


def _thread_id_of(runtime: ToolRuntime | None) -> str:
    """从 ToolRuntime 里取 thread_id 做缓存分区。

    取不到就退回全局分区——宁可跨会话误命中一次相同查询，
    也比缓存完全失效强（内容一样，不会答错）。
    """
    ctx = getattr(runtime, "context", None) if runtime is not None else None
    return getattr(ctx, "thread_id", "") or "_global"


def _norm(query: str) -> str:
    """归一化查询串：去首尾空白、把连续空白压成一个、统一小写。

    中文不受 lower() 影响，主要是为了兼容英文和全角/半角空格的差异。
    """
    return re.sub(r"\s+", " ", query.strip()).lower()


def _cache_get(key: tuple[str, str]) -> str | None:
    if key not in _cache:
        return None
    _cache.move_to_end(key)          # LRU：命中就挪到末尾
    return _cache[key]


def _cache_put(key: tuple[str, str], value: str) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)   # 淘汰最久未用的


def build_rag_tools(retriever: Retriever, settings: Settings | None = None) -> list:
    if settings is None:
        settings = get_settings()

    @tool
    async def rag_search(
        query: str,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg] = None,
    ) -> str:
        """在企业知识库中检索与查询相关的文档片段。

        适用场景：药品存储规范、使用说明、安全须知等企业内部文档查询。
        返回匹配的文档片段及来源信息，如无匹配则明确说明。
        """
        key = (_thread_id_of(runtime), _norm(query))

        if (cached := _cache_get(key)) is not None:
            logger.info("rag_search 命中去重缓存，跳过检索 | query=%s", query)
            return (
                f"【注意：本次未重新检索】你在本次任务里已经用完全相同的查询"
                f"「{query}」检索过知识库，下面是上次的结果原文。\n"
                f"知识库内容在一次任务里不会变化，**不要再用同样或近似的查询重复检索**。\n"
                f"如果这些内容不足以回答问题，说明知识库里就是没有，"
                f"如实汇报未命中，由上级决定是否转网络搜索。\n\n"
                f"{cached}"
            )

        hits = await retriever.search(query)

        if not hits:
            result = f"知识库中未找到与「{query}」相关的内容。建议改用网络搜索获取公开资料。"
            _cache_put(key, result)   # 零命中也缓存，防止拿同一个词反复空跑
            return result

        parts: list[str] = []
        for i, hit in enumerate(hits, start=1):
            source = hit.metadata.get("source", "未知来源")
            parts.append(
                f"【片段 {i}】(来源: {source}, 相关度: {hit.score:.2f})\n"
                f"{hit.text}"
            )

        text = "\n\n---\n\n".join(parts)
        logger.info("rag_search 返回 | 片段数=%d | 字符数=%d", len(hits), len(text))

        # Day 10：大结果落盘卸载到 /scratch/（L0），只回摘要
        result = await offload_if_large(
            text, runtime=runtime, hint="rag", settings=settings,
        )
        _cache_put(key, result)
        return result

    return [rag_search]
