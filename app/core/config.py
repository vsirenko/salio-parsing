"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# HS256 needs >= 32 bytes of key material (RFC 7518).
DEV_SECRET_KEY = "dev-secret-change-me-before-deploying-anywhere"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Products API"
    app_version: str = "0.1.0"
    environment: Literal["local", "dev", "staging", "production"] = "local"
    debug: bool = False
    log_level: str = "INFO"

    # --- HTTP ---
    host: str = "0.0.0.0"
    port: int = 8000
    api_prefix: str = "/api"

    # --- Docs ---
    # Turn off to hide Swagger/ReDoc in production.
    docs_enabled: bool = True

    # --- Auth ---
    # Generate a real one with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    secret_key: str = Field(default=DEV_SECRET_KEY, min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # Dev convenience: create the demo admin/customer accounts on startup.
    seed_users: bool = True

    # --- CORS ---
    # Comma-separated in .env, e.g. CORS_ORIGINS=http://localhost:3000,https://app.example.com
    # NoDecode: keep pydantic-settings from JSON-parsing the value so the validator below
    # can accept a plain comma-separated string.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        """Fail fast instead of shipping dev credentials to production."""
        if not self.is_production:
            return self
        if self.secret_key == DEV_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set to a real secret in production")
        if self.seed_users:
            raise ValueError("SEED_USERS must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — import this everywhere instead of building Settings()."""
    return Settings()


settings = get_settings()
