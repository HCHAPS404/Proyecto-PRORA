from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    _ephemeral_jwt_secret: bool = PrivateAttr(default=False)
    _database_ssl: bool = PrivateAttr(default=False)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PRORA_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PRORA API"
    app_version: str = "1.0.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite+aiosqlite:///./prora.db"
    database_echo: bool = False
    auto_create_tables: bool = True
    # Forzar SSL hacia Postgres remoto (Render/Neon). asyncpg no usa ?ssl= en la URL.
    database_ssl: bool | None = None
    # Si true, sync/train se ejecutan en BackgroundTasks de la API (plan free sin worker).
    jobs_inline: bool = False

    jwt_secret: SecretStr | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    log_level: str = "INFO"

    # External public-data connectors. Tokens are optional for development,
    # but strongly recommended to avoid anonymous Socrata throttling.
    socrata_app_token: SecretStr | None = None
    ingestion_batch_size: int = 10_000
    institutional_upload_dir: str = "./data/inbox"
    raw_snapshot_dir: str = "./data/raw"
    max_upload_mb: int = 100

    # Model artifacts are immutable directories with manifests and checksums.
    model_registry_path: str = "./artifacts/models"

    # Optional grounded assistant provider. Without a key the deterministic,
    # database-grounded assistant remains fully functional.
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    @model_validator(mode="after")
    def validate_runtime_security(self) -> Settings:
        # PaaS (Render, Railway, etc.) suelen entregar postgres://; SQLAlchemy async
        # requiere el driver asyncpg. SSL se configura en connect_args (no en la URL):
        # asyncpg no acepta ?ssl=require como psycopg2.
        if self.database_url.startswith("postgres://"):
            self.database_url = "postgresql+asyncpg://" + self.database_url[len("postgres://") :]
        elif self.database_url.startswith("postgresql://"):
            self.database_url = (
                "postgresql+asyncpg://" + self.database_url[len("postgresql://") :]
            )

        if self.database_url.startswith("postgresql+asyncpg://"):
            from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

            parsed = urlparse(self.database_url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            ssl_hint = query.pop("ssl", None) or query.pop("sslmode", None)
            if query != dict(parse_qsl(parsed.query, keep_blank_values=True)):
                self.database_url = urlunparse(parsed._replace(query=urlencode(query)))

            lower_host = (parsed.hostname or "").lower()
            is_local = lower_host in {"localhost", "127.0.0.1"} or lower_host.endswith(
                ".local"
            )
            # Hosts internos de Render (p. ej. dpg-xxx-a) no llevan punto ni TLS.
            is_private_host = "." not in lower_host
            if self.database_ssl is not None:
                self._database_ssl = self.database_ssl
            elif ssl_hint is not None:
                self._database_ssl = str(ssl_hint).lower() not in {"0", "false", "disable", "off"}
            else:
                self._database_ssl = not is_local and not is_private_host
        else:
            self._database_ssl = False

        if self.environment == "production":
            if self.jwt_secret is None or len(self.jwt_secret.get_secret_value()) < 32:
                raise ValueError(
                    "PRORA_JWT_SECRET de al menos 32 caracteres es obligatorio en produccion"
                )
            if self.auto_create_tables:
                raise ValueError(
                    "PRORA_AUTO_CREATE_TABLES debe ser false en produccion; use Alembic"
                )
        elif self.jwt_secret is None:
            # Clave efimera, no una credencial por defecto; solo sirve para este proceso.
            self.jwt_secret = SecretStr(secrets.token_urlsafe(48))
            self._ephemeral_jwt_secret = True

        if not self.api_prefix.startswith("/"):
            raise ValueError("api_prefix debe comenzar por '/'")
        if self.access_token_minutes < 1 or self.refresh_token_days < 1:
            raise ValueError("La duracion de tokens debe ser positiva")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def uses_ephemeral_jwt_secret(self) -> bool:
        return self._ephemeral_jwt_secret

    @property
    def uses_database_ssl(self) -> bool:
        return self._database_ssl

    @property
    def database_connect_args(self) -> dict:
        """Argumentos extra para asyncpg (SSL obligatorio en Postgres de Render)."""
        if self._database_ssl and self.database_url.startswith("postgresql+asyncpg://"):
            return {"ssl": True}
        return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
