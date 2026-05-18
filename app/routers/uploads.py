"""Image upload endpoints for lot photos and user avatars.

Every uploaded byte stream goes through
``utils.images.validate_and_normalise_image`` first — Pillow ``verify``
rejects payloads that don't match a real image header, then a re-open +
save strips EXIF / ICC and re-encodes. The CPU-bound part runs on a
worker thread so a multi-megabyte file doesn't stall the event loop;
the disk write uses ``aiofiles`` for the same reason.
"""

import asyncio
import logging
import os
import uuid
from pathlib import PurePosixPath

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ALLOWED_IMAGE_TYPES, MAX_UPLOAD_SIZE, UPLOAD_DIR
from app.database import get_db
from app.models import User
from app.utils.images import validate_and_normalise_image
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user, require_verified_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["uploads"])


def _safely_remove(path: str) -> None:
    """Best-effort delete of an old upload file. Logs on failure
    instead of swallowing — a stale file blocks nothing functional, but
    silent failures hide a misconfigured UPLOAD_DIR."""
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as exc:
        logger.warning("Could not remove old upload %s: %s", path, exc)


async def _read_under_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Stream-read the upload into memory, bailing with 413 the
    moment the running total exceeds ``max_bytes``. Avoids slurping a
    multi-GB attacker-supplied file just to reject it."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(status_code=413, detail="Изображение слишком большое")
    return bytes(buf)


async def _accept_image(file: UploadFile) -> tuple[bytes, str]:
    """Validate the upload's bytes against the allowed image formats
    and return the sanitised payload + the file extension to use."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип изображения")

    raw = await _read_under_limit(file, MAX_UPLOAD_SIZE)
    sanitised, content_type, ext = await asyncio.to_thread(
        validate_and_normalise_image, raw
    )
    if content_type != file.content_type:
        # Magic bytes don't match the Content-Type the client claimed —
        # almost always means a payload disguised as an image.
        raise HTTPException(status_code=400, detail="Тип содержимого изображения не совпадает")
    return sanitised, ext


@router.post("/upload-image")
@limiter.limit("20/minute")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_verified_user),
):
    sanitised, ext = await _accept_image(file)
    filename = f"{uuid.uuid4().hex}.{ext}"
    dst_path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(dst_path, "wb") as out:
        await out.write(sanitised)
    return {"image_url": f"/static/uploads/{filename}"}


@router.post("/upload-avatar")
@limiter.limit("20/minute")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sanitised, ext = await _accept_image(file)

    if current_user.avatar_url:
        # PurePosixPath(...).name returns only the leaf component, never
        # ``..`` — so a tampered avatar_url like "/static/uploads/../../etc/passwd"
        # can't escape UPLOAD_DIR. Server writes the column today, but cheap insurance.
        old_filename = PurePosixPath(current_user.avatar_url).name
        if old_filename and old_filename != "..":
            _safely_remove(os.path.join(UPLOAD_DIR, old_filename))

    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    dst_path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(dst_path, "wb") as out:
        await out.write(sanitised)

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
        # PurePosixPath(...).name returns only the leaf component, never
        # ``..`` — so a tampered avatar_url like "/static/uploads/../../etc/passwd"
        # can't escape UPLOAD_DIR. Server writes the column today, but cheap insurance.
        old_filename = PurePosixPath(current_user.avatar_url).name
        if old_filename and old_filename != "..":
            _safely_remove(os.path.join(UPLOAD_DIR, old_filename))
        current_user.avatar_url = None
        await db.commit()
    return {"ok": True}
