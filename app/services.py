from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Expense, MonthlyBudget, User


class DomainError(Exception):
    pass


class DuplicateExpense(DomainError):
    pass


@dataclass(slots=True)
class BudgetStatus:
    category: Category
    limit: Decimal
    spent: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.limit - self.spent


def parse_amount(raw: str) -> Decimal:
    normalized = raw.replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise DomainError("Введите корректную сумму, например 1500 или 1500,50") from error
    if amount <= 0:
        raise DomainError("Сумма должна быть больше нуля")
    return amount


def active_budget_query(now: datetime) -> Select[tuple[Category, Decimal, Decimal]]:
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        period_end = period_start.replace(year=now.year + 1, month=1)
    else:
        period_end = period_start.replace(month=now.month + 1)
    spent = (
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(
            Expense.category_id == Category.id,
            Expense.spent_at >= period_start,
            Expense.spent_at < period_end,
        )
        .correlate(Category)
        .scalar_subquery()
    )
    return (
        select(Category, MonthlyBudget.limit_amount, spent)
        .join(MonthlyBudget, MonthlyBudget.category_id == Category.id)
        .where(
            Category.is_active.is_(True),
            MonthlyBudget.year == now.year,
            MonthlyBudget.month == now.month,
        )
        .order_by(Category.name)
    )


async def budget_statuses(session: AsyncSession, now: datetime) -> list[BudgetStatus]:
    rows = (await session.execute(active_budget_query(now))).all()
    return [BudgetStatus(category=row[0], limit=row[1], spent=row[2]) for row in rows]


async def get_or_sync_user(
    session: AsyncSession,
    telegram_id: int,
    *,
    username: str | None = None,
    display_name: str | None = None,
    is_admin: bool = False,
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            display_name=display_name,
            is_admin=is_admin,
        )
        session.add(user)
    else:
        user.username = username or user.username
        user.display_name = display_name or user.display_name
        user.is_active = True
        user.is_admin = is_admin
    await session.commit()
    await session.refresh(user)
    return user


async def add_expense(
    session: AsyncSession,
    *,
    user: User,
    category_id: int,
    amount: Decimal,
    source: str,
    idempotency_key: str | None,
    now: datetime,
) -> tuple[Expense, BudgetStatus]:
    statuses = {item.category.id: item for item in await budget_statuses(session, now)}
    status = statuses.get(category_id)
    if status is None:
        raise DomainError("Категория не найдена или для неё не задан бюджет на этот месяц")

    expense = Expense(
        user_id=user.id,
        category_id=category_id,
        amount=amount,
        source=source,
        idempotency_key=idempotency_key,
        spent_at=now,
    )
    session.add(expense)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise DuplicateExpense("Эта трата уже была сохранена") from error
    await session.refresh(expense)
    status.spent += amount
    return expense, status
