from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class ExpenseCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    category_id: int = Field(gt=0)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class ExpenseUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    category_id: int | None = Field(default=None, gt=0)
    spent_at: datetime | None = None

    @model_validator(mode="after")
    def has_changes(self) -> "ExpenseUpdate":
        if self.amount is None and self.category_id is None and self.spent_at is None:
            raise ValueError("Укажите хотя бы одно изменение")
        return self


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


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    limit: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class BudgetUpdate(BaseModel):
    limit: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
