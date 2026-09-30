import os
import re
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List

def clean_database_url(raw_url: str) -> str:
    """Normalize any database URL format for asyncpg + SQLAlchemy and fix Neon pooler SNI."""
    if not raw_url:
        return ""
    url = raw_url.strip().strip('"').strip("'")
    if url.startswith("DATABASE_URL="):
        url = url.split("=", 1)[1].strip().strip('"').strip("'")
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[11:]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[13:]

    # asyncpg requires ssl=require instead of sslmode=require
    if "sslmode=require" in url:
        url = url.replace("sslmode=require", "ssl=require")

    # Clean channel_binding parameter unsupported by asyncpg
    if "&channel_binding=require" in url:
        url = url.replace("&channel_binding=require", "")
    if "?channel_binding=require&" in url:
        url = url.replace("channel_binding=require&", "")
    elif "?channel_binding=require" in url:
        url = url.replace("?channel_binding=require", "")

    # For Neon: remove -pooler suffix so SQLAlchemy uses direct compute connection.
    # This prevents PgBouncer SNI authentication failure on external hosts like Render.
    if "-pooler." in url:
        url = url.replace("-pooler.", ".")

    return url

class Settings(BaseSettings):
    bot_token_raw: str = Field("", validation_alias="BOT_TOKEN")
    telegram_bot_token_raw: str = Field("", validation_alias="TELEGRAM_BOT_TOKEN")
    database_url_raw: str = Field("", validation_alias="DATABASE_URL")
    admin_telegram_ids: str = Field("", validation_alias="ADMIN_TELEGRAM_IDS")
    admin_ids_raw: str = Field("", validation_alias="ADMIN_IDS")
    developer_username: str = Field("tgekaiva", validation_alias="DEVELOPER_USERNAME")
    initial_credits: int = Field(3, validation_alias="INITIAL_CREDITS")
    default_recharge_amount: int = Field(10, validation_alias="DEFAULT_RECHARGE_AMOUNT")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    port: int = Field(10000, validation_alias="PORT")

    @property
    def bot_token(self) -> str:
        token = (
            self.bot_token_raw
            or self.telegram_bot_token_raw
            or os.environ.get("BOT_TOKEN", "")
            or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        ).strip().strip('"').strip("'")
        if token.startswith("BOT_TOKEN="):
            token = token.split("=", 1)[1].strip().strip('"').strip("'")
        return token

    @property
    def database_url(self) -> str:
        raw = (
            self.database_url_raw
            or os.environ.get("DATABASE_URL", "")
        )
        return clean_database_url(raw)

    @property
    def admin_ids(self) -> List[int]:
        raw = (
            self.admin_telegram_ids
            or self.admin_ids_raw
            or os.environ.get("ADMIN_IDS", "")
            or os.environ.get("ADMIN_TELEGRAM_IDS", "")
        )
        if not raw:
            return []
        # clean any extra characters
        cleaned_ids = []
        for uid in raw.replace(";", ",").split(","):
            val = uid.strip().strip('"').strip("'")
            if val.isdigit():
                cleaned_ids.append(int(val))
        return cleaned_ids

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

config = Settings()
