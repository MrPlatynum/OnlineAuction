import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, CORS_ORIGINS, LOCAL_CORS_REGEX, STATIC_DIR
from app.routers import (
    auctions,
    auth,
    balance,
    bids,
    categories,
    notifications,
    reviews,
    static_pages,
    subscriptions,
    uploads,
    users,
    websocket,
)
from app.services.auctions import check_expired_auctions
from app.services.migrations import create_tables, run_migrations, seed_categories


def create_app() -> FastAPI:
    create_tables()
    run_migrations()
    seed_categories()

    fastapi_app = FastAPI(title="Real-time Auction API with Notifications")

    fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_origin_regex=LOCAL_CORS_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(auth.router)
    fastapi_app.include_router(users.router)
    fastapi_app.include_router(balance.router)
    fastapi_app.include_router(uploads.router)
    fastapi_app.include_router(categories.router)
    fastapi_app.include_router(auctions.router)
    fastapi_app.include_router(bids.router)
    fastapi_app.include_router(notifications.router)
    fastapi_app.include_router(reviews.router)
    fastapi_app.include_router(subscriptions.router)
    fastapi_app.include_router(websocket.router)

    if os.path.exists(os.path.join(BASE_DIR, "templates", "index.html")):
        fastapi_app.include_router(static_pages.router)

    background_task: asyncio.Task | None = None

    @fastapi_app.on_event("startup")
    async def startup_event():
        nonlocal background_task
        background_task = asyncio.create_task(check_expired_auctions())
        print("✅ Приложение запущено с системой уведомлений")

    @fastapi_app.on_event("shutdown")
    async def shutdown_event():
        nonlocal background_task
        if background_task:
            background_task.cancel()
            try:
                await background_task
            except asyncio.CancelledError:
                pass
        print("🛑 Приложение остановлено")

    return fastapi_app
