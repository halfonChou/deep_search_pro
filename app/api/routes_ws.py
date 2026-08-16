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
        # ★ 这里什么都不用做。
        # EventBus.subscribe() 是个 async generator，它自己的 finally 里已经
        # _unsubscribe 掉了本连接的队列 —— 精确、只影响自己。
        # 原来这里调 bus.drop(thread_id)，会把**整个会话**的订阅者和历史一起清掉：
        #   - 同一会话开了两个页面时，关掉一个，另一个也瞎了
        #   - 历史被清掉，后来的连接看不到回放
        pass
