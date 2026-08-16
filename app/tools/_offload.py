"""大结果落盘卸载（L0 草稿层）。

当工具返回的文本超过 offload_threshold_bytes（默认 4KB），
把完整内容写进虚拟文件系统的 /scratch/ 目录，只把一段摘要 + 文件路径
回给上下文。模型需要细节时可以 read_file 取回。

★★ 落的是 /scratch/（L0 草稿，落在 checkpoints.sqlite 的虚拟文件系统里）。
绝不是 data/session/（L2 交付物）。搞错的后果：用户下载目录被搜索原文塞满。

★★ 关于写入方式（这里之前踩过坑）：
deepagents 的 ToolRuntime **没有** write_file 方法——内置的 write_file 工具
是通过 backend.awrite() 写的（见 deepagents/middleware/filesystem.py）。
而 StateBackend 本身不持有状态，它每次读写都用 langgraph 的 get_config()
去当前图执行上下文里拿 files 通道，官方注释明确说了它可以
"fetch state on demand from any graph context (tools, middleware nodes, etc.)"。
所以这里在模块级建一个复用即可，行为和内置 write_file 完全一致。
"""

from __future__ import annotations

import logging
from uuid import uuid4

from deepagents.backends.state import StateBackend
from deepagents.backends.utils import validate_path
from langchain.tools import ToolRuntime

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# 无状态，可安全复用。读写时才去当前图上下文取 files 通道。
_backend = StateBackend()

# 落盘失败时的兜底截断长度。比 offload_summary_chars 大得多——
# 摘要那 200 字是"有全文兜底"时的展示片段，而落盘失败意味着全文没了，
# 这时候多留一些是在减少损失。
_FALLBACK_CHARS = 2000


def _truncated(text: str, limit: int, reason: str) -> str:
    """落盘失败时的降级返回。明确告知模型全文不可用，避免它凭片段瞎猜。"""
    return (
        f"[结果较大（{len(text)} 字符），{reason}，仅返回开头 {limit} 字符。\n"
        f"完整内容本次不可用——请只依据以下片段作答，缺失部分如实说明「未取到」，"
        f"不要推测片段里没有出现的内容]\n"
        f"{text[:limit]}\n…（已截断）"
    )


async def offload_if_large(
    text: str,
    runtime: ToolRuntime | None = None,
    hint: str = "result",
    settings: Settings | None = None,
) -> str:
    """大于阈值就写进虚拟文件系统的 /scratch/，只把摘要 + 路径回给上下文。

    Parameters
    ----------
    text : str
        工具原始返回文本。
    runtime : ToolRuntime | None
        保留这个参数只为兼容现有三个调用方的签名。
        写入不再依赖它（走 StateBackend），但保留可以避免改动 search_tools /
        sql_tools / rag_tools。
    hint : str
        文件名前缀，便于在 /scratch/ 里区分来源（如 "search"、"sql"、"rag"）。
    settings : Settings | None
        配置对象。如果为 None，从 get_settings() 取。

    Returns
    -------
    str
        未超阈值 → 原文；落盘成功 → 摘要 + 路径；落盘失败 → 加长截断 + 警告。
    """
    if settings is None:
        settings = get_settings()

    threshold = settings.offload_threshold_bytes
    summary_chars = settings.offload_summary_chars
    scratch_dir = settings.scratch_dir  # 默认 "/scratch"

    # 未超阈值，直接返回
    raw_bytes = len(text.encode("utf-8"))
    if raw_bytes <= threshold:
        return text

    # 构造并校验虚拟路径。validate_path 会拒绝 .. 穿越和 Windows 盘符路径，
    # 并把路径归一化成以 / 开头的 posix 形式。
    try:
        path = validate_path(f"{scratch_dir}/{hint}-{uuid4().hex[:8]}.txt")
    except ValueError as e:
        logger.warning("[Offload] 路径非法，退回截断：%s", e)
        return _truncated(text, _FALLBACK_CHARS, f"落盘路径非法（{e}）")

    # 这里故意用同步的 write 而不是 awrite：
    # StateBackend.write 只是往 langgraph 的 channel 里塞一条待写记录，
    # 纯内存操作、不碰 I/O，不会阻塞事件循环。awrite 是协议层的默认包装，
    # 对这个 backend 没有额外好处。
    try:
        result = _backend.write(path, text)
    except Exception as e:
        # 最常见的失败原因：当前图的 state 里没有 files 通道
        # （例如自定义 StateGraph 的 state schema 没声明 files）。
        logger.warning(
            "[Offload] 写虚拟文件系统失败（%s: %s）。"
            "如果调用方是自定义子图，检查它的 state schema 有没有 files 通道。",
            type(e).__name__, e,
        )
        return _truncated(text, _FALLBACK_CHARS, "落盘失败")

    if result.error:
        logger.warning("[Offload] backend 返回错误：%s", result.error)
        return _truncated(text, _FALLBACK_CHARS, f"落盘失败（{result.error}）")

    logger.info(
        "[Offload] 大结果落盘 | hint=%s | 原始=%d 字符 | 路径=%s",
        hint, len(text), path,
    )

    return (
        f"[完整结果共 {len(text)} 字符，已存至虚拟文件 {path}。以下为开头片段]\n"
        f"{text[:summary_chars]}\n"
        f"[需要完整内容或核对细节时，调 read_file('{path}') 取回。"
        f"该文件在本会话内有效，主 Agent 也能读到]"
    )
