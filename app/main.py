import logging                                    # ★★ 提到顶层，别再写在 except 里面
from contextlib import asynccontextmanager

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
from app.rag.embedder import OpenAIEmbedder
from app.rag.retriever import Retriever
from app.rag.store import ChromaStore
from app.services.session_service import SessionService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)

    db = Database(settings)
    try:
        await db.connect()
    except Exception as e:
        logger.warning("数据库连接池建立失败: %s", e)
        db = None
    app.state.db = db


    try:
        embedder = OpenAIEmbedder(
            base_url=settings.llm_base_url,      # 复用主模型的 base_url（同一家通义）
            api_key=settings.llm_api_key,
            model=settings.embed_model,          # text-embedding-v3
        )
        store = ChromaStore(persist_directory=str(settings.chroma_dir))
        retriever = Retriever(embedder, store)
        logger.info("RAG 检索器已装配，向量库路径: %s", settings.chroma_dir)
    except Exception as e:
        logger.warning("RAG 检索器装配失败，知识库子 Agent 将降级: %s", e)
        retriever = None
    app.state.retriever = retriever

    app.state.checkpointer = await build_checkpoint(settings)
    agent = build_main_agent(
        AgentDeps(
            settings=settings,
            bus=app.state.event_bus,
            db=db,
            retriever=retriever,                 # ★★ Day 1 预留的字段，今天填上
        ),
        checkpointer=app.state.checkpointer,
    )
    app.state.agent = agent


    sessions = SessionService(settings)
    app.state.sessions = sessions
    app.state.task_service = TaskService(
        agent=agent,
        bus=app.state.event_bus,
        sessions=sessions,
        settings=settings,
    )

    yield

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