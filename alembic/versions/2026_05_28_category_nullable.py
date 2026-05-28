"""Enforce NOT NULL on categories.name and categories.slug

Both columns are UNIQUE, but Postgres treats NULL as distinct in
UNIQUE indexes - so without an explicit NOT NULL two or more rows
with ``slug=NULL`` (or ``name=NULL``) could legally coexist. That
silently breaks the ``/categories/<slug>`` lookup, the seed-time
"slug already exists" guard, and any admin tool that round-trips
through these columns. The seed always populates both fields, but
the schema needs to enforce the invariant itself.

Backfill any pre-existing NULLs with a placeholder before the ALTER
runs so existing dev databases survive the upgrade. In production
the seed has filled every row from day one, so the backfill is a
no-op.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-28 16:30:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill: any NULL row gets a deterministic placeholder so the
    # NOT NULL alter doesn't fail. ``id`` is unique by definition, so
    # ``name_<id>`` / ``slug_<id>`` won't collide with the existing
    # unique-name / unique-slug indexes.
    op.execute(
        "UPDATE categories SET name = 'category_' || id WHERE name IS NULL"
    )
    op.execute(
        "UPDATE categories SET slug = 'category_' || id WHERE slug IS NULL"
    )
    op.alter_column("categories", "name", nullable=False)
    op.alter_column("categories", "slug", nullable=False)


def downgrade() -> None:
    op.alter_column("categories", "slug", nullable=True)
    op.alter_column("categories", "name", nullable=True)
