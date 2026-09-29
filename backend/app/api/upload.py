from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import MenuEditor
from app.core.config import settings

router = APIRouter(prefix="/admin/upload", tags=["admin:upload"])


class ImageDelete(BaseModel):
    url: str

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


@router.post("/image", status_code=status.HTTP_201_CREATED)
async def upload_image(
    _: MenuEditor,
    file: UploadFile = File(...),
) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Допустимые форматы: {', '.join(sorted(ALLOWED))}",
        )

    data = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл больше {settings.max_upload_mb} МБ",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")

    settings.images_path.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}{ext}"
    path = settings.images_path / name
    path.write_bytes(data)

    return {
        "url": f"/static/{name}",
        "filename": name,
        "size": len(data),
        "content_type": file.content_type,
    }


@router.delete("/image")
def delete_image(payload: ImageDelete, _: MenuEditor) -> dict:
    name = Path(payload.url).name
    path = (settings.images_path / name).resolve()
    if path.parent == settings.images_path.resolve() and path.exists():
        path.unlink()
    return {"ok": True}
