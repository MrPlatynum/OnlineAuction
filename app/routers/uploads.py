import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ALLOWED_IMAGE_TYPES, MAX_UPLOAD_SIZE, UPLOAD_DIR
from app.database import get_db
from app.models import User
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user

router = APIRouter(prefix="/api", tags=["uploads"])


@router.post("/upload-image")
@limiter.limit("20/minute")
async def upload_image(request: Request, file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    ext = ALLOWED_IMAGE_TYPES[file.content_type]
    filename = f"{uuid.uuid4().hex}.{ext}"
    dst_path = os.path.join(UPLOAD_DIR, filename)

    size = 0
    with open(dst_path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                os.remove(dst_path)
                raise HTTPException(status_code=413, detail="Image too large")
            out.write(chunk)

    return {"image_url": f"/static/uploads/{filename}"}


@router.post("/upload-avatar")
@limiter.limit("20/minute")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    ext = ALLOWED_IMAGE_TYPES[file.content_type]
    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    dst_path = os.path.join(UPLOAD_DIR, filename)

    if current_user.avatar_url:
        old_filename = current_user.avatar_url.split("/")[-1]
        old_path = os.path.join(UPLOAD_DIR, old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    size = 0
    with open(dst_path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                os.remove(dst_path)
                raise HTTPException(status_code=413, detail="Image too large")
            out.write(chunk)

    avatar_url = f"/static/uploads/{filename}"
    current_user.avatar_url = avatar_url
    await db.commit()

    return {"avatar_url": avatar_url}


@router.delete("/upload-avatar")
async def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.avatar_url:
        old_filename = current_user.avatar_url.split("/")[-1]
        old_path = os.path.join(UPLOAD_DIR, old_filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
        current_user.avatar_url = None
        await db.commit()
    return {"ok": True}
