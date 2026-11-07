import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.auth import SESSION_COOKIE, session_nonce
from app.config import get_settings
from app.db import engine
from app.migrations import migrate_legacy_schema
from app.models import Base
from app.web import router as web_router

settings = get_settings()
static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=settings.log_level)
    await migrate_legacy_schema(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Babki", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.include_router(api_router)
app.include_router(web_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(("/app", "/web/", "/auth/")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
async def root(request: Request) -> RedirectResponse:
    authenticated = session_nonce(request.cookies.get(SESSION_COOKIE), settings) is not None
    return RedirectResponse("/app" if authenticated else "/login", status_code=303)


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    if session_nonce(request.cookies.get(SESSION_COOKIE), settings) is not None:
        return RedirectResponse("/app", status_code=303)
    return FileResponse(static_dir / "login.html")


@app.get("/app", include_in_schema=False)
async def app_page(request: Request):
    if session_nonce(request.cookies.get(SESSION_COOKIE), settings) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(static_dir / "app.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=settings.log_level.lower())


if __name__ == "__main__":
    run()
