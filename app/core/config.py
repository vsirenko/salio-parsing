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

    # --- Fetching ---
    # A crawler that hammers a shop gets blocked, and a blocked channel produces nothing
    # until somebody notices — which is slower than crawling slowly.
    #
    # Two limits, because they answer two questions and multiplying them together is how a
    # polite crawler becomes a slow one without anyone deciding to. The first is how many
    # requests may be open at once; the second is how many may be started per second,
    # whatever is open.
    #
    # Eight and eight, measured rather than guessed. The legacy parser ran six to eight
    # threads with no spacing at all against these same shops for years; at the roughly
    # 0.9 s a product page takes, eight open connections would reach nearly nine requests a
    # second, so here the ceiling is what actually binds — which is the point of having
    # one. Measured on a live shop: 5.1 products a second at six slots, and the ceiling
    # holds the eighth slot to 8. A full pass of 1400 products is about three minutes.
    fetch_concurrency: int = Field(default=8, ge=1, le=32)
    # 0 disables the ceiling and leaves concurrency as the only limit. Do not: it is what
    # protects a shop that starts answering in fifty milliseconds, which concurrency alone
    # does not.
    fetch_rate_per_second: float = Field(default=8.0, ge=0.0, le=200.0)
    fetch_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    fetch_retries: int = Field(default=3, ge=0, le=10)
    fetch_user_agent: str = "salio-parsing/0.1 (+https://example.com/bot)"
    # What a proxy check asks for through each address: a page that answers with the
    # address it saw, so the check says which one the shop would see.
    proxy_check_url: str = "https://api.ipify.org?format=json"
    proxy_check_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    # Where a worker keeps the bytes a shop served. Its own disk rather than the database:
    # a parser is wrong more often than a site changes, and every fix is worth only what it
    # costs to re-apply — with a snapshot that is nothing, without one it is another crawl.
    snapshot_dir: str = "data/snapshots"

    # --- The collector's own account ---
    # A worker signs in like anyone else and reaches a different set of routes, because
    # the audience decides that. It is not an administrator: a parser runs hostile input
    # through itself all day, and a compromised one holding an admin token could do
    # anything an administrator can.
    worker_email: str = "worker@example.com"
    worker_password: SecretStr = SecretStr("worker-password")
    # Where a worker reaches the service. Inside compose this is the service name.
    api_base_url: str = "http://localhost:8080"

    # --- Ingestion ---
    # A batch is posted gzipped: product JSON compresses by roughly an order of magnitude
    # and the difference is paid on every pass of every channel. The cap is a safety
    # limit, not a tuning knob — a few kilobytes of gzip can expand to gigabytes.
    max_decompressed_body_mb: int = Field(default=32, ge=1, le=512)
    # How many observations one request may carry. Above this the worker splits, which
    # keeps one request's memory bounded no matter how large a catalogue is.
    max_batch_offers: int = Field(default=500, ge=1, le=5000)
    # How many products a worker reads before handing them over, rather than handing over
    # a whole shop at the end: what a run collects reaches the database while it runs, and a
    # worker that dies at nine tenths has lost one slice rather than everything.
    worker_handover_every: int = Field(default=100, ge=1, le=5000)

    # --- Collection scheduler ---
    # Its own process: inside the API it would duplicate per uvicorn worker and die with
    # it. Single instance is a Postgres advisory lock, not a row — a lock in a table needs
    # a TTL, a heartbeat and a way to steal a stale one, and an advisory lock is released
    # when the connection drops, which is the same semantics with none of the machinery.
    scheduler_tick_seconds: int = Field(default=20, ge=1, le=600)
    # A registry change is read into stored listings once the changes have gone quiet this
    # long, a batch of this many listings per scheduler tick.
    reread_quiet_seconds: int = Field(default=60, ge=0, le=3600)
    reread_batch: int = Field(default=500, ge=1, le=5000)
    # Deliberately low. Two concurrent crawls on a small box is how the memory limit is
    # found, and a channel collects far faster with a few neighbours than with a dozen.
    scheduler_max_running: int = Field(default=1, ge=1, le=16)
    # What the scheduler spawns for one run. `{run_id}`, `{source_id}` and `{kind}` are
    # substituted; the process is expected to finish the run itself.
    worker_command: str = "python -m app.features.runs.worker --run-id {run_id}"
    # A worker still going after this is killed and its run recorded as failed. Without it
    # one hung channel holds its own live-run slot forever.
    run_timeout_minutes: int = Field(default=60, ge=1, le=1440)

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
    # A rule's match is listed for review when the judge gives the listing less than this
    # chance of naming the entry's own model. Measured, unlike the one above: over all 8982
    # live matches on 22.09.2026, below 0.1 about three flags in four were real misfiles,
    # between 0.1 and 0.5 fewer than one in ten — mostly entry names carrying `5G` or `Z`.
    judge_doubt_below: float = Field(default=0.1, ge=0.0, le=1.0)

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
