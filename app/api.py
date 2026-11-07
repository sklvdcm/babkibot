import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.schemas import CategoryResult, ExpenseCreate, ExpenseResult
from app.services import DomainError, add_expense, budget_statuses, get_or_sync_user

router = APIRouter(prefix="/api/v1")


async def shortcut_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    supplied = authorization.removeprefix("Bearer ").strip()
    telegram_id = next(
        (
            int(user_id)
            for user_id, token in settings.shortcut_tokens.items()
            if secrets.compare_digest(supplied, token)
        ),
        None,
    )
    if telegram_id is None or telegram_id not in settings.allowed_telegram_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return await get_or_sync_user(
        session, telegram_id, is_admin=telegram_id in settings.admin_telegram_ids
    )


@router.get("/categories", response_model=list[CategoryResult])
async def categories(
    user: Annotated[User, Depends(shortcut_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[CategoryResult]:
    del user
    now = datetime.now(settings.tz)
    return [
        CategoryResult(
            id=item.category.id,
            name=item.category.name,
            limit=item.limit,
            spent=item.spent,
            remaining=item.remaining,
        )
        for item in await budget_statuses(session, now)
    ]


@router.post("/expenses", response_model=ExpenseResult, status_code=status.HTTP_201_CREATED)
async def create_expense(
    payload: ExpenseCreate,
    user: Annotated[User, Depends(shortcut_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExpenseResult:
    try:
        expense, budget = await add_expense(
            session,
            user=user,
            category_id=payload.category_id,
            amount=payload.amount,
            source="iphone_shortcut",
            idempotency_key=payload.idempotency_key,
            now=datetime.now(settings.tz),
        )
    except DomainError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ExpenseResult(
        id=expense.id,
        amount=expense.amount,
        category_id=budget.category.id,
        category_name=budget.category.name,
        spent_at=expense.spent_at,
        remaining=budget.remaining,
    )
