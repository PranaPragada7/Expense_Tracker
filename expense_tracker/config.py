"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEVELOPMENT_SECRET = "local-development-secret-change-me"
DEFAULT_DATABASE_URL = "sqlite:///./expense_api.db"
DEFAULT_ACCESS_TOKEN_MINUTES = 60
DEFAULT_APP_ENV = "development"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings with safe production validation."""

    database_url: str = DEFAULT_DATABASE_URL
    jwt_secret: str = DEVELOPMENT_SECRET
    access_token_minutes: int = DEFAULT_ACCESS_TOKEN_MINUTES
    app_env: str = DEFAULT_APP_ENV
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            jwt_secret=os.environ.get("JWT_SECRET", DEVELOPMENT_SECRET),
            access_token_minutes=int(
                os.environ.get(
                    "ACCESS_TOKEN_MINUTES", str(DEFAULT_ACCESS_TOKEN_MINUTES)
                )
            ),
            app_env=os.environ.get("APP_ENV", DEFAULT_APP_ENV).lower(),
            log_level=os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.access_token_minutes < 1:
            raise ValueError("ACCESS_TOKEN_MINUTES must be at least 1")
        if self.app_env == "production" and self.jwt_secret == DEVELOPMENT_SECRET:
            raise ValueError("JWT_SECRET must be configured in production")
        if len(self.jwt_secret) < 24:
            raise ValueError("JWT_SECRET must contain at least 24 characters")
