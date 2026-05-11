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
    """Random bytes with ``image/jpeg`` Content-Type — historically
    this passed the header-only check. The magic-byte verify must
    reject it as 'not a valid image'."""
    payload = b"#!/bin/sh\necho pwned\n" + b"\x00" * 256
    files = {"file": ("evil.jpg", payload, "image/jpeg")}
    r = await client.post(
        "/api/upload-avatar", files=files, headers=registered_user["headers"]
    )
    assert r.status_code == 400, r.text


async def test_content_type_mismatch_rejected(client, registered_user):
    """Real PNG bytes sent with ``image/jpeg`` Content-Type — the
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
