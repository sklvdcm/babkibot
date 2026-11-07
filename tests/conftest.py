import os

os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
