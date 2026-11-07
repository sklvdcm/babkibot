import secrets
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    SESSION_COOKIE,
    LoginRequest,
    check_login_rate_limit,
    clear_login_attempts,
    csrf_token,
    new_session,
    require_csrf,
    require_web_session,
    set_session_cookie,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Category, Expense, MonthlyBudget
from app.schemas import BudgetUpdate, CategoryCreate, CategoryUpdate, ExpenseUpdate
from app.services import budget_statuses, month_bounds

router = APIRouter()


def money_value(value: Decimal) -> str:
    return f"{value:.2f}"


@router.post("/auth/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    if not settings.web_password or not settings.web_session_secret:
        raise HTTPException(status_code=503, detail="Доступ ещё не настроен на сервере")
    check_login_rate_limit(request)
    if not secrets.compare_digest(payload.password, settings.web_password):
        raise HTTPException(status_code=401, detail="Неверный пароль")
    clear_login_attempts(request)
    cookie, csrf = new_session(settings)
    set_session_cookie(response, cookie, settings)
    return {"csrf_token": csrf}


@router.post("/auth/logout", dependencies=[Depends(require_csrf)])
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/web/api/session")
async def session_info(
    nonce: Annotated[str, Depends(require_web_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    return {"csrf_token": csrf_token(nonce, settings)}


def month_moment(period: str | None, settings: Settings) -> datetime:
    if period is None:
        return datetime.now(settings.tz)
    try:
        year, month = (int(part) for part in period.split("-", 1))
        return datetime(year, month, 1, tzinfo=settings.tz)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Некорректный месяц") from error


def expense_dict(expense: Expense, settings: Settings) -> dict:
    return {
        "id": expense.id,
        "amount": money_value(expense.amount),
        "category_id": expense.category_id,
        "category_name": expense.category.name,
        "person": expense.user.display_name or expense.user.external_id,
        "spent_at": expense.spent_at.astimezone(settings.tz).isoformat(),
        "source": expense.source,
    }


@router.get("/web/api/overview")
async def overview(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[str, Depends(require_web_session)],
    period: str | None = None,
) -> dict:
    moment = month_moment(period, settings)
    statuses = await budget_statuses(session, moment)
    start, end = month_bounds(moment)
    expenses = (
        await session.scalars(
            select(Expense)
            .where(Expense.spent_at >= start, Expense.spent_at < end)
            .options(selectinload(Expense.category), selectinload(Expense.user))
            .order_by(Expense.spent_at.desc())
            .limit(6)
        )
    ).all()
    total_limit = sum((item.limit for item in statuses), Decimal("0"))
    total_spent = sum((item.spent for item in statuses), Decimal("0"))
    return {
        "period": f"{moment.year:04d}-{moment.month:02d}",
        "total_limit": money_value(total_limit),
        "total_spent": money_value(total_spent),
        "remaining": money_value(total_limit - total_spent),
        "categories": [
            {
                "id": item.category.id,
                "name": item.category.name,
                "limit": money_value(item.limit),
                "spent": money_value(item.spent),
                "remaining": money_value(item.remaining),
                "ratio": float(item.spent / item.limit) if item.limit else 0,
            }
            for item in statuses
        ],
        "recent": [expense_dict(item, settings) for item in expenses],
    }


@router.get("/web/api/expenses")
async def expenses(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[str, Depends(require_web_session)],
    period: str | None = None,
    category_id: int | None = None,
) -> dict:
    moment = month_moment(period, settings)
    start, end = month_bounds(moment)
    query = (
        select(Expense)
        .where(Expense.spent_at >= start, Expense.spent_at < end)
        .options(selectinload(Expense.category), selectinload(Expense.user))
        .order_by(Expense.spent_at.desc())
    )
    if category_id is not None:
        query = query.where(Expense.category_id == category_id)
    rows = (await session.scalars(query)).all()
    total = sum((item.amount for item in rows), Decimal("0"))
    return {
        "period": f"{moment.year:04d}-{moment.month:02d}",
        "total": money_value(total),
        "count": len(rows),
        "items": [expense_dict(item, settings) for item in rows],
    }


@router.patch("/web/api/expenses/{expense_id}", dependencies=[Depends(require_csrf)])
async def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    expense = await session.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Трата не найдена")
    if payload.category_id is not None:
        category = await session.get(Category, payload.category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="Категория не найдена")
        expense.category_id = payload.category_id
    if payload.amount is not None:
        expense.amount = payload.amount
    if payload.spent_at is not None:
        expense.spent_at = payload.spent_at
    await session.commit()
    return {"ok": True}


@router.delete("/web/api/expenses/{expense_id}", dependencies=[Depends(require_csrf)])
async def delete_expense(
    expense_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    expense = await session.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Трата не найдена")
    await session.delete(expense)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/web/api/categories")
async def list_categories(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[str, Depends(require_web_session)],
    period: str | None = None,
) -> dict:
    moment = month_moment(period, settings)
    categories = (await session.scalars(select(Category).order_by(Category.name))).all()
    budgets = {
        item.category_id: item
        for item in (
            await session.scalars(
                select(MonthlyBudget).where(
                    MonthlyBudget.year == moment.year, MonthlyBudget.month == moment.month
                )
            )
        ).all()
    }
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "is_active": item.is_active,
                "limit": money_value(budgets[item.id].limit_amount) if item.id in budgets else None,
            }
            for item in categories
        ]
    }


@router.post(
    "/web/api/categories", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_category(
    payload: CategoryCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, int]:
    now = datetime.now(settings.tz)
    category = Category(name=payload.name.strip())
    session.add(category)
    try:
        await session.flush()
        session.add(
            MonthlyBudget(
                category_id=category.id,
                year=now.year,
                month=now.month,
                limit_amount=payload.limit,
            )
        )
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Категория с таким названием уже есть"
        ) from error
    return {"id": category.id}


@router.patch("/web/api/categories/{category_id}", dependencies=[Depends(require_csrf)])
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    if payload.name is not None:
        category.name = payload.name.strip()
    if payload.is_active is not None:
        category.is_active = payload.is_active
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Категория с таким названием уже есть"
        ) from error
    return {"ok": True}


@router.put("/web/api/budgets/{category_id}/{period}", dependencies=[Depends(require_csrf)])
async def set_budget(
    category_id: int,
    period: str,
    payload: BudgetUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    moment = month_moment(period, settings)
    category = await session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    budget = await session.scalar(
        select(MonthlyBudget).where(
            MonthlyBudget.category_id == category_id,
            MonthlyBudget.year == moment.year,
            MonthlyBudget.month == moment.month,
        )
    )
    if budget is None:
        session.add(
            MonthlyBudget(
                category_id=category_id,
                year=moment.year,
                month=moment.month,
                limit_amount=payload.limit,
            )
        )
    else:
        budget.limit_amount = payload.limit
    await session.commit()
    return {"ok": True}
