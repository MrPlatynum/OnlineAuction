"""Helpers for moving between Decimal (DB / arithmetic) and float
(JSON / API). Money columns are ``Numeric`` so SQLAlchemy gives back
``Decimal``, but request payloads arrive as ``float`` from JSON.
Mixing the two raises ``TypeError`` on +/-/*//, so always convert at
the boundary."""

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def to_decimal(value) -> Decimal | None:
    """Convert via ``str`` so we don't inherit float's binary
    rounding error (``Decimal(0.1)`` ≠ ``Decimal('0.1')``). User-
    supplied money amounts are validated to ``decimal_places<=2`` at
    the Pydantic boundary (see schemas/balance.py, schemas/bid.py,
    schemas/auction.py), so a value that reaches this helper has
    already been rejected if it carried sub-cent precision - no
    silent rounding here.

    Internal arithmetic that *produces* a sub-cent value (commission
    percent multiplication, division) must quantize explicitly via
    ``quantize_money`` at the boundary where it lands in a Numeric(12,2)
    column."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to the 2-decimal money grid with banker-free
    half-up rounding. Use at the single site that produces a sub-cent
    Decimal (commission) before it enters a Numeric(12,2) column - the
    rounding policy is explicit and centralised so a future change is
    one edit, not a sweep of ``.quantize`` calls."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def money_to_float(value) -> float | None:
    """Cast Decimal → float for JSON responses where the historical
    API contract returns a number, not a string."""
    if value is None:
        return None
    return float(value)
