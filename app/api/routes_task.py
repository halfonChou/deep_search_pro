"""任务生命周期 HTTP 路由：提交 / 状态 / 取消 / 审批 / 待办清单读写。"""
from fastapi import APIRouter, Body, HTTPException, Request

from app.services.task_service import TaskService

router = APIRouter(prefix="/task", tags=["task"])


def _get_task_service(request: Request) -> TaskService:
    """从 app.state 拿 TaskService（main.py lifespan 里装配好的）。"""
    svc = getattr(request.app.state, "task_service", None)
    if svc is None:
        raise HTTPException(503, "TaskService 未初始化")
    return svc


def _get_agent(request: Request):
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(503, "Agent 未初始化")
    return agent


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
async def decide_task(thread_id: str, request: Request, decisions=Body(...)):
    """HITL 审批决策。

    ★ 请求体接受两种形态（不能写死成 list[dict]，多中断时会 422）：

      单个中断：  [{"type": "approve"}]
      多个中断：  {"<中断id>": [{"type": "approve"}], "<中断id2>": [{"type": "reject", ...}]}

    主 Agent 一轮里派出多个子 Agent 时会同时挂起多个 interrupt，
    LangGraph 要求恢复时逐个指定 id，所以第二种形态是必须支持的。
    """
    if not isinstance(decisions, (list, dict)) or not decisions:
        raise HTTPException(400, "decisions 必须是非空的列表或 {中断id: 决策} 字典")

    svc = _get_task_service(request)
    await svc.decide(thread_id, decisions)
    return {"thread_id": thread_id, "decided": True,
            "interrupts": len(decisions) if isinstance(decisions, dict) else 1}


# --------------------------------------------------------------------------
# 待办清单（todos）读写：前端「修改任务」功能的后端支撑
# --------------------------------------------------------------------------

def _normalize_todos(raw) -> list[dict]:
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, dict):
            content = item.get("content") or item.get("task") or ""
            status = item.get("status", "pending")
        else:
            content = getattr(item, "content", None) or str(item)
            status = getattr(item, "status", "pending")
        content = str(content).strip()
        if not content:
            continue
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        out.append({"content": content, "status": status})
    return out


@router.get("/{thread_id}/todos")
async def get_todos(thread_id: str, request: Request):
    """读取该会话当前的待办清单（来自 checkpointer 里的图状态）。"""
    agent = _get_agent(request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await agent.aget_state(config)
    except Exception as e:
        raise HTTPException(500, f"读取图状态失败: {e}") from e

    values = getattr(snapshot, "values", None) or {}
    return {"thread_id": thread_id, "todos": _normalize_todos(values.get("todos"))}


@router.put("/{thread_id}/todos")
async def put_todos(thread_id: str, request: Request, todos: list[dict] = Body(..., embed=True)):
    """覆盖写该会话的待办清单。

    用途：任务跑到一半，人觉得 Agent 的计划不对，直接在前端改完推回去；
    下一步 Agent 从 checkpoint 恢复时读到的就是改过的计划。
    """
    agent = _get_agent(request)
    clean = _normalize_todos(todos)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        await agent.aupdate_state(config, {"todos": clean})
    except Exception as e:
        raise HTTPException(500, f"写入图状态失败: {e}") from e

    bus = getattr(request.app.state, "event_bus", None)
    if bus is not None:
        from app.agents.events import AgentEvent
        await bus.publish(
            thread_id,
            AgentEvent(
                type="plan_update", thread_id=thread_id,
                message="计划已被人工修改",
                data={"todos": clean, "node": "human"},
            ),
        )

    return {"thread_id": thread_id, "todos": clean}
