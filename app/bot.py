import uuid
from datetime import datetime
from decimal import Decimal

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import desc, select

from app.config import Settings
from app.db import session_factory
from app.models import Category, Expense, MonthlyBudget, User
from app.services import DomainError, add_expense, budget_statuses, get_or_sync_user, parse_amount

router = Router()


class SpendFlow(StatesGroup):
    amount = State()
    amount_confirm = State()
    category = State()
    category_confirm = State()


def money(value: Decimal) -> str:
    return f"{value:,.2f} ₽".replace(",", " ").replace(".00", "")


def confirm_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"{prefix}:no"),
            ]
        ]
    )


async def allowed(message: Message, settings: Settings) -> bool:
    if message.from_user and message.from_user.id in settings.allowed_telegram_ids:
        return True
    await message.answer("У вас нет доступа к этому боту.")
    return False


async def db_user(message: Message, settings: Settings) -> User:
    assert message.from_user
    async with session_factory() as session:
        return await get_or_sync_user(
            session,
            message.from_user.id,
            username=message.from_user.username,
            display_name=message.from_user.full_name,
            is_admin=message.from_user.id in settings.admin_telegram_ids,
        )


@router.message(CommandStart())
async def start(message: Message, settings: Settings) -> None:
    if not await allowed(message, settings):
        return
    await db_user(message, settings)
    await message.answer(
        "💸 BabkiBot готов.\n\n"
        "/spend — записать трату\n"
        "/budgets — остатки по категориям\n"
        "/history — последние траты\n"
        "/help — все команды"
    )


@router.message(Command("help"))
async def help_command(message: Message, settings: Settings) -> None:
    if not await allowed(message, settings):
        return
    text = (
        "Команды:\n"
        "/spend — добавить трату\n"
        "/budgets — бюджет текущего месяца\n"
        "/history — 15 последних трат"
    )
    if message.from_user and message.from_user.id in settings.admin_telegram_ids:
        text += (
            "\n\nАдминистратор:\n"
            "/category_add Название | 50000\n"
            "/category_edit ID | Новое название | 60000\n"
            "/category_disable ID\n"
            "/budget_set ID | 70000 | 2026-11"
        )
    await message.answer(text)


@router.message(Command("spend"))
async def spend_start(message: Message, state: FSMContext, settings: Settings) -> None:
    if not await allowed(message, settings):
        return
    await db_user(message, settings)
    await state.clear()
    await state.set_state(SpendFlow.amount)
    await message.answer("Введите сумму траты:")


@router.message(SpendFlow.amount)
async def spend_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = parse_amount(message.text or "")
    except DomainError as error:
        await message.answer(str(error))
        return
    await state.update_data(amount=str(amount))
    await state.set_state(SpendFlow.amount_confirm)
    await message.answer(
        f"Сумма: {money(amount)}. Всё верно?", reply_markup=confirm_keyboard("amount")
    )


@router.callback_query(SpendFlow.amount_confirm, F.data == "amount:no")
async def amount_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Добавление траты отменено.")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(SpendFlow.amount_confirm, F.data == "amount:yes")
async def amount_confirm(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    async with session_factory() as session:
        statuses = await budget_statuses(session, datetime.now(settings.tz))
    if not statuses:
        await state.clear()
        await callback.message.edit_text("На текущий месяц нет активных категорий.")  # type: ignore[union-attr]
        await callback.answer()
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{s.category.name} · {money(s.remaining)}",
                    callback_data=f"cat:{s.category.id}",
                )
            ]
            for s in statuses
        ]
    )
    await state.set_state(SpendFlow.category)
    await callback.message.edit_text("Выберите категорию:", reply_markup=keyboard)  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(SpendFlow.category, F.data.startswith("cat:"))
async def category_choose(callback: CallbackQuery, state: FSMContext) -> None:
    category_id = int(callback.data.split(":", 1)[1])  # type: ignore[union-attr]
    async with session_factory() as session:
        category = await session.get(Category, category_id)
    if category is None:
        await callback.answer("Категория больше не существует", show_alert=True)
        return
    await state.update_data(category_id=category_id, category_name=category.name)
    data = await state.get_data()
    await state.set_state(SpendFlow.category_confirm)
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"Записать {money(Decimal(data['amount']))} в «{category.name}»?",
        reply_markup=confirm_keyboard("category"),
    )
    await callback.answer()


@router.callback_query(SpendFlow.category_confirm, F.data == "category:no")
async def category_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Добавление траты отменено.")  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(SpendFlow.category_confirm, F.data == "category:yes")
async def category_confirm(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    data = await state.get_data()
    assert callback.from_user
    async with session_factory() as session:
        user = await get_or_sync_user(
            session,
            callback.from_user.id,
            username=callback.from_user.username,
            display_name=callback.from_user.full_name,
            is_admin=callback.from_user.id in settings.admin_telegram_ids,
        )
        try:
            expense, budget = await add_expense(
                session,
                user=user,
                category_id=int(data["category_id"]),
                amount=Decimal(data["amount"]),
                source="telegram",
                idempotency_key=str(uuid.uuid4()),
                now=datetime.now(settings.tz),
            )
        except DomainError as error:
            await callback.answer(str(error), show_alert=True)
            return
    await state.clear()
    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Записано: {money(expense.amount)} · {budget.category.name}\n"
        f"Осталось: {money(budget.remaining)}"
    )
    await callback.answer()


