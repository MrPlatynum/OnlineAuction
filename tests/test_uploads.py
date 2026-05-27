"""Upload validation tests.

Covers the magic-byte check: a real PIL-encoded PNG goes through; raw
bytes that fake the Content-Type header but aren't actually an image
are rejected with 400. Includes a Content-Type-vs-magic-byte mismatch
test so we don't accept a real PNG sent as ``image/jpeg``.
"""

import io
import os

import pytest_asyncio
from PIL import Image


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(255, 128, 64)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(64, 128, 255)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest_asyncio.fixture(autouse=True)
async def _clean_uploads():
    """Each test starts with a clean uploads dir and is responsible
    for its own teardown via the test code path."""
    from app.config import UPLOAD_DIR

    yield UPLOAD_DIR
    for name in os.listdir(UPLOAD_DIR):
        try:
            os.remove(os.path.join(UPLOAD_DIR, name))
        except OSError:
            pass


async def test_valid_png_accepted(client, registered_user):
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"].startswith("/static/uploads/")


async def test_valid_jpeg_accepted(client, registered_user):
    files = {"file": ("test.jpg", _jpeg_bytes(), "image/jpeg")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 200, r.text


async def test_payload_disguised_as_image_rejected(client, registered_user):
    """Random bytes with ``image/jpeg`` Content-Type - historically
    this passed the header-only check. The magic-byte verify must
    reject it as 'not a valid image'."""
    payload = b"#!/bin/sh\necho pwned\n" + b"\x00" * 256
    files = {"file": ("evil.jpg", payload, "image/jpeg")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 400, r.text


async def test_content_type_mismatch_rejected(client, registered_user):
    """Real PNG bytes sent with ``image/jpeg`` Content-Type - the
    server should refuse rather than silently accept the lie."""
    files = {"file": ("trick.jpg", _png_bytes(), "image/jpeg")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 400, r.text


async def test_unsupported_content_type_rejected(client, registered_user):
    """GIF / SVG / others not in the allow-list are rejected before
    Pillow even sees the bytes."""
    files = {"file": ("a.gif", b"GIF89a", "image/gif")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 400, r.text


async def test_upload_image_requires_auth(client):
    """``/upload-image`` used to accept anonymous uploads, letting any
    visitor consume disk + cycle through the image validator. Both
    ``/upload-image`` and ``/upload-avatar`` now require a bearer token."""
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    r = await client.post("/api/upload-image", files=files)
    assert r.status_code == 401, r.text


async def test_upload_image_authed_succeeds(client, registered_user):
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    r = await client.post(
        "/api/upload-image", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["image_url"].startswith("/static/uploads/")


async def test_upload_quota_blocks_after_window_exhausted(
    client, registered_user, monkeypatch
):
    """A user pushing past the rolling-24h byte cap is rejected with
    413; the surrounding /upload-image rate limit only meters frequency,
    not total volume, so without the byte quota a verified user could
    fill the disk indefinitely with 8 MB images at 20/min."""
    from app.routers import uploads as uploads_mod

    # Shrink the quota to 1 byte - any upload at all crosses it.
    monkeypatch.setattr(uploads_mod, "_UPLOAD_QUOTA_BYTES", 1)

    headers = registered_user["headers"]
    files = {"file": ("a.png", _png_bytes((48, 48)), "image/png")}
    r = await client.post("/api/upload-image", files=files, headers=headers)
    assert r.status_code == 413, r.text
    assert "лимит" in r.json()["detail"].lower()


async def test_upload_quota_persists_when_disk_write_fails(
    client, registered_user, monkeypatch
):
    """A failed (or cancelled) disk write used to roll the quota bump
    back together with the rest of the session because db.commit() ran
    *after* aiofiles.open(...).write(). An attacker dropping TCP
    mid-write could therefore recharge their budget for free, defeating
    the rolling 24h byte cap. The fix commits the quota first; this
    test asserts the bump survives a disk-side failure.
    """
    import aiofiles

    from sqlalchemy import select

    from app import database as _db_module
    from app.models import User

    headers = registered_user["headers"]
    user_id = registered_user["user"]["id"]

    # Force aiofiles.open to raise so the handler bails after _check_upload_quota
    # has mutated upload_bytes_window but before the second mutation (avatar
    # URL) or the response. With the pre-fix ordering, no commit would have
    # run and the quota bump would have rolled back via get_db's teardown.
    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(aiofiles, "open", _boom)

    files = {"file": ("a.png", _png_bytes((32, 32)), "image/png")}
    # The OSError propagates out of the route - TestClient re-raises it
    # by default. Either outcome (re-raise or 500) leaves the same state
    # behind: get_db's teardown closed the session. The fix's contract is
    # that the quota was committed *before* the disk write, so closing
    # the session does not unwind the bump.
    import pytest

    with pytest.raises(OSError):
        await client.post("/api/upload-image", files=files, headers=headers)

    async with _db_module.SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        assert user.upload_bytes_window and user.upload_bytes_window > 0, (
            f"quota bump was rolled back by the disk failure "
            f"(upload_bytes_window={user.upload_bytes_window}) - attacker can recharge"
        )


async def test_decompression_bomb_rejected(client, registered_user, monkeypatch):
    """A valid PNG header with declared dimensions above
    Image.MAX_IMAGE_PIXELS must be refused instead of decoded - the
    historical default would let a 50 KB upload pin a worker on a
    multi-GB decode buffer."""
    from PIL import Image

    # Temporarily shrink the cap so we can stage a bomb without generating
    # a giant fixture in CI.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color=(0, 0, 0)).save(buf, format="PNG")  # 2500px > 100
    files = {"file": ("bomb.png", buf.getvalue(), "image/png")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "большое" in detail or "decode" in detail or "разобрать" in detail
