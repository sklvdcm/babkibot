from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://budget:change_me@db:5432/budget"
    shortcut_tokens: dict[str, str] = Field(default_factory=dict)
    shortcut_users: dict[str, str] = Field(default_factory=dict)
    web_password: str = ""
    web_session_secret: str = ""
    cookie_secure: bool = True
    timezone: str = "Europe/Moscow"
    log_level: str = "INFO"

    @field_validator("shortcut_tokens")
    @classmethod
    def validate_tokens(cls, value: dict[str, str]) -> dict[str, str]:
        weak = [user_id for user_id, token in value.items() if len(token) < 32]
        if weak:
            raise ValueError(f"Shortcut tokens must be at least 32 characters: {weak}")
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
