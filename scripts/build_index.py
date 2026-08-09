# scripts/build_index.py
# ★★ 职责：命令行一键建库。运行方式：python -m scripts.build_index --dir knowledge_base

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.config import get_settings
from app.rag.embedder import OpenAIEmbedder
from app.rag.ingest import ingest_documents
from app.rag.store import ChromaStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def main(doc_dir: Path) -> None:
    """建库主流程。

    ★★ 注意这里直接 new 出具体实现类（OpenAIEmbedder、ChromaStore），
    而不是用 Protocol。因为脚本是"最顶层的装配点"——
    谁用谁、用哪个实现，在这里决定。
    Protocol 的价值是让 ingest_documents 不认识具体类，
    但总得有人来选具体类，那个人就是脚本入口。
    """
    settings = get_settings()

    # ---- 装配三个零件 ----
    embedder = OpenAIEmbedder(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.embed_model,
    )

    store = ChromaStore(
        persist_directory=str(settings.chroma_dir),
    )

    # ---- 调用摄取流水线 ----
    count = await ingest_documents(
        doc_dir=doc_dir,
        embedder=embedder,
        store=store,
        settings=settings,
    )

    if count > 0:
        logger.info("建库成功！共写入 %d 个分块，存储位置: %s", count, settings.chroma_dir)
    else:
        logger.warning("未写入任何分块，请检查 %s 目录下是否有 .md 或 .txt 文件", doc_dir)


# ★★ if __name__ == "__main__" 的意思：
# 只有直接运行这个脚本时才执行下面的代码。
# 如果别人 import 了这个文件（比如测试），不会自动跑建库。
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 RAG 知识库索引")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("knowledge_base"),
        help="知识库文档目录（默认: knowledge_base）",
    )
    args = parser.parse_args()

    if not args.dir.exists():
        logger.error("目录不存在: %s", args.dir)
        sys.exit(1)

    # ★★ asyncio.run() 是同步世界和异步世界的桥梁。
    # 脚本入口是同步的（if __name__ == "__main__"），
    # 但 ingest_documents 是 async 的。
    # asyncio.run() 创建一个事件循环，跑完 main() 再销毁。
    asyncio.run(main(args.dir))