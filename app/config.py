from typing import Set
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(default="", alias="BOT_TOKEN")
    default_gemini_key: str = Field(default="", alias="DEFAULT_GEMINI_KEY")

    # Whitelist & Permissions
    whitelist_enabled: bool = Field(default=True, alias="WHITELIST_ENABLED")
    allowed_users_str: str = Field(default="", alias="ALLOWED_USERS")

    # Encryption (Fernet key for custom user API keys)
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")

    # Storage & TTL
    database_path: str = Field(default="tg_pulse.db", alias="DATABASE_PATH")
    buffer_ttl_hours: int = Field(default=48, alias="BUFFER_TTL_HOURS")

    @property
    def allowed_users(self) -> Set[int]:
        """Parse comma-separated user IDs into a set of integers."""
        if not self.allowed_users_str:
            return set()
        user_ids = set()
        for item in self.allowed_users_str.split(","):
            cleaned = item.strip()
            if cleaned.isdigit() or (cleaned.startswith("-") and cleaned[1:].isdigit()):
                user_ids.add(int(cleaned))
        return user_ids

    def is_user_allowed(self, user_id: int) -> bool:
        """Check if user has access based on whitelist settings."""
        if not self.whitelist_enabled:
            return True
        return user_id in self.allowed_users


settings = Settings()
