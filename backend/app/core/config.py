from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Inventario Operativo"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://inventario:inventario@localhost:5432/inventario"
    )
    migration_database_url: str | None = None
    session_cookie_name: str = "inventario_session"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cors_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    cors_origin_regex: str | None = None

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("API_PREFIX debe comenzar con /")
        return value.rstrip("/")

    @field_validator("cookie_secure")
    @classmethod
    def require_secure_production_cookie(cls, value: bool, info):
        environment = info.data.get("environment")
        if environment == "production" and not value:
            raise ValueError("COOKIE_SECURE debe ser true en producción")
        return value

    @field_validator("cookie_samesite")
    @classmethod
    def require_secure_cross_site_cookie(cls, value: str, info):
        cookie_secure = info.data.get("cookie_secure")
        if value == "none" and not cookie_secure:
            raise ValueError("COOKIE_SECURE debe ser true cuando COOKIE_SAMESITE=none")
        return value

    @field_validator("cors_origin_regex", mode="before")
    @classmethod
    def empty_cors_regex_is_disabled(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
