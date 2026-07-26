from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import require_token
from app.api.routes_files import router as files_router
from app.config import get_settings
from app.config import Settings
from app.infra.event_bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时装配依赖，关闭时清理"""
    settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)

    yield


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
