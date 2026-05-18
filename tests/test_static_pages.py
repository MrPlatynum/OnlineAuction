"""Static-page routes (``static_pages`` router).

Each route just returns one of the templates from ``TEMPLATES_DIR`` via
``FileResponse``. There's no business logic to test — only that the
route is wired, the template exists on disk, and the 404 branch fires
when it doesn't."""

import os

import pytest

from app.config import BASE_DIR
from app.routers import static_pages as static_pages_module

PAGE_ROUTES = [
    "/",
    "/index.html",
    "/auction.html",
    "/profile.html",
    "/my-bids.html",
    "/user.html",
    "/verify-email.html",
    "/forgot-password.html",
    "/password-reset.html",
]


@pytest.mark.parametrize("path", PAGE_ROUTES)
async def test_static_page_route_returns_template(client, path):
    response = await client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    # FileResponse sets Content-Type from the template extension; all of
    # ours are .html.
    assert "text/html" in response.headers.get("content-type", "")


async def test_static_page_missing_template_returns_404(client, monkeypatch):
    """The ``_page`` helper raises 404 when the file is missing. We can't
    delete the real templates, but we can point the helper at a path
    that doesn't exist."""
    fake_dir = os.path.join(BASE_DIR, "no-such-dir-for-tests")
    monkeypatch.setattr(static_pages_module, "TEMPLATES_DIR", fake_dir)
    response = await client.get("/index.html")
    assert response.status_code == 404
