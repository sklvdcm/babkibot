from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import Base, Category, MonthlyBudget
from app.services import add_expense, get_or_sync_user


@pytest.fixture
async def web_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        web_password="test-password",
        web_session_secret="s" * 64,
        cookie_secure=False,
    )

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def login(client: AsyncClient) -> str:
    response = await client.post("/auth/login", json={"password": "test-password"})
    assert response.status_code == 200
    return response.json()["csrf_token"]


async def test_login_rejects_wrong_password(web_client):
    client, _ = web_client
    response = await client.post("/auth/login", json={"password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный пароль"


async def test_history_can_be_updated_and_deleted(web_client):
    client, factory = web_client
    csrf = await login(client)
    now = datetime(2026, 11, 8, 12, tzinfo=ZoneInfo("Europe/Moscow"))

    async with factory() as session:
        user = await get_or_sync_user(session, "iphone-daniil", display_name="Даниил")
        category = Category(name="Продукты")
        session.add(category)
        await session.flush()
        session.add(MonthlyBudget(category_id=category.id, year=2026, month=11, limit_amount=10000))
        await session.commit()
        expense, _ = await add_expense(
            session,
            user=user,
            category_id=category.id,
            amount=Decimal("1500"),
            source="iphone_shortcut",
            idempotency_key="web-test-key",
            now=now,
        )
        expense_id = expense.id

    response = await client.get("/web/api/expenses?period=2026-11")
    assert response.status_code == 200
    assert response.json()["total"] == "1500.00"

    response = await client.patch(
        f"/web/api/expenses/{expense_id}",
        headers={"X-CSRF-Token": csrf},
        json={"amount": "1750.50"},
    )
    assert response.status_code == 200

    response = await client.get("/web/api/expenses?period=2026-11")
    assert response.json()["total"] == "1750.50"

    response = await client.delete(
        f"/web/api/expenses/{expense_id}", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 204
    response = await client.get("/web/api/expenses?period=2026-11")
    assert response.json()["count"] == 0
