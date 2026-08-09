# tests/test_rag.py
# ★★ 职责：验证 RAG 流水线的核心逻辑。不调真实 API，用 Fake 替身。

import pytest

from app.rag.embedder import Embedder
from app.rag.store import ChromaStore, Hit, VectorStore
from app.rag.ingest import ingest_documents, _load_file, _make_chunk_id
from app.rag.retriever import Retriever
from pathlib import Path
from unittest.mock import AsyncMock
from app.config import get_settings


# ★★ FakeEmbedder：不调 API，直接返回固定长度的假向量。
# 这就是 Protocol 的价值——ingest 和 retriever 不认识具体类，
# 传 Fake 进去照样跑，零网络请求，测试飞快。
class FakeEmbedder:
    """假嵌入器：返回全 0 向量，维度 = 文本长度 % 100 + 1（保证非零维度）。"""
    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # 每条文本返回一个长度为 dim 的向量
        # 用文本长度做微小扰动，让不同文本的向量略有不同
        return [
            [len(t) * 0.01 + i * 0.001 for i in range(self._dim)]
            for t in texts
        ]


# ========== 测试用例 ==========

class TestLoadFile:
    """测试文件加载。"""

    def test_load_md(self, tmp_path: Path):
        """能读 .md 文件。"""
        f = tmp_path / "test.md"
        f.write_text("# 测试内容\n这是一段文字。", encoding="utf-8")
        assert _load_file(f) is not None

    def test_load_txt(self, tmp_path: Path):
        """能读 .txt 文件。"""
        f = tmp_path / "test.txt"
        f.write_text("普通文本内容", encoding="utf-8")
        assert _load_file(f) is not None

    def test_load_unsupported(self, tmp_path: Path):
        """不支持的格式返回 None。"""
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4 fake content")
        assert _load_file(f) is None

    def test_load_empty(self, tmp_path: Path):
        """空文件返回 None。"""
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        assert _load_file(f) is None


class TestChunkId:
    """测试分块 ID 的稳定性。"""

    def test_same_input_same_id(self):
        """同样的文件名 + 序号 → 同样的 ID（幂等）。"""
        id1 = _make_chunk_id("阿莫西林.md", 3)
        id2 = _make_chunk_id("阿莫西林.md", 3)
        assert id1 == id2

    def test_different_input_different_id(self):
        """不同文件名 → 不同 ID。"""
        id1 = _make_chunk_id("阿莫西林.md", 0)
        id2 = _make_chunk_id("布洛芬.md", 0)
        assert id1 != id2


class TestRetriever:
    """测试检索器的分数过滤逻辑。"""

    @pytest.mark.asyncio
    async def test_filter_low_score(self):
        """低分结果应被过滤掉。"""
        fake_embedder = FakeEmbedder()

        # Mock 一个 store，返回两条结果：一条高分一条低分
        mock_store = AsyncMock(spec=VectorStore)
        mock_store.query.return_value = [
            Hit(id="1", text="高分结果", score=0.85, metadata={}),
            Hit(id="2", text="低分结果", score=0.20, metadata={}),
        ]

        retriever = Retriever(fake_embedder, mock_store, score_threshold=0.4)
        hits = await retriever.search("测试查询")

        assert len(hits) == 1
        assert hits[0].id == "1"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """全部低分 → 返回空列表（触发 fallback）。"""
        fake_embedder = FakeEmbedder()

        mock_store = AsyncMock(spec=VectorStore)
        mock_store.query.return_value = [
            Hit(id="1", text="不相关", score=0.15, metadata={}),
            Hit(id="2", text="也不相关", score=0.10, metadata={}),
        ]

        retriever = Retriever(fake_embedder, mock_store, score_threshold=0.4)
        hits = await retriever.search("完全不相关的问题")

        assert hits == []  # 空列表，不是异常