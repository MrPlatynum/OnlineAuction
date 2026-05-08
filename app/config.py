import os

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
ACCESS_TOKEN_EXPIRE_HOURS = 24

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

# Public-facing base URL приложения — используется в email-уведомлениях
# для построения ссылок (auction.html, profile.html и т. п.).
# В проде задаётся через env: PUBLIC_BASE_URL=https://lotus.example.com
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

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
LOCAL_CORS_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"

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
