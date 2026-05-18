"""Plain-HTML pages served as static templates.

The frontend is multi-page, no SPA framework — each navigable URL maps
to a file in ``templates/`` returned via ``FileResponse``. Per-page
``static/js/<page>.js`` does the data fetching client-side; this
module just resolves URL → file and 404s if the template is missing.
"""

import os

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from app.config import BASE_DIR

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

router = APIRouter()


def _page(name: str) -> FileResponse:
    path = os.path.join(TEMPLATES_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Страница не найдена")
    return FileResponse(path)


@router.get("/")
async def read_index_root():
    return _page("index.html")


@router.get("/index.html")
async def read_index():
    return _page("index.html")


@router.get("/auction.html")
async def read_auction():
    return _page("auction.html")


@router.get("/profile.html")
async def read_profile():
    return _page("profile.html")


@router.get("/my-bids.html")
async def read_my_bids():
    return _page("my-bids.html")


@router.get("/user.html")
async def read_user():
    return _page("user.html")


@router.get("/verify-email.html")
async def read_verify_email():
    return _page("verify-email.html")


@router.get("/forgot-password.html")
async def read_forgot_password():
    return _page("forgot-password.html")


@router.get("/password-reset.html")
async def read_password_reset():
    return _page("password-reset.html")


