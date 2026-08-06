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
from app.services.session_service import SessionService
from app.services.task_service import TaskService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)

    db = Database(settings)
    try:
        await db.connect()
    except Exception as e:
        import logging
        logging.warning("数据库连接池建立失败: %s", e)
        db = None
    app.state.db = db

    app.state.checkpointer = await build_checkpoint(settings)
    agent = build_main_agent(
        AgentDeps(settings=settings, bus=app.state.event_bus, db=db),
        checkpointer=app.state.checkpointer,
    )
    app.state.agent = agent

    # Day 4：装配 SessionService + TaskService
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
