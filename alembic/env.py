"""Alembic migration environment.

Pulls the database URL from the same env var the app uses
(``DATABASE_URL``) so dev, prod, and tests all stay aligned without
duplicating connection strings in alembic.ini.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Ensure ``app`` is importable when alembic is invoked from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# AUCTION_SECRET_KEY is required by app.config at import time. We don't
# need a real key for migrations (no JWTs are signed), so set a stub if
# the user only wants to run schema upgrades.
os.environ.setdefault("AUCTION_SECRET_KEY", "alembic-stub-not-used-for-signing")

from app import models  # noqa: E402,F401  -- registers all models on Base
from app.database import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic uses a sync driver. App config exposes ``SYNC_DATABASE_URL``
# derived from ``DATABASE_URL`` (which may use +asyncpg for the app).
from app.config import SYNC_DATABASE_URL  # noqa: E402

config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
