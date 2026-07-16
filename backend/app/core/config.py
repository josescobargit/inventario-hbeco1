from functools import lru_cache
from urllib.parse import SplitResult, urlsplit, urlunsplit
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPABASE_POOLER_HOST = "aws-0-us-east-1.pooler.supabase.com"


def _normalize_supabase_database_url(value: str) -> str:
    if "pooler.supabase.com:5432/" in value:
        return value.replace(
            "pooler.supabase.com:5432/",
            "pooler.supabase.com:6543/",
            1,
        )

    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if not (
        parsed.scheme.startswith("postgresql")
        and hostname.startswith("db.")
        and hostname.endswith(".supabase.co")
    ):
        return value

    project_ref = hostname.removeprefix("db.").removesuffix(".supabase.co")
    if not project_ref:
        return value

    raw_userinfo = ""
    if parsed.netloc and "@" in parsed.netloc:
        raw_userinfo = parsed.netloc.rsplit("@", 1)[0]
    raw_password = ""
    if ":" in raw_userinfo:
        raw_password = raw_userinfo.split(":", 1)[1]

    userinfo = f"postgres.{project_ref}"
    if raw_password:
        userinfo = f"{userinfo}:{raw_password}"

    query = parsed.query
    if "sslmode=" not in query:
        query = f"{query}&sslmode=require" if query else "sslmode=require"

    return urlunsplit(
        SplitResult(
            scheme="postgresql+psycopg",
            netloc=f"{userinfo}@{SUPABASE_POOLER_HOST}:6543",
            path=parsed.path or "/postgres",
            query=query,
            fragment=parsed.fragment,
        )
    )


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

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def normalize_supabase_pooler_port(cls, value: str | None) -> str | None:
        if value:
            return _normalize_supabase_database_url(value)
        return value

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
