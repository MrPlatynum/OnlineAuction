"""Helpers for moving between Decimal (DB / arithmetic) and float
(JSON / API). Money columns are ``Numeric`` so SQLAlchemy gives back
``Decimal``, but request payloads arrive as ``float`` from JSON.
Mixing the two raises ``TypeError`` on +/-/*//, so always convert at
the boundary."""

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def to_decimal(value) -> Decimal | None:
    """Convert via ``str`` so we don't inherit float's binary
    rounding error (``Decimal(0.1)`` ≠ ``Decimal('0.1')``), then
    quantize to two decimal places. Money columns are ``Numeric(12,2)``
    - storing a value like 100.0055 leaves an in-memory ORM copy with
    four decimals while the DB stores 100.01, so audit rows built off
    the un-rounded amount disagree with the persisted balance by sub-
    cent. Quantize on the way in so caller arithmetic, audit ``amount``
    fields and DB writes all agree."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def money_to_float(value) -> float | None:
    """Cast Decimal → float for JSON responses where the historical
    API contract returns a number, not a string."""
    if value is None:
        return None
    return float(value)
