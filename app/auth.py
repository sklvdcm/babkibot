import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings

SESSION_COOKIE = "babki_session"
SESSION_SECONDS = 60 * 60 * 24 * 30
ATTEMPT_WINDOW = 15 * 60
MAX_ATTEMPTS = 5
_attempts: dict[str, deque[float]] = defaultdict(deque)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _signature(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()


def new_session(settings: Settings) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(24)
    payload = f"{nonce}.{int(time.time()) + SESSION_SECONDS}"
    cookie = f"{_encode(payload)}.{_signature(payload, settings.web_session_secret)}"
    return cookie, csrf_token(nonce, settings)


def session_nonce(cookie: str | None, settings: Settings) -> str | None:
    if not cookie or not settings.web_session_secret:
        return None
    try:
        encoded, supplied_signature = cookie.rsplit(".", 1)
        payload = _decode(encoded)
        nonce, expiry_raw = payload.rsplit(".", 1)
        if int(expiry_raw) < int(time.time()):
            return None
        if not hmac.compare_digest(
            supplied_signature, _signature(payload, settings.web_session_secret)
        ):
            return None
        return nonce
    except (ValueError, UnicodeError):
        return None


def csrf_token(nonce: str, settings: Settings) -> str:
    return _signature(f"csrf:{nonce}", settings.web_session_secret)


def require_web_session(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    nonce = session_nonce(request.cookies.get(SESSION_COOKIE), settings)
    if nonce is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Войдите снова")
    return nonce


def require_csrf(
    nonce: Annotated[str, Depends(require_web_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = csrf_token(nonce, settings)
    if not x_csrf_token or not hmac.compare_digest(x_csrf_token, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Обновите страницу")


def check_login_rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = _attempts[key]
    while attempts and attempts[0] < now - ATTEMPT_WINDOW:
        attempts.popleft()
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток. Попробуйте через 15 минут",
        )
    attempts.append(now)


def clear_login_attempts(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    _attempts.pop(key, None)


def set_session_cookie(response: Response, value: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        value,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
