"""probe_day9.py —— Day 9 端到端验收：RAG 检索 + 三链路降级。

运行：python -m scripts.probe_day9

★★ 为什么用脚本而不是 HTTP：
HTTP 提交任务是异步的（立即返回 thread_id，结果走 WebSocket 推），
验收时我们要看的是"完整调用链长什么样"，直接 ainvoke 一把梭最直观。
生产走 HTTP，调试走脚本，两套并存不矛盾。
"""
import asyncio
import logging
import uuid

from app.agents.deps import AgentDeps
from app.agents.context import RunContext
from app.agents.main_agent import build_main_agent
from app.config import get_settings
from app.infra.checkpoint import build_checkpoint
from app.infra.event_bus import EventBus
from app.rag.embedder import OpenAIEmbedder
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.services.session_service import SessionService

# 只看我们关心的日志，把 httpx 那些噪音压下去
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)

RUN_ID = uuid.uuid4().hex[:8]

# ★★ 两个问题的设计是有讲究的，不是随便挑的：
#   Q1 知识库必然命中 → 验证正常链路
#   Q2 知识库必然零命中（文档里只有药品存储规范，没有市场数据）→ 验证降级链路
# 验收要同时覆盖"走通"和"走不通时怎么办"，只测前者等于没测。
QUESTIONS = [
    (f"kb-hit-{RUN_ID}", "阿莫西林的存储温度要求是什么？"),
    (f"kb-miss-{RUN_ID}", "阿司匹林的存储温度要求是什么？"),
]


def _print_message(msg) -> None:
    """把一条消息打印成人能读的形式。"""
    role = type(msg).__name__          # HumanMessage / AIMessage / ToolMessage
    tool_calls = getattr(msg, "tool_calls", None)

    if tool_calls:
        for tc in tool_calls:
            # ★★ 这一行是验收的关键观察点：
            # 主 Agent 委托子 Agent 时，会打出一个工具调用，
            # 名字里能看到派给了谁（task / knowledge-base / network-search）
            print(f"  🔧 [{role}] 调用工具: {tc['name']}")
            print(f"      参数: {str(tc['args'])[:300]}")
    elif role == "ToolMessage":
        name = getattr(msg, "name", "?")
        content = str(msg.content)
        print(f"  📥 [工具返回 {name}] {content[:500]}")
    elif msg.content:
        print(f"  💬 [{role}] {str(msg.content)[:1500]}")


async def ask(agent, sessions: SessionService, thread_id: str, query: str) -> None:
    print("\n" + "=" * 70)
    print(f"❓ 问题: {query}")
    print("=" * 70)

    ctx = RunContext(thread_id=thread_id, session_dir=sessions.dir_for(thread_id=thread_id))
    config = {"configurable": {"thread_id": thread_id}}

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": query}]},
        config=config,
        context=ctx,          # ★★ context_schema=RunContext，必须传
    )

    # ★★ HITL 中断检查：如果模型试图查数据库，会在这里停住等审批。
    # 今天这两个问题不该碰数据库，一旦出现说明主 Agent 路由错了。
    if "__interrupt__" in result:
        print("  ⚠️ 任务被 HITL 中断（模型试图执行 SQL）——今天的问题不该走到这里")
        print(f"     {result['__interrupt__']}")
        return

    for msg in result["messages"]:
        _print_message(msg)


async def main() -> None:
    settings = get_settings()

    # ---- 跟 main.py lifespan 一样的装配，只是不起 web 服务 ----
    bus = EventBus(settings.event_queue_maxsize)
    sessions = SessionService(settings)

    embedder = OpenAIEmbedder(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.embed_model,
    )
    store = ChromaStore(persist_directory=str(settings.chroma_dir))
    retriever = Retriever(embedder, store)

    checkpointer = await build_checkpoint(settings)

    agent = build_main_agent(
        # ★★ db=None：今天不测数据库链路，pharma_db 还没建。
        # 主 Agent 不该把这两个问题派给 database-query，如果派了说明
        # prompts.yml 里三个 description 的边界没划清楚——那是 Day 5 的活。
        AgentDeps(settings=settings, bus=bus, db=None, retriever=retriever),
        checkpointer=checkpointer,
    )

    for thread_id, query in QUESTIONS:
        await ask(agent, sessions, thread_id, query)

    print("\n" + "=" * 70)
    print("探测结束。验收看两点：")
    print("  1. Q1 是否调了 rag_search，返回里有没有【来源: xxx.md, 相关度: 0.xx】")
    print("  2. Q2 是否在知识库零命中后，自动改调了 network-search")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())