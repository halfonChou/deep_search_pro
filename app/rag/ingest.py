# app/rag/ingest.py
# ★★ 职责：离线建库的主干。读文档 → 分块 → 嵌入 → 写入向量库。

import hashlib
import logging
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.rag.embedder import Embedder
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)

# ★★ 中文分隔符——默认只有英文标点，对中文切得很烂。
# 优先级从高到低：先按段落切，段落太长按行切，再按句号、分号、逗号切。
_CN_SEPARATORS = ["\n\n", "\n", "。", "；", "，", " ", ""]

# ★★ 嵌入 API 单次最大条数。通义 text-embedding-v3 是 25。
# 超过这个数就要分批发，不然 API 报 400。
_EMBED_BATCH_SIZE = 25


def _load_file(path: Path) -> str | None:
    """按后缀读文件。返回 None 表示不支持的格式，跳过。

    ★★ 扩展点：将来加 PDF 支持，在这里加一个 elif 分支就行，
    上面的 ingest_documents 一行不改。
    """
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        text = path.read_text(encoding="utf-8")
        # 空文件跳过（扫描版 PDF 转出来可能是空的）
        return text.strip() or None
    # 将来在这里加：
    # elif suffix == ".pdf":
    #     return _load_pdf(path)
    else:
        logger.warning("不支持的文件格式，跳过: %s", path.name)
        return None


def _make_chunk_id(source: str, index: int) -> str:
    """生成分块 ID。同一文件同一位置的块，ID 永远相同。

    ★★ 为什么用 hash 而不是简单拼接？
    文件名可能含中文和特殊字符，Chroma 的 ID 最好是纯 ASCII。
    md5 前 12 位 + 序号，碰撞概率极低，且可读性还行。
    """
    name_hash = hashlib.md5(source.encode()).hexdigest()[:12]
    return f"{name_hash}_{index:04d}"


async def ingest_documents(
    doc_dir: Path,
    embedder: Embedder,
    store: VectorStore,
    settings: Settings,
) -> int:
    """摄取一个目录下的所有文档，返回写入的分块总数。

    这是整条离线管道的入口。建库脚本只需调这一个函数。

    ★★ 参数类型注意：
    - embedder 类型是 Embedder（Protocol），不是 OpenAIEmbedder
    - store 类型是 VectorStore（Protocol），不是 ChromaStore
    - 这就是 Protocol 的价值——这个函数不认识具体实现，只认合同
    """
    # ---- 第一步：读文档 ----
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.rag_chunk_size,       # 800
        chunk_overlap=settings.rag_chunk_overlap,  # 120
        separators=_CN_SEPARATORS,
    )

    all_chunks: list[str] = []       # 所有分块的文本
    all_ids: list[str] = []          # 所有分块的 ID
    all_metas: list[dict] = []       # 所有分块的元数据

    # ★★ doc_dir.iterdir() 遍历目录下所有文件（不递归子目录）。
    # 排序保证每次建库的处理顺序一致——同样的文档同样的顺序，
    # 生成的 chunk ID 也一样，upsert 才能正确覆盖。
    for file_path in sorted(doc_dir.iterdir()):
        if file_path.is_dir():
            continue

        text = _load_file(file_path)
        if text is None:
            continue

        # ---- 第二步：分块 ----
        chunks = splitter.split_text(text)
        source_name = file_path.name  # "阿莫西林.md"

        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_ids.append(_make_chunk_id(source_name, i))
            all_metas.append({"source": source_name})

        logger.info("文件 %s → %d 个分块", source_name, len(chunks))

    if not all_chunks:
        logger.warning("目录 %s 下没有可摄取的文档", doc_dir)
        return 0

    # ---- 第三步：嵌入（分批）----
    all_embeddings: list[list[float]] = []

    # ★★ 分批的原因：通义 v3 单次最多 25 条。
    # range(0, 100, 25) → [0, 25, 50, 75]，每次取 25 条。
    for start in range(0, len(all_chunks), _EMBED_BATCH_SIZE):
        batch = all_chunks[start : start + _EMBED_BATCH_SIZE]
        batch_vectors = await embedder.embed(batch)
        all_embeddings.extend(batch_vectors)
        logger.info(
            "嵌入进度: %d/%d",
            min(start + _EMBED_BATCH_SIZE, len(all_chunks)),
            len(all_chunks),
        )

    # ---- 第四步：写入向量库 ----
    await store.add(
        ids=all_ids,
        texts=all_chunks,
        embeddings=all_embeddings,
        metadatas=all_metas,
    )

    total = len(all_chunks)
    logger.info("摄取完成，共写入 %d 个分块", total)
    return total
