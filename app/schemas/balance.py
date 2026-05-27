from decimal import Decimal

from pydantic import BaseModel, Field


# Money amounts arrive as JSON numbers. Use Decimal at the validation
# layer with ``decimal_places=2`` so a payload like ``100.005`` fails the
# 422 boundary instead of being silently rounded to ``100.01`` later by
# helper code - the user sees an immediate validation error and must
# re-submit a value that exactly matches what the platform will charge or
# credit. Float at the boundary used to give silent half-up rounding via
# ``to_decimal``.
class DepositRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("100000"), decimal_places=2)


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("100000"), decimal_places=2)
