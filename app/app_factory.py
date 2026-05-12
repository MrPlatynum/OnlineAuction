import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import BASE_DIR, CORS_ORIGINS, LOCAL_CORS_REGEX, STATIC_DIR
from app.routers import (
    auctions,
    auth,
    balance,
    bids,
    categories,
    health,
    notifications,
    reviews,
    static_pages,
    subscriptions,
    uploads,
    users,
    websocket,
)
from app.services.auction_scheduler import schedule_active_auctions, shutdown_scheduler
from app.services.email_outbox import start_outbox_worker, stop_outbox_worker
from app.services.migrations import seed_categories
from app.services.scheduler_election import (
    release_scheduler_lock,
    try_become_scheduler_leader,
)
from app.utils.rate_limit import limiter

logger = logging.getLogger(__name__)


class _JsonFormatter(logging.Formatter):
    """Single-line JSON per record. Plays nice with Loki / CloudWatch /
    any log shipper that wants to index by level/logger/msg."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_SECURITY_HEADERS = {
    # Stop content-sniffing — uploaded "image" returned with a wrong
    # Content-Type can't be re-interpreted as HTML/script by the browser.
    "X-Content-Type-Options": "nosniff",
    # No iframing. The app has no embed-in-iframe use case, and refusing
    # framing kills clickjacking even if a chrome-rendered page is reused.
    "X-Frame-Options": "DENY",
    # Don't leak full URLs (with query params) to third-party origins on
    # navigation; keep the origin so analytics / referrer logs still work.
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Disable browser feature surface that the app doesn't use.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add a small set of safe-by-default security headers to every
    response. HSTS is opt-in (``HSTS_ENABLED=true``) — it's only safe
    once the app is served exclusively over HTTPS, which is a deployment
    decision, not a code one."""

    def __init__(self, app, hsts_enabled: bool = False):
        super().__init__(app)
        self.hsts_enabled = hsts_enabled

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if self.hsts_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def setup_logging():
    """Configure root logger once at app start. Idempotent — uvicorn's
    own loggers are untouched (they own the access/error namespaces).

    Set ``LOG_FORMAT=json`` to switch to one-line JSON records suitable
    for log shippers; default stays human-readable for local dev.
    """
    if logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    if os.getenv("LOG_FORMAT", "").lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # Schema is managed by Alembic (run ``alembic upgrade head`` before
    # starting the server). Reference-data seeding is idempotent and
    # runs on every startup.
    await seed_categories()
    # Leader-elect the scheduler via a Postgres advisory lock. Under
    # ``uvicorn --workers N`` only the worker that wins the lock arms
    # the per-auction asyncio.Tasks; followers serve HTTP/WS traffic
    # only. The outbox worker uses ``SELECT FOR UPDATE SKIP LOCKED``
    # and is intentionally safe to run in every worker.
    is_leader = await try_become_scheduler_leader()
    if is_leader:
        await schedule_active_auctions()
    start_outbox_worker()
    logger.info(
        "Application startup complete (scheduler %s)",
        "leader" if is_leader else "follower",
    )
    try:
        yield
    finally:
        if is_leader:
            await shutdown_scheduler()
        await stop_outbox_worker()
        await release_scheduler_lock()
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
    fastapi_app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_enabled=os.getenv("HSTS_ENABLED", "").lower() in {"true", "1", "yes"},
    )

    fastapi_app.include_router(health.router)
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
