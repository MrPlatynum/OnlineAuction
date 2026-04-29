import os

_PLACEHOLDER_SECRET = "your-secret-key-change-in-production"

SECRET_KEY = os.getenv("AUCTION_SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == _PLACEHOLDER_SECRET:
    raise RuntimeError(
        "AUCTION_SECRET_KEY env var is required. "
        "Generate a random key with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./auction.db")

LEGACY_PASSWORD_KEYS = [
    key.strip() for key in os.getenv("LEGACY_PASSWORD_KEYS", "").split(",") if key.strip()
]

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "AuctionHub <noreply@localhost>")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:5500,http://localhost:8000,null"
    ).split(",")
    if origin.strip()
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
