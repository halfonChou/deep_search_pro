"""逐个测试三档模型能不能调通，绕开 Agent 和中间件。

401 invalid_api_key 有三种成因，这个脚本能分开它们：

- 三个模型全 401  → key 本身失效，或者被代理改写了 Authorization 头
- 只有 plus/turbo 401 → 那两个模型在你的账号/地域没开通
- 全部通过        → 问题不在模型层，在 Agent 里某个别的调用点

用法（项目根目录）：
    python scripts/check_models.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import AsyncOpenAI  # noqa: E402

from app.config import get_settings  # noqa: E402

PROXY_VARS = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy"]


def report_env(settings) -> None:
    print("=" * 60)
    print(f"端点  : {settings.llm_base_url}")
    key = settings.llm_api_key or ""
    print(f"Key   : 长度 {len(key)}，前缀 {key[:6]!r}，后缀 {key[-4:]!r}")
    print()

    proxies = {v: os.environ.get(v) for v in PROXY_VARS if os.environ.get(v)}
    if proxies:
        print("⚠ 检测到代理环境变量 —— httpx 会把 DashScope 的请求也走代理，")
        print("  某些 LLM 代理（比如 cli-proxy-api）会改写 Authorization 头，")
        print("  于是 key 到达阿里云时已经不是你配的那个了。")
        for k, v in proxies.items():
            print(f"    {k} = {v}")
        print("  排查办法：让 dashscope 绕过代理")
        print('    $env:NO_PROXY = "dashscope.aliyuncs.com"')
        print()
    else:
        print("未检测到代理环境变量。")
        print()

    # 这两个变量存在时，某些客户端会优先用它们而不是显式传入的 api_key
    for v in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        if os.environ.get(v):
            print(f"⚠ 环境变量 {v} 存在（值不显示）——注意它可能干扰 SDK 的默认取值")
    print("=" * 60)
    print()


async def try_model(client: AsyncOpenAI, model: str) -> bool:
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回答一个字：好"}],
            max_tokens=8,
        )
        usage = r.usage
        print(f"✅ {model:<14} 通过 | 输入 {usage.prompt_tokens} / 输出 {usage.completion_tokens} token")
        return True
    except Exception as e:
        name = type(e).__name__
        msg = str(e).replace("\n", " ")
        print(f"❌ {model:<14} 失败 | {name}: {msg[:220]}")
        return False


async def main() -> int:
    s = get_settings()
    report_env(s)

    client = AsyncOpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)

    tiers = [
        ("T1 主 Agent", s.llm_model),
        ("T2 子 Agent", s.llm_model_fast),
        ("T3 摘要压缩", s.llm_model_cheap),
    ]
    results = {}
    for label, model in tiers:
        print(f"[{label}]")
        results[model] = await try_model(client, model)
        print()

    ok = [m for m, v in results.items() if v]
    bad = [m for m, v in results.items() if not v]

    print("=" * 60)
    if not bad:
        print("✅ 三档全部通过。401 不是模型层的问题——")
        print("   去查 Agent 里别的调用点：embedder（rag/embedder.py 用同一个 key，")
        print("   但如果 EMBED_MODEL 没开通也会报错）、或 fallback_models 里配了别的模型。")
        return 0

    if not ok:
        print("❌ 三档全部失败 → key 本身的问题，或者被代理改写了。")
        print("   1) 去百炼控制台确认这个 key 还有效、没被禁用")
        print("   2) 如果上面提示了代理变量，先设 NO_PROXY 再试：")
        print('        $env:NO_PROXY = "dashscope.aliyuncs.com"')
        print("        python scripts/check_models.py")
        print("   3) 确认 key 的地域和端点匹配（北京的 key 不能用新加坡端点）")
        return 1

    print(f"⚠ 部分失败：通过 {ok}，失败 {bad}")
    print("  key 是好的，失败的那几个模型在你的账号里没开通或名称写错了。")
    print("  去百炼控制台看模型广场里的准确名称，改 config.py 的")
    print("  llm_model_fast / llm_model_cheap，或在 .env 里覆盖：")
    print("    LLM_MODEL_FAST=qwen-plus")
    print("    LLM_MODEL_CHEAP=qwen-turbo")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
