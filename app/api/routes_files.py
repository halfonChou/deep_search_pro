from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

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
    # ★★ 目录名必须是 "session"（单数），和 SessionService.dir_for 保持一致。
    # 原来这里写的是 "sessions"（复数），而 generate_markdown 走 SessionService
    # 落到 data/session/<tid>/ —— 两边对不上，导致 /files/list 永远返回空列表，
    # 报告生成了却在前端看不到。cleanup_expired 用的也是单数。
    d = (settings.data_dir / "session" / thread_id).resolve()
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

# @router.get("/list")
# async def list_files(session_dir: Path = Query(...)):
#     resolved = session_dir.resolve()
#     if not resolved.is_dir():
#         return {"files": []}
#
#     files = [
#         {"name": file.name, "size": file.stat().st_size}
#         for file in resolved.iterdir()
#         if file.is_file()
#     ]
#     return {"files": files}


@router.get("/download")
async def download_file(
    filename: str = Query(...),
    thread_id: str = Query(...),
    settings: Settings = Depends(get_settings),
):
    """下载文件本体。

    原来这里 return {"path": str(target)} —— 只回了一个**服务端本地路径**，
    浏览器和前端都拿不到文件内容，等于没实现下载。改成 FileResponse 回真正的字节流。
    """
    session_dir = _session_dir(thread_id, settings)
    target = _safe_resolve(filename, session_dir)

    if not target.exists() or not target.is_file():
        raise HTTPException(404, f"文件不存在：{filename}")

    return FileResponse(
        path=target,
        filename=target.name,
        media_type="application/octet-stream",
    )


@router.get("/content")
async def file_content(
    filename: str = Query(...),
    thread_id: str = Query(...),
    settings: Settings = Depends(get_settings),
):
    """读文本文件内容，供前端直接渲染（报告预览用）。

    和 /download 分开：download 给"另存为"，content 给"在页面里显示"。
    只允许纯文本类型，二进制文件走 download。
    """
    session_dir = _session_dir(thread_id, settings)
    target = _safe_resolve(filename, session_dir)

    if not target.exists() or not target.is_file():
        raise HTTPException(404, f"文件不存在：{filename}")

    if target.suffix.lower() not in {".md", ".txt", ".csv", ".json"}:
        raise HTTPException(415, f"不是可预览的文本类型：{target.suffix}")

    if target.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(413, "文件超过 2MB，请改用下载")

    return {
        "name": target.name,
        "size": target.stat().st_size,
        "text": target.read_text(encoding="utf-8", errors="replace"),
    }


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

    size, chunks = 0, []
    while chunk := await file.read(1 << 20):
        size += len(chunk)
        if size > _MAX_UPLOAD_SIZE:
            raise HTTPException(413, "文件过大")
        chunks.append(chunk)


    target = _safe_resolve(file.filename, session_dir)

    if target.exists():
        stem = target.stem
        for i in range(1, 1000):
            candidate = target.with_name(f"{stem}_{i}{suffix}")
            if not candidate.exists():
                target = candidate
                break

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"".join(chunks))

    return {"filename": file.filename, "size": size}
