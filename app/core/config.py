"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — import this everywhere instead of building Settings()."""
    return Settings()


settings = get_settings()
