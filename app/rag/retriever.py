
import logging

from app.rag.embedder import Embedder
from app.rag.store import Hit, VectorStore

logger = logging.getLogger(__name__)

# ★★ 分数阈值。低于这个分数的结果视为"不相关"，不返回。
# 回忆 store.py 的转换公式：score = 1/(1+distance)
# 0.4 大约对应 distance=1.5，意思是"有点关系但不太靠谱"。
# 这个值需要根据实际效果调，不是理论最优值。
_DEFAULT_SCORE_THRESHOLD = 0.4


class Retriever:

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        score_threshold: float = _DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._score_threshold = score_threshold

    async def search(self, query: str, top_k: int = 5) -> list[Hit]:
        query_embedding = (await self._embedder.embed([query]))[0]

        hits = await self._store.query(query_embedding, top_k=top_k)

        filtered = [h for h in hits if h.score >= self._score_threshold]

        if not filtered:
            logger.info("检索零命中（阈值 %.2f）: %s", self._score_threshold, query)
        else:
            logger.info(
                "检索命中 %d 条（最高分 %.2f）: %s",
                len(filtered),
                filtered[0].score,
                query,
            )

        return filtered
