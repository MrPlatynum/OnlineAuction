"""Image upload endpoints for lot photos and user avatars.

Every uploaded byte stream goes through
``utils.images.validate_and_normalise_image`` first - Pillow ``verify``
rejects payloads that don't match a real image header, then a re-open +
save strips EXIF / ICC and re-encodes. The CPU-bound part runs on a
worker thread so a multi-megabyte file doesn't stall the event loop;
the disk write uses ``aiofiles`` for the same reason.
"""

import asyncio
import logging
import os
import uuid
from datetime import timedelta
from pathlib import PurePosixPath

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ALLOWED_IMAGE_TYPES, MAX_UPLOAD_SIZE, UPLOAD_DIR
from app.database import get_db
from app.models import User
from app.utils.images import validate_and_normalise_image
from app.utils.rate_limit import limiter
from app.utils.security import get_current_user, require_verified_user
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# Per-user rolling cap on accepted bytes. 50 MB / 24 h is generous
# for legitimate sellers uploading lot photos (5 MB × 10 lots) but
# stops the 8 MB × 20/min worst case ramp from filling the disk.
_UPLOAD_QUOTA_BYTES = 50 * 1024 * 1024
_UPLOAD_QUOTA_WINDOW = timedelta(hours=24)

router = APIRouter(prefix="/api", tags=["uploads"])


async def _check_upload_quota(db: AsyncSession, user_id: int, size: int) -> None:
    """Enforce the per-user rolling 24h upload-byte cap.

    Reads + mutates the user row under a row lock so two concurrent
    /upload-image calls can't both observe pre-charge state and slip
    past the cap. Resets the window when the prior start drifted out
    of range. Caller still needs to commit the session so the bump
    sticks even if the file write later fails - that's intentional:
    a partial-write attacker shouldn't be able to recharge their
    budget by cancelling the request mid-upload.
    """
    user = (
        await db.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    now = utcnow()
    start = user.upload_window_start
    if start is None or now - start >= _UPLOAD_QUOTA_WINDOW:
        user.upload_window_start = now
        user.upload_bytes_window = 0

    projected = (user.upload_bytes_window or 0) + size
    if projected > _UPLOAD_QUOTA_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Превышен суточный лимит загрузок "
                f"({_UPLOAD_QUOTA_BYTES // (1024 * 1024)} МБ)."
            ),
        )
    user.upload_bytes_window = projected


def _safely_remove(path: str) -> None:
    """Best-effort delete of an old upload file. Logs on failure
    instead of swallowing - a stale file blocks nothing functional, but
    silent failures hide a misconfigured UPLOAD_DIR."""
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as exc:
        logger.warning("Could not remove old upload %s: %s", path, exc)


def _remove_avatar_file(avatar_url: str | None) -> None:
    """Best-effort cleanup of a previous avatar before writing a new
    one. Walks the leaf name through ``PurePosixPath(...).name`` so a
    tampered DB value like ``"/static/uploads/../../etc/passwd"`` can't
    escape ``UPLOAD_DIR`` (the leaf component is never ``..``).
    Defensive: the column is server-set today, but cheap insurance."""
    if not avatar_url:
        return
    leaf = PurePosixPath(avatar_url).name
    if leaf and leaf != "..":
        _safely_remove(os.path.join(UPLOAD_DIR, leaf))


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
        # Magic bytes don't match the Content-Type the client claimed -
        # almost always means a payload disguised as an image.
        raise HTTPException(status_code=400, detail="Тип содержимого изображения не совпадает")
    return sanitised, ext


@router.post("/upload-image")
@limiter.limit("20/minute")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_verified_user),
    db: AsyncSession = Depends(get_db),
):
    sanitised, ext = await _accept_image(file)
    await _check_upload_quota(db, current_user.id, len(sanitised))
    # Commit the quota bump *before* the disk write so a cancelled or
    # failed write doesn't roll back the budget - otherwise an attacker
    # can drop the connection mid-upload and recharge for free, defeating
    # the rolling 24h cap. A successful quota commit + later disk failure
    # is the correct trade-off: the user "paid" budget for a request that
    # didn't land.
    await db.commit()
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
    await _check_upload_quota(db, current_user.id, len(sanitised))
    # Commit the quota bump before the disk write - see upload_image for
    # the partial-write recharge attack this guards against.
    await db.commit()

    _remove_avatar_file(current_user.avatar_url)

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
        _remove_avatar_file(current_user.avatar_url)
        current_user.avatar_url = None
        await db.commit()
    return {"ok": True}