@router.message(Command("budgets", "categories"))
async def budgets(message: Message, settings: Settings) -> None:
    if not await allowed(message, settings):
        return
    async with session_factory() as session:
        items = await budget_statuses(session, datetime.now(settings.tz))
    if not items:
        await message.answer("На текущий месяц бюджеты пока не заданы.")
        return
    lines = ["📊 Бюджет на текущий месяц:"]
    for item in items:
        lines.append(
            f"\n{item.category.id}. {item.category.name}\n"
            f"Потрачено {money(item.spent)} из {money(item.limit)}\n"
            f"Осталось {money(item.remaining)}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("history"))
async def history(message: Message, settings: Settings) -> None:
    if not await allowed(message, settings):
        return
    async with session_factory() as session:
        expenses = (
            await session.scalars(select(Expense).order_by(desc(Expense.spent_at)).limit(15))
        ).all()
        for expense in expenses:
            await session.refresh(expense, ["user", "category"])
    if not expenses:
        await message.answer("История трат пока пуста.")
        return
    lines = ["🧾 Последние траты:"]
    for expense in expenses:
        who = expense.user.display_name or expense.user.username or str(expense.user.telegram_id)
        when = expense.spent_at.astimezone(settings.tz).strftime("%d.%m %H:%M")
        lines.append(f"{when} · {who} · {expense.category.name} · {money(expense.amount)}")
    await message.answer("\n".join(lines))


def admin_args(message: Message, settings: Settings) -> str | None:
    if not message.from_user or message.from_user.id not in settings.admin_telegram_ids:
        return None
    return (message.text or "").partition(" ")[2].strip()


@router.message(Command("category_add"))
async def category_add(message: Message, settings: Settings) -> None:
    raw = admin_args(message, settings)
    if raw is None:
        await message.answer("Команда доступна только администратору.")
        return
    try:
        name, amount_raw = [part.strip() for part in raw.split("|", 1)]
        amount = parse_amount(amount_raw)
        if not name:
            raise ValueError
    except (ValueError, DomainError):
        await message.answer("Формат: /category_add Название | 50000")
        return
    now = datetime.now(settings.tz)
    async with session_factory() as session:
        category = Category(name=name)
        session.add(category)
        await session.flush()
        session.add(
            MonthlyBudget(
                category_id=category.id, year=now.year, month=now.month, limit_amount=amount
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await message.answer("Категория с таким названием уже существует.")
            return
    await message.answer(f"✅ Категория «{name}» создана, лимит {money(amount)}.")


@router.message(Command("category_edit"))
async def category_edit(message: Message, settings: Settings) -> None:
    raw = admin_args(message, settings)
    if raw is None:
        await message.answer("Команда доступна только администратору.")
        return
    try:
        id_raw, name, amount_raw = [part.strip() for part in raw.split("|", 2)]
        category_id, amount = int(id_raw), parse_amount(amount_raw)
    except (ValueError, DomainError):
        await message.answer("Формат: /category_edit ID | Новое название | 60000")
        return
    now = datetime.now(settings.tz)
    async with session_factory() as session:
        category = await session.get(Category, category_id)
        if category is None:
            await message.answer("Категория не найдена.")
            return
        category.name = name
        budget = await session.scalar(
            select(MonthlyBudget).where(
                MonthlyBudget.category_id == category_id,
                MonthlyBudget.year == now.year,
                MonthlyBudget.month == now.month,
            )
        )
        if budget is None:
            budget = MonthlyBudget(
                category_id=category_id, year=now.year, month=now.month, limit_amount=amount
            )
            session.add(budget)
        else:
            budget.limit_amount = amount
        await session.commit()
    await message.answer(f"✅ Категория обновлена: «{name}», лимит {money(amount)}.")


@router.message(Command("category_disable"))
async def category_disable(message: Message, settings: Settings) -> None:
    raw = admin_args(message, settings)
    try:
        category_id = int(raw or "")
    except ValueError:
        await message.answer("Формат: /category_disable ID")
        return
    async with session_factory() as session:
        category = await session.get(Category, category_id)
        if category is None:
            await message.answer("Категория не найдена.")
            return
        category.is_active = False
        await session.commit()
    await message.answer(f"Категория «{category.name}» отключена. История сохранена.")


@router.message(Command("budget_set"))
async def budget_set(message: Message, settings: Settings) -> None:
    raw = admin_args(message, settings)
    if raw is None:
        await message.answer("Команда доступна только администратору.")
        return
    try:
        id_raw, amount_raw, period = [part.strip() for part in raw.split("|", 2)]
        category_id, amount = int(id_raw), parse_amount(amount_raw)
        year, month = map(int, period.split("-"))
        if not 1 <= month <= 12:
            raise ValueError
    except (ValueError, DomainError):
        await message.answer("Формат: /budget_set ID | 70000 | 2026-11")
        return
    async with session_factory() as session:
        category = await session.get(Category, category_id)
        if category is None:
            await message.answer("Категория не найдена.")
            return
        budget = await session.scalar(
            select(MonthlyBudget).where(
                MonthlyBudget.category_id == category_id,
                MonthlyBudget.year == year,
                MonthlyBudget.month == month,
            )
        )
        if budget is None:
            session.add(
                MonthlyBudget(category_id=category_id, year=year, month=month, limit_amount=amount)
            )
        else:
            budget.limit_amount = amount
        await session.commit()
    await message.answer(f"✅ {category.name}: {money(amount)} на {month:02d}.{year}.")


def create_dispatcher(settings: Settings) -> tuple[Bot, Dispatcher]:
    session = AiohttpSession(proxy=settings.telegram_proxy_url)
    bot = Bot(token=settings.telegram_bot_token, session=session)
    dispatcher = Dispatcher()
    dispatcher["settings"] = settings
    dispatcher.include_router(router)
    return bot, dispatcher
