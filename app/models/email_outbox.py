from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base
from app.utils.time import utcnow


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id = Column(Integer, primary_key=True, index=True)
    to_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    html_body = Column(Text, nullable=False)
    # ``pending``: not yet sent or scheduled for retry.
    # ``sent``: terminal success.
    # ``failed``: terminal dead-letter - retry budget exhausted.
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    last_error = Column(Text, nullable=True)
    # The worker fetches rows where ``status='pending' AND
    # next_attempt_at <= now()``. Backoff updates push this forward.
    next_attempt_at = Column(DateTime, nullable=False, default=utcnow)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    sent_at = Column(DateTime, nullable=True)
