from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import chromadb

@dataclass
class Hit:
    id: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)
    # 使用factory 是为了确保 每个Hit 拿到独立的字典


@runtime_checkable
class VectorStore(Protocol):
    async def add(
            self,
            ids: list[str],
            texts: list[str],
            embeddings: list[list[float]],
            metadatas: list[dict]):

        ...

    async def query(
            self,
            embedding: list[float],
            top_k: int = 5,):

        ...

class ChromaStore:
    def __init__(self, persist_directory:str, collection_name:str = "knowledge"):
        self._chroma = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._chroma.get_or_create_collection(
            name = collection_name
        )

    async def add(
            self,
            ids: list[str],
            texts: list[str],
            embeddings: list[list[float]],
            metadatas: list[dict]):

        self._collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas
        )

    async def query(
            self,
            embedding: list[float],
            top_k: int = 5,
    ):
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )

        hits: list[Hit] = []

        ids = result["ids"][0]
        docs = result["documents"][0]
        distances = result["distances"][0]
        metas = result["metadatas"][0]

        for i, doc_id in enumerate(ids):
            hits.append(
                Hit(
                    id = doc_id,
                    text = docs[i],
                    score= 1.0 / (1.0 + distances[i]),
                    metadata=metas[i] if metas[i] else {} ,
                ))

        return hits