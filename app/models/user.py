from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    # Explicit length caps so the schema itself bounds what
    # server-generated code can write here. Pydantic gates the user-
    # facing inputs at the same or tighter limits, so this is a
    # defence-in-depth layer that catches a buggy template or admin
    # SQL writing multi-MB strings.
    username = Column(String(64), unique=True, index=True, nullable=False)
    # RFC 5321 caps an email address at 320 octets (64 local + @ + 255 domain).
    email = Column(String(320), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    # Bumped by /change-password (and any future invalidation event) so
    # tokens issued before the bump fail at /me / get_current_user. JWT
    # carries the value as a ``tv`` claim; mismatch → 401.
    token_version = Column(Integer, default=0, nullable=False)
    # New registrations land as ``False`` and pick up True after the
    # /verify-email click. Existing rows were backfilled to True by the
    # migration (grandfather), so this is *only* False for accounts
    # opened after the feature shipped.
    email_verified = Column(Boolean, default=False, nullable=False)
    # Last time we mailed a password-reset link to this account. Used
    # by /password-reset/request to throttle per-email (1/min) on top
    # of the per-IP slowapi limit - without the per-email floor, an
    # attacker with rotating IPs could flood the inbox.
    password_reset_sent_at = Column(DateTime(timezone=True), nullable=True)
    # Per-account credential-stuffing defence. Bumped on every failed
    # /login attempt; reset to 0 on success. ``locked_until`` carries
    # an exponential lockout (1m / 5m / 15m / 1h plateau) once the
    # count crosses thresholds so a botnet attacking *one* account
    # from many IPs can't sneak past the per-IP rate limit.
    failed_login_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    # Rolling-24h upload byte-budget. ``upload_window_start`` is the
    # opening of the current window; once a fresh upload lands more
    # than 24h after it, the counter resets and the start moves to
    # ``now``. Without this cap any verified user could push 8 MB at
    # 20/min into static/uploads indefinitely and use the platform
    # as free image hosting.
    upload_bytes_window = Column(Integer, default=0, nullable=False)
    upload_window_start = Column(DateTime(timezone=True), nullable=True)
    balance = Column(Numeric(12, 2), default=1000.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    avatar_url = Column(String(500), nullable=True)

    email_notifications = Column(Boolean, default=True, nullable=False)
    notify_outbid = Column(Boolean, default=True, nullable=False)
    notify_winning = Column(Boolean, default=True, nullable=False)
    notify_ending = Column(Boolean, default=True, nullable=False)
    notify_sold = Column(Boolean, default=True, nullable=False)
    notify_bid_received = Column(Boolean, default=True, nullable=False)
    notify_lost = Column(Boolean, default=True, nullable=False)

    bids = relationship("Bid", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        # DB-level safety net: every code path that mutates balance
        # already pre-checks (deposit caps at MAX_USER_BALANCE, withdraw
        # validates available >= amount, bid debit happens against the
        # locked row in complete_auction), but a bug or admin SQL that
        # somehow leaks a negative debit would silently corrupt the
        # audit trail. The constraint catches that at INSERT/UPDATE.
        CheckConstraint("balance >= 0", name="ck_users_balance_nonneg"),
    )
