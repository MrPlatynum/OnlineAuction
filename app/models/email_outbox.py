from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.database import Base
from app.utils.time import utcnow


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id = Column(Integer, primary_key=True, index=True)
    to_email = Column(String(320), nullable=False)
    subject = Column(String(500), nullable=False)
    html_body = Column(Text, nullable=False)
    # ``pending``: not yet sent or scheduled for retry.
    # ``sent``: terminal success.
    # ``failed``: terminal dead-letter - retry budget exhausted.
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    last_error = Column(Text, nullable=True)
    # The worker fetches rows where ``status='pending' AND
    # next_attempt_at <= now()``. Backoff updates push this forward.
    next_attempt_at = Column(DateTime, nullable=False, default=utcnow)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    sent_at = Column(DateTime, nullable=True)

    # The migration creates this index for the hot worker query above;
    # the model has to declare it too or the next alembic autogenerate
    # diff-detects a "phantom" drop and ships a migration that removes
    # it - silently regressing outbox-drain performance once the table
    # grows.
    __table_args__ = (
        Index(
            "ix_email_outbox_status_next_attempt_at",
            "status",
            "next_attempt_at",
        ),
    )
