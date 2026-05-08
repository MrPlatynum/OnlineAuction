import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

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
from app.services.auction_scheduler import schedule_active_auctions, shutdown_scheduler
from app.services.migrations import seed_categories
from app.utils.rate_limit import limiter

logger = logging.getLogger(__name__)


def setup_logging():
    """Configure root logger once at app start. Idempotent — uvicorn's
    own loggers are untouched (they own the access/error namespaces)."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Schema is managed by Alembic (run ``alembic upgrade head`` before
    # starting the server). Reference-data seeding is idempotent and
    # runs on every startup.
    await seed_categories()
    await schedule_active_auctions()
    logger.info("Application startup complete (notifications enabled)")
    try:
        yield
    finally:
        await shutdown_scheduler()
        logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    setup_logging()

    fastapi_app = FastAPI(
        title="Real-time Auction API with Notifications",
        lifespan=lifespan,
    )

    fastapi_app.state.limiter = limiter
    fastapi_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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

    return fastapi_app
