from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_proxy_url: str | None = None
    database_url: str = "postgresql+asyncpg://babkibot:change_me@db:5432/babkibot"
    allowed_telegram_ids: Annotated[set[int], NoDecode] = Field(default_factory=set)
    admin_telegram_ids: Annotated[set[int], NoDecode] = Field(default_factory=set)
    shortcut_tokens: dict[str, str] = Field(default_factory=dict)
    timezone: str = "Europe/Moscow"
    log_level: str = "INFO"

    @field_validator("allowed_telegram_ids", "admin_telegram_ids", mode="before")
    @classmethod
    def parse_id_list(cls, value: object) -> object:
        if isinstance(value, str):
            return {int(item.strip()) for item in value.split(",") if item.strip()}
        return value

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
    return Settings()  # type: ignore[call-arg]
