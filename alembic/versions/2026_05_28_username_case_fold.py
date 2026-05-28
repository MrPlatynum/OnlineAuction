"""Lower-case all existing usernames

The column was created without case-folding, and the
``User.username == ...`` comparison everywhere in the app is
case-sensitive. So 'Alice' and 'alice' could both have registered,
@-mentions were ambiguous, and a profile lookup at /users/Alice
silently 404'd for a user who registered as 'alice'. The Pydantic
input layer now lowercases the username at every boundary
(UserCreate, UserLogin, path/query params); this migration backfills
the column so the new invariant holds for pre-existing rows too.

Pre-flight: if any two rows differ only in case
(``lower(a.username) = lower(b.username) AND a.id != b.id``), the
migration aborts with a clear message - an operator must rename one
of the colliding pair before re-running. Letting the UPDATE through
would either silently violate the UNIQUE constraint (Postgres raises
mid-migration, leaving the table half-converted) or, worse, merge
the two profiles' identities.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-05-28 21:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op
from sqlalchemy import text

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Pre-flight: are there any case-insensitive duplicates?
    collisions = conn.execute(
        text(
            """
            SELECT lower(username) AS folded, array_agg(username) AS variants
            FROM users
            GROUP BY lower(username)
            HAVING count(*) > 1
            """
        )
    ).fetchall()
    if collisions:
        details = "; ".join(
            f"{row.folded!r}: {row.variants}" for row in collisions
        )
        raise RuntimeError(
            "Cannot case-fold usernames: pre-existing case-insensitive "
            f"duplicates detected. Resolve manually first: {details}"
        )
    # No collisions - safe to lower-case in place.
    op.execute(text("UPDATE users SET username = lower(username) WHERE username != lower(username)"))


def downgrade() -> None:
    # No-op: the original mixed-case values aren't recoverable from
    # the lowercased form. Downgrading the schema is fine; the data
    # stays lowercased.
    pass
