from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

router = APIRouter(prefix="/files", tags=["files"])

# 允许上传的文件后缀
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".csv", ".json",
    ".pdf", ".doc", ".docx",
    ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg",
})

_MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024

def _safe_resolve(filename: str, session_dir: Path) -> Path:
    """将文件名解析为 session_dir 内的绝对路径，防止路径穿越。

    Raises:
        HTTPException 403: 路径逃逸出 session_dir。
        HTTPException 400: 文件名为空。
    """
    if not filename or not filename.strip():
        raise HTTPException(400, "文件名不能为空")

    target = (session_dir / filename).resolve()

    if not target.is_relative_to(session_dir.resolve()):
        raise HTTPException(403,"禁止访问会话目录以外的文件")

    return target

@router.get("/list")
async def list_files(session_dir: Path = Query(...)):
    resolved = session_dir.resolve()
    if not resolved.is_dir():
        return {"files":[]}

    files = [
        {"name": file.name, "size": file.stat().st_size}
        for file in resolved.iterdir()
        if file.is_file()
    ]
    return {"files":files}

@router.get("/download")
async def download_file(filename:str = Query(...), session_dir: Path = Query(...)):
    target = _safe_resolve(filename, session_dir)

    if not target.exists():
        raise HTTPException(404, f"文件不存在{filename}")

    return {"path": str(target)}

@router.post("/upload")
async def upload_file(session_dir:Path = Query(...), file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不允许改文件类型：{suffix}")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"文件大小超过限制{_MAX_UPLOAD_SIZE // 1024 // 1024} MB")

    target = _safe_resolve(file.filename, session_dir)

    if target.exists():
        stem = target.stem
        for i in range(1,1000):
            candidate = target.with_name(f"{stem}_{i}{suffix}")
            if not candidate.exists():
                target = candidate
                break

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    return {"filename":file.filename, "size":len(content)}
