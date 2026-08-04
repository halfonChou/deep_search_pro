from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.deps import AgentDeps
from app.agents.main_agent import build_main_agent
from app.api.deps import require_token
from app.api.routes_files import router as files_router
from app.config import Settings, get_settings
from app.infra.checkpoint import build_checkpoint
from app.infra.db import Database
from app.infra.event_bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时装配依赖，关闭时清理。"""
    settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)

    # 惰性建数据库连接池：连不上不阻止启动，只记警告
    db = Database(settings)
    try:
        await db.connect()
    except Exception as e:
        import logging
        logging.warning("数据库连接池建立失败，数据库功能不可用: %s", e)
        db = None
    app.state.db = db

    # ---- 临时注释：B5 攻防实验不需要 agent ----
    app.state.checkpointer = await build_checkpoint(settings)
    app.state.agent = build_main_agent(
        AgentDeps(settings=settings, bus=app.state.event_bus, db=db),
        checkpointer=app.state.checkpointer
    )

    yield

    # 退出时关闭连接池
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
    return app
