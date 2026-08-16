"""检查 ChromaStore 是否还在阻塞事件循环。

原理：起一个「心跳」协程，每 50 毫秒打印一次。
同时反复调用 store.query()。

- 没改好（同步阻塞）：查询期间心跳完全停住，出现一大段空白
- 改好了（to_thread）：心跳全程匀速，一次都不断

用法（项目根目录下）：
    python scripts/check_blocking.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.rag.store import ChromaStore  # noqa: E402

QUERY_ROUNDS = 30       # 查询次数，放大效果用
HEARTBEAT_INTERVAL = 0.05


async def heartbeat(stop: asyncio.Event, gaps: list[float]):
    """每 50ms 跳一次，记录相邻两次的实际间隔。"""
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now
        print(".", end="", flush=True)


async def main() -> int:
    settings = get_settings()
    store = ChromaStore(persist_directory=str(settings.chroma_dir))

    # 从库里偷一条向量出来当查询向量，省得调 embedding API
    peek = store._collection.peek(1)
    embeddings = peek.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        print("❌ 向量库是空的，先跑 python scripts/build_index.py 建索引")
        return 2
    vector = list(embeddings[0])
    print(f"向量维度 {len(vector)}，开始测试……\n")

    stop = asyncio.Event()
    gaps: list[float] = []
    hb = asyncio.create_task(heartbeat(stop, gaps))

    await asyncio.sleep(0.3)                 # 让心跳先稳定跳几下
    t0 = time.perf_counter()
    for _ in range(QUERY_ROUNDS):
        await store.query(vector, top_k=5)
    query_elapsed = time.perf_counter() - t0

    await asyncio.sleep(0.3)
    stop.set()
    await hb

    if not gaps:
        print("\n❌ 心跳一次都没跳成，说明事件循环从头堵到尾")
        return 1

    worst = max(gaps)
    print(f"\n\n{QUERY_ROUNDS} 次查询共耗时 {query_elapsed * 1000:.0f} ms")
    print(f"心跳跳了 {len(gaps)} 次，最大停顿 {worst * 1000:.0f} ms"
          f"（正常应该在 {HEARTBEAT_INTERVAL * 1000:.0f} ms 上下）")

    # 阈值：单次停顿超过 3 倍心跳间隔，就说明事件循环被占住过
    if worst > HEARTBEAT_INTERVAL * 3:
        print("\n❌ 还在阻塞。检查 app/rag/store.py 的 query 是不是漏了 asyncio.to_thread，")
        print("   或者写成了 to_thread(self._collection.query(...)) —— 括号要换成逗号。")
        return 1

    print("\n✅ 没有阻塞，改对了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
