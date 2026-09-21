"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    app_name: str = "salio-parsing"
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

    # --- Database ---
    database_url: str = "postgresql+asyncpg://app:app@localhost:55432/app"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False
    # Do not keep pooled connections. Needed where a connection cannot outlive the
    # context that opened it: tests (each client runs its own event loop) and
    # serverless runtimes.
    db_use_null_pool: bool = False

    # --- Auth ---
    # Generate a real one with: python -c "import secrets; print(secrets.token_urlsafe(48))"
    secret_key: str = Field(default=DEV_SECRET_KEY, min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # Dev convenience: create the demo admin/customer accounts on startup.
    seed_users: bool = True

    # --- Sign-in rate limit ---
    # Counted per account and per address. The per-address budget is the looser of the
    # two: a shared office NAT is one address for everybody behind it.
    login_rate_limit_enabled: bool = True
    login_max_failures_per_account: int = 5
    login_max_failures_per_ip: int = 20
    login_failure_window_minutes: int = 15
    # The lock doubles with every failure past the limit, up to the maximum.
    login_lock_seconds: int = 60
    login_max_lock_seconds: int = 3600

    # --- The judge (TypeSafe) ---
    # Judging is off unless a key is set. There is deliberately no separate "enabled"
    # flag: a flag and a key can disagree, and then the panel offers a button that
    # cannot work.
    typesafe_api_key: SecretStr | None = None
    # jev-latest moves. The concrete model that answered is stored on every verdict, so
    # a change is visible after the fact; pinning is a decision to make once there is
    # enough real data to say a newer model is better or worse for this catalogue.
    typesafe_model: str = "jev-latest"
    typesafe_timeout_seconds: float = 10.0
    # One listing is one request — the state differs per listing, so they cannot share
    # one. They are sent together instead, which is what keeps a pass over the queue from
    # taking its length in seconds.
    judge_concurrency: int = Field(default=4, ge=1, le=32)
    # Below this the answer is still recorded, and still not acted on. The number is a
    # starting point, not a measurement: the docs are explicit that a threshold has to be
    # evaluated against real data, and this catalogue has none yet.
    judge_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)

    # --- Audit ---
    # Trust X-Forwarded-For / X-Request-ID. Only enable behind a proxy that rewrites them.
    trust_proxy_headers: bool = False

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
    def judge_enabled(self) -> bool:
        """Whether anything may call out to TypeSafe. The key is the only switch."""
        return self.typesafe_api_key is not None

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
