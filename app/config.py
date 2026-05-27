import os
from decimal import Decimal

from dotenv import load_dotenv

# Load .env from the project root if present. Existing OS env vars
# always win (load_dotenv default), so CI / Docker / explicit shell
# exports keep their precedence.
load_dotenv()

_PLACEHOLDER_SECRET = "your-secret-key-change-in-production"

SECRET_KEY = os.getenv("AUCTION_SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == _PLACEHOLDER_SECRET:
    raise RuntimeError(
        "AUCTION_SECRET_KEY env var is required. "
        "Generate a random key with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

ALGORITHM = "HS256"
# Auth-token lifetime. Lower than 24 h means a leaked JWT (XSS,
# logged URL, careless screenshot) burns out the same day it was
# stolen rather than giving an attacker a full working day. No
# refresh-token flow yet - users on long-lived sessions get a
# silent re-auth prompt every ~2 h, which is the accepted UX
# trade-off until refresh tokens land.
ACCESS_TOKEN_EXPIRE_HOURS = 2

# Defence-in-depth claims on every JWT this app issues. ``iss``
# stops a token signed for some future sibling service from being
# accepted here; ``aud`` flags which API the token is meant for so
# the same key can't be reused to authorise calls against an
# unrelated audience.
JWT_ISSUER = "lotus"
JWT_AUDIENCE = "lotus-api"

_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://auction:auction_dev_password@localhost:5433/auction",
)

# The app uses asyncpg; Alembic uses psycopg2. Accept either driver in
# the env var and normalise so both URLs are always available without
# requiring two env vars.
if "+psycopg2" in _raw_url:
    DATABASE_URL = _raw_url.replace("+psycopg2", "+asyncpg")
elif "+asyncpg" in _raw_url:
    DATABASE_URL = _raw_url
elif _raw_url.startswith("postgresql://"):
    DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://")
else:
    DATABASE_URL = _raw_url

SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg2")

LEGACY_PASSWORD_KEYS = [
    key.strip() for key in os.getenv("LEGACY_PASSWORD_KEYS", "").split(",") if key.strip()
]

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Лотус <noreply@localhost>")

# Public-facing base URL for the application - used by email
# notifications to build absolute links (auction.html, profile.html,
# etc.). Set in production via env: PUBLIC_BASE_URL=https://lotus.example.com
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Platform commission charged to the seller on every settled sale -
# both BIN purchases and auction completions. Held in a single Decimal
# so the multiplication path in app/services/auctions.py doesn't have
# to coerce float → Decimal on the hot settlement path. Operators can
# override per-deployment via env (e.g. PLATFORM_COMMISSION_PERCENT=10).
PLATFORM_COMMISSION_PERCENT = Decimal(os.getenv("PLATFORM_COMMISSION_PERCENT", "7"))

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:5500,http://localhost:8000",
    ).split(",")
    # ``null`` is the Origin header sent by sandboxed iframes and
    # ``file://`` pages; allowing it together with credentials lets a
    # malicious page trick the browser into authenticated CORS calls.
    if origin.strip() and origin.strip().lower() != "null"
]
# AUCTION_ENV is the project-scoped environment name (dev/local/test
# enable developer conveniences; anything else is treated as prod).
# Bare ``ENV`` was too generic - collided with cloud platforms that
# inject their own ENV value (e.g. AWS Elastic Beanstalk).
AUCTION_ENV = os.getenv("AUCTION_ENV", "").lower()

# Localhost CORS regex is a dev convenience: a fresh checkout serving
# the SPA from :5500 / :3000 talks to the API on :8000. In production
# the regex must be off - without it, any page hosted on a literal
# ``localhost`` subdomain (e.g. attacker-controlled ``localhost.evil``
# resolved via /etc/hosts) could make credentialed requests once the
# user is logged in. CORS_ORIGINS handles legitimate production hosts.
LOCAL_CORS_REGEX = (
    r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    if AUCTION_ENV in {"dev", "local", "test"}
    else None
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
UPLOAD_DIR = os.path.join(STATIC_DIR, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
}
