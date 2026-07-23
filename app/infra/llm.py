from langchain.chat_models import init_chat_model

from app.config import Settings


def build_chat_model(settings: Settings):
    return init_chat_model(
        model_provider="openai",
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
