from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.config import Settings, get_settings

router = APIRouter(prefix="/files", tags=["files"])

# 允许上传的文件后缀
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".csv", ".json",
    ".pdf", ".doc", ".docx",
    ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg",
})

_MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024


def _session_dir(thread_id: str, settings: Settings) -> Path:
    """会话目录只由服务端从 thread_id 推导，绝不接受客户端传入。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", thread_id):
        raise HTTPException(400, "非法 thread_id")
    d = (settings.data_dir / "sessions" / thread_id).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_resolve(filename: str, session_dir: Path) -> Path:
    """将文件名解析为 session_dir 内的绝对路径，防止路径穿越。"""
    if not filename or not filename.strip():
        raise HTTPException(400, "文件名不能为空")

    target = (session_dir / filename).resolve()

    if not target.is_relative_to(session_dir.resolve()):
        raise HTTPException(403, "禁止访问会话目录以外的文件")

    return target


@router.get("/list")
async def list_files(
    thread_id: str = Query(...),
    settings: Settings = Depends(get_settings),
):
    session_dir = _session_dir(thread_id, settings)
    if not session_dir.is_dir():
        return {"files": []}

    files = [
        {"name": file.name, "size": file.stat().st_size}
        for file in session_dir.iterdir()
        if file.is_file()
    ]
    return {"files": files}


@router.get("/download")
async def download_file(
    filename: str = Query(...),
    thread_id: str = Query(...),
    settings: Settings = Depends(get_settings),
):
    session_dir = _session_dir(thread_id, settings)
    target = _safe_resolve(filename, session_dir)

    if not target.exists():
        raise HTTPException(404, f"文件不存在{filename}")

    return {"path": str(target)}


@router.post("/upload")
async def upload_file(
    thread_id: str = Query(...),
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    session_dir = _session_dir(thread_id, settings)
    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不允许改文件类型：{suffix}")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"文件大小超过限制{_MAX_UPLOAD_SIZE // 1024 // 1024} MB")

    target = _safe_resolve(file.filename, session_dir)

    if target.exists():
        stem = target.stem
        for i in range(1, 1000):
            candidate = target.with_name(f"{stem}_{i}{suffix}")
            if not candidate.exists():
                target = candidate
                break

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    return {"filename": file.filename, "size": len(content)}
