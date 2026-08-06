"""WebSocket 网关：把 EventBus 事件流推给浏览器。"""
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.infra.event_bus import EventBus

router = APIRouter()


@router.websocket("/ws/{thread_id}")
async def ws_endpoint(websocket: WebSocket, thread_id: str):
    """订阅某会话的事件流，实时推到浏览器。

    晚连接也能收到历史缓冲事件（EventBus 的 fan-out + history 设计）。
    """
    await websocket.accept()
    bus: EventBus = websocket.app.state.event_bus

    try:
        async for event in bus.subscribe(thread_id):
            await websocket.send_json(asdict(event))   # AgentEvent → dict → JSON
    except WebSocketDisconnect:
        pass     # 客户端断开：正常，不报错
    finally:
        # 断开后清理该会话的所有订阅者队列 + 历史缓冲
        # ★ 注意：这会清掉整个会话的缓冲，若还有别的客户端连着会有影响
        bus.drop(thread_id)
