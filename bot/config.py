import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List

class Settings(BaseSettings):
    # Support both BOT_TOKEN and TELEGRAM_BOT_TOKEN
    bot_token_raw: str = Field("", validation_alias="BOT_TOKEN")
    telegram_bot_token_raw: str = Field("", validation_alias="TELEGRAM_BOT_TOKEN")
    database_url: str = Field("", validation_alias="DATABASE_URL")
    admin_telegram_ids: str = Field("", validation_alias="ADMIN_TELEGRAM_IDS")
    admin_ids_raw: str = Field("", validation_alias="ADMIN_IDS")
    developer_username: str = Field("tgekaiva", validation_alias="DEVELOPER_USERNAME")
    initial_credits: int = Field(3, validation_alias="INITIAL_CREDITS")
    default_recharge_amount: int = Field(10, validation_alias="DEFAULT_RECHARGE_AMOUNT")
    log_level: str = Field("INFO", validation_alias="LOG_LEVEL")
    port: int = Field(10000, validation_alias="PORT")

    @property
    def bot_token(self) -> str:
        return (
            self.bot_token_raw
            or self.telegram_bot_token_raw
            or os.environ.get("BOT_TOKEN", "")
            or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        )

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
        return [int(uid.strip()) for uid in raw.split(",") if uid.strip().isdigit()]

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

config = Settings()
