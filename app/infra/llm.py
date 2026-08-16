from langchain.chat_models import init_chat_model

from app.config import Settings


def build_chat_model(settings: Settings, model:str | None = None):
    return init_chat_model(
        model_provider="openai",
        model=(model or settings.llm_model),
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        # ★ 流式调用下 OpenAI 协议默认不回 usage，预算中间件就统计不到 token。
        # stream_usage=True 会带上 stream_options={"include_usage": true}，
        # 让最后一个 chunk 里带 usage_metadata。DashScope 兼容模式支持这个参数。
        stream_usage=True,
    )


def build_fallback_model(settings: Settings):
    return [init_chat_model(
        model_provider="openai",
        model=name,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        stream_usage=True,
    )
        for name in settings.fallback_models
    ]
