from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: list[str]):
        ...



class OpenAIEmbedder:
    def __init__(self, base_url:str, api_key:str, model:str) -> None:
        self._client = AsyncOpenAI(base_url = base_url, api_key = api_key)
        self._model = model

    async def embed(self, text: list[str]):

        resp = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )

        sort_data = sorted(resp.data, key=lambda  x: x.index)
        return [item.embedding for item in sort_data]
