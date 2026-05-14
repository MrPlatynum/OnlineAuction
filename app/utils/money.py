"""Helpers for moving between Decimal (DB / arithmetic) and float
(JSON / API). Money columns are ``Numeric`` so SQLAlchemy gives back
``Decimal``, but request payloads arrive as ``float`` from JSON.
Mixing the two raises ``TypeError`` on +/-/*//, so always convert at
the boundary."""

from decimal import Decimal


def to_decimal(value) -> Decimal | None:
    """Convert via ``str`` so we don't inherit float's binary
    rounding error (``Decimal(0.1)`` ≠ ``Decimal('0.1')``)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money_to_float(value) -> float | None:
    """Cast Decimal → float for JSON responses where the historical
    API contract returns a number, not a string."""
    if value is None:
        return None
    return float(value)
