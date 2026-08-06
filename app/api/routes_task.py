"""任务生命周期 HTTP 路由：提交 / 状态 / 取消 / 审批。"""
from fastapi import APIRouter, HTTPException, Request

from app.services.task_service import TaskService

router = APIRouter(prefix="/task", tags=["task"])


def _get_task_service(request: Request) -> TaskService:
    """从 app.state 拿 TaskService（main.py lifespan 里装配好的）。"""
    svc = getattr(request.app.state, "task_service", None)
    if svc is None:
        raise HTTPException(503, "TaskService 未初始化")
    return svc


@router.post("")
async def submit_task(query: str, thread_id: str, request: Request):
    """提交任务：立即返回 thread_id。"""
    svc = _get_task_service(request)
    await svc.submit(query=query, thread_id=thread_id)
    return {"thread_id": thread_id, "state": svc.status(thread_id)["state"]}


@router.get("/{thread_id}")
async def task_status(thread_id: str, request: Request):
    """查任务状态。"""
    svc = _get_task_service(request)
    return svc.status(thread_id)


@router.delete("/{thread_id}")
async def cancel_task(thread_id: str, request: Request):
    """取消任务。"""
    svc = _get_task_service(request)
    ok = await svc.cancel(thread_id)
    return {"thread_id": thread_id, "cancelled": ok, "state": svc.status(thread_id)["state"]}


@router.post("/{thread_id}/decision")
async def decide_task(thread_id: str, decisions: list[dict], request: Request):
    """HITL 审批决策（Day 7 填实现）。"""
    svc = _get_task_service(request)
    await svc.decide(thread_id, decisions)
    return {"thread_id": thread_id, "decided": True}
