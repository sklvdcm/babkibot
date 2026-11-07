from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Category, MonthlyBudget
from app.services import DomainError, add_expense, budget_statuses, get_or_sync_user, parse_amount


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def test_parse_amount_accepts_russian_format():
    assert parse_amount("1 500,50") == Decimal("1500.50")


@pytest.mark.parametrize("raw", ["0", "-20", "abc"])
def test_parse_amount_rejects_invalid_values(raw):
    with pytest.raises(DomainError):
        parse_amount(raw)


async def test_expense_reduces_remaining_budget(session):
    now = datetime(2026, 11, 8, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    user = await get_or_sync_user(session, 123)
    category = Category(name="Продукты")
    session.add(category)
    await session.flush()
    session.add(MonthlyBudget(category_id=category.id, year=2026, month=11, limit_amount=10000))
    await session.commit()

    expense, status = await add_expense(
        session,
        user=user,
        category_id=category.id,
        amount=Decimal("1500"),
        source="iphone_shortcut",
        idempotency_key="unique-key",
        now=now,
    )

    assert expense.amount == Decimal("1500")
    assert status.remaining == Decimal("8500")
    statuses = await budget_statuses(session, now)
    assert statuses[0].spent == Decimal("1500")


async def test_previous_month_expense_does_not_reduce_current_budget(session):
    november = datetime(2026, 11, 30, 23, tzinfo=ZoneInfo("Europe/Moscow"))
    december = datetime(2026, 12, 1, 1, tzinfo=ZoneInfo("Europe/Moscow"))
    user = await get_or_sync_user(session, 456)
    category = Category(name="Транспорт")
    session.add(category)
    await session.flush()
    session.add_all(
        [
            MonthlyBudget(category_id=category.id, year=2026, month=11, limit_amount=5000),
            MonthlyBudget(category_id=category.id, year=2026, month=12, limit_amount=7000),
        ]
    )
    await session.commit()
    await add_expense(
        session,
        user=user,
        category_id=category.id,
        amount=Decimal("1000"),
        source="iphone_shortcut",
        idempotency_key="november-key",
        now=november,
    )

    statuses = await budget_statuses(session, december)

    assert statuses[0].limit == Decimal("7000")
    assert statuses[0].spent == Decimal("0")
