# BabkiBot

Telegram-бот для общего учёта расходов с месячными бюджетами и HTTP API для iPhone Shortcuts.

## Возможности

- доступ только Telegram ID из whitelist;
- запись траты через пошаговый Telegram-флоу с двумя подтверждениями;
- запись траты через iPhone Shortcut;
- категории и отдельный лимит на каждый месяц;
- остаток и сумма расходов по каждой категории;
- история: кто, когда, куда и сколько потратил;
- защита API персональными bearer-токенами и от повторной отправки запроса.

## Быстрый запуск

1. Создайте бота через `@BotFather` и получите токен.
2. Скопируйте конфигурацию: `cp .env.example .env`.
3. Заполните `.env`:
   - `TELEGRAM_BOT_TOKEN`;
   - `ALLOWED_TELEGRAM_IDS` — Telegram ID через запятую;
   - `ADMIN_TELEGRAM_IDS` — кто может менять категории и бюджеты;
   - `SHORTCUT_TOKENS` — JSON с отдельным случайным токеном для каждого iPhone;
   - одинаковый надёжный пароль в `POSTGRES_PASSWORD` и `DATABASE_URL`.
4. Запустите: `docker compose up -d --build`.
5. Проверьте: `curl http://127.0.0.1:8000/health`.

Для генерации токена Shortcut: `openssl rand -hex 32`.

На сервере API слушает только localhost. Перед подключением iPhone его нужно открыть по HTTPS через reverse proxy (Caddy/Nginx) и домен. Это сделаем после получения доступа к хосту.

## Telegram-команды

Пользовательские:

- `/spend` — записать трату;
- `/budgets` — посмотреть лимит, расходы и остаток;
- `/history` — последние 15 трат.

Администраторские:

- `/category_add Продукты | 50000`;
- `/category_edit 1 | Продукты и быт | 60000`;
- `/category_disable 1` — скрывает категорию, не удаляя историю;
- `/budget_set 1 | 70000 | 2026-12` — задаёт лимит категории на месяц.

## API для iPhone Shortcut

Сначала Shortcut получает категории:

```http
GET /api/v1/categories
Authorization: Bearer <персональный токен>
```

Затем отправляет подтверждённую трату:

```http
POST /api/v1/expenses
Authorization: Bearer <персональный токен>
Content-Type: application/json

{
  "amount": 1500,
  "category_id": 1,
  "idempotency_key": "случайный UUID для этого запуска"
}
```

`idempotency_key` не позволяет случайному повтору HTTP-запроса создать две одинаковые траты.

## Разработка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest
```

Таблицы создаются при первом старте. Перед дальнейшим развитием и изменениями схемы следует включить версионируемые Alembic-миграции.
