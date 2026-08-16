"""验证 prompt 缓存到底有没有生效（绕开 Agent，直接打模型）。

做法：用同一段很长的系统提示，连着发两次请求。
- 第一次：缓存刚建立，cached_tokens 通常是 0
- 第二次：前缀完全相同，cached_tokens 应该接近系统提示的长度

这个脚本不依赖你的 Agent 代码，所以能把问题隔离开：
- 这里能命中，Agent 里不命中 → 是你的前缀不稳定（中间件在改历史）
- 这里也不命中 → 是模型/地域/参数的问题，跟你的代码无关

用法（项目根目录）：
    python scripts/check_cache.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import AsyncOpenAI  # noqa: E402

from app.config import get_settings  # noqa: E402

# 隐式缓存有最小长度门槛（百炼部署 256 token，Qwen3.7 系列 2000 token），
# 显式缓存要 1024 token。这里堆到 4000 token 以上，确保跨过所有门槛。
FILLER = (
    "你是一个医药行业分析助手。你需要严格遵守以下工作规范："
    "一、所有结论必须有数据来源支撑，不允许编造。"
    "二、涉及药品存储条件时，必须引用内部规范原文。"
    "三、涉及销售数据时，必须说明统计口径和时间范围。"
    "四、涉及市场行情时，必须附带来源网址。"
) * 100

SYSTEM_PROMPT = FILLER + "\n请用一句话回答用户的问题。"


def _report(tag: str, usage) -> int:
    """打印 usage，返回命中的 token 数。"""
    prompt_tokens = getattr(usage, "prompt_tokens", 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = 0
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    elif isinstance(usage, dict):
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0

    rate = cached / prompt_tokens * 100 if prompt_tokens else 0
    print(f"{tag}: 输入 {prompt_tokens} token | 命中缓存 {cached} | 命中率 {rate:.0f}%")
    return cached


async def main() -> int:
    s = get_settings()
    client = AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)
    print(f"模型：{s.llm_model}\n地域/端点：{s.llm_base_url}\n")

    async def ask(question: str):
        stream = await client.chat.completions.create(
            model=s.llm_model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": question}],
            max_tokens=32,
            stream=True,
            stream_options={"include_usage": True},  # 关键
        )
        usage = None
        async for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
        return usage

    # 第一次：建立缓存
    r1 = await ask("布洛芬属于哪一类药？")
    _report("第 1 次（建缓存）", r1.usage)

    await asyncio.sleep(2)

    # 第二次：前缀一字不差，应该命中
    r2 = await ask("阿莫西林属于哪一类药？")
    cached2 = _report("第 2 次（应命中）", r2.usage)

    # 第三次：故意在系统提示【开头】改一个字，缓存应该失效
    await asyncio.sleep(2)
    r3 = await client.chat.completions.create(
        model=s.llm_model,
        messages=[
            {"role": "system", "content": "X" + SYSTEM_PROMPT},
            {"role": "user", "content": "阿莫西林属于哪一类药？"},
        ],
        max_tokens=32,
    )
    cached3 = _report("第 3 次（开头改一个字，应失效）", r3.usage)

    print()
    if cached2 > 0:
        print("✅ 这个模型 + 这个端点支持隐式缓存，且确实命中了。")
        if cached3 < cached2:
            print("✅ 开头改一个字就失效 —— 印证了「前缀必须完全一致」这条规则。")
        print("\n下一步：跑一次真实任务，看 [cache] 日志里的命中率。")
        print("如果那边明显低于这里，问题就在中间件重写历史 / todos 注入位置上。")
        return 0

    print("❌ 第 2 次也没命中。可能的原因，按可能性排序：")
    print("   1. 这个模型不支持上下文缓存 —— 换 qwen-plus 或 qwen-max 再试")
    print(f"   2. 端点地域不支持 —— 你用的是 {s.llm_base_url}，华北2（北京）支持最全")
    print("   3. 系统提示还没到最小长度门槛 —— 把脚本里 FILLER 的 *40 调成 *100 再试")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
