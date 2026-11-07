from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    category_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ExpenseResult(BaseModel):
    id: int
    amount: Decimal
    category_id: int
    category_name: str
    spent_at: datetime
    remaining: Decimal


class CategoryResult(BaseModel):
    id: int
    name: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
