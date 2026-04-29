from pydantic import BaseModel, Field


class DepositRequest(BaseModel):
    amount: float = Field(gt=0, le=100000)


class WithdrawRequest(BaseModel):
    amount: float = Field(gt=0, le=100000)
