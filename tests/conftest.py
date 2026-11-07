import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:testtoken_for_tests")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
