from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.infra.event_bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时装配依赖，关闭时清理"""
    settings = get_settings()
    app.state.settings = settings
    app.state.event_bus = EventBus(settings.event_queue_maxsize)

    yield


def create_app()->FastAPI:
    """应用工厂，创建并且配置fastapi实例"""
    settings = get_settings()
    app = FastAPI(title="DeepSearch Pro", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
