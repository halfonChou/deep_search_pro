"""FastAPI 应用入口。

Day 11 更新：
- 集成结构化日志（logging_config）
- 后台清理过期会话
- LangSmith 追踪（通过环境变量 LANGSMITH_TRACING=true 自动生效）
"""

import asyncio
import logging
import warnings
from contextlib import asynccontextmanager

# LangGraph 往 checkpoint 里存 RunContext 时，Pydantic 的 schema 标的是 None，
# 实际塞的是我们的 dataclass，于是每存一次就唠叨一句。功能无影响，纯噪音，屏蔽掉。
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.deps import AgentDeps
from app.agents.main_agent import build_main_agent
from app.api.deps import require_token
from app.api.routes_files import router as files_router
from app.api.routes_task import router as task_router
from app.api.routes_ws import router as ws_router
from app.config import Settings, get_settings
from app.infra.checkpoint import build_checkpoint
from app.infra.db import Database
from app.infra.event_bus import EventBus
from app.logging_config import setup_logging
from app.rag.embedder import OpenAIEmbedder
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.services.session_service import SessionService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


async def _cleanup_loop(sessions: SessionService, ttl_hours: int):
    """后台协程：每小时清理一次过期会话目录。"""
    while True:
        try:
            removed = await sessions.cleanup_expired(ttl_hours)
            if removed:
                logger.info("清理了 %d 个过期会话目录", removed)
        except Exception:
            logger.exception("会话清理失败")
        await asyncio.sleep(3600)  # 每小时检查一次


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Day 11：初始化结构化日志
    setup_logging()

    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)

    # ---- 数据库 ----
    db = Database(settings)
    try:
        await db.connect()
    except Exception as e:
        logger.warning("数据库连接池建立失败: %s", e)
        db = None
    app.state.db = db

    # ---- RAG 检索器 ----
    try:
        embedder = OpenAIEmbedder(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.embed_model,
        )
        store = ChromaStore(persist_directory=str(settings.chroma_dir))
        retriever = Retriever(embedder, store)
        logger.info("RAG 检索器已装配，向量库路径: %s", settings.chroma_dir)
    except Exception as e:
        logger.warning("RAG 检索器装配失败，知识库子 Agent 将降级: %s", e)
        retriever = None
    app.state.retriever = retriever

    # ---- 会话服务（必须在 agent 之前创建，report_tools 依赖它）----
    sessions = SessionService(settings)
    app.state.sessions = sessions

    # ---- Checkpointer ----
    app.state.checkpointer = await build_checkpoint(settings)

    # ---- 主 Agent ----
    agent = build_main_agent(
        AgentDeps(
            settings=settings,
            bus=app.state.event_bus,
            db=db,
            retriever=retriever,
            sessions=sessions,
        ),
        checkpointer=app.state.checkpointer,
    )
    app.state.agent = agent

    # ---- TaskService ----
    app.state.task_service = TaskService(
        agent=agent,
        bus=app.state.event_bus,
        sessions=sessions,
        settings=settings,
    )

    # ---- Day 11：启动后台清理协程 ----
    cleanup_task = asyncio.create_task(
        _cleanup_loop(sessions, settings.session_ttl_hours)
    )

    yield

    # ---- 关闭 ----
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    if app.state.db is not None:
        await app.state.db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()
    app = FastAPI(title="DeepSearch Pro", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(files_router, dependencies=[Depends(require_token)])
    app.include_router(task_router, dependencies=[Depends(require_token)])
    app.include_router(ws_router)
    return app
