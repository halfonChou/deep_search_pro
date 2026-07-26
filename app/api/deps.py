from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings


async def require_token(
        authorization: str | None = Header(None),
        settings: Settings = Depends(get_settings),
):
    if not settings.api_token:
        return

    if not authorization or authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="unauthorized!!!!!!!")
