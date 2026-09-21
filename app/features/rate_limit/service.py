"""Sign-in rate limiting.

Counted in PostgreSQL rather than in process memory: several api replicas must share
one budget, otherwise the real limit is the configured one multiplied by the number
of replicas.

Like the audit trail, the counters are written through `session_factory` in their own
transaction. A failed sign-in raises, the request transaction is rolled back, and a
failure recorded on that session would be rolled back with it — leaving the limiter
counting nothing but successes.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.exceptions import RateLimitError
from app.db.models import LoginAttempt
from app.db.session import session_factory

Scope = Literal["ip", "account"]


class LoginRateLimiter:
    """Locks a bucket out for a while once it has failed too often.

    The lock doubles with every further failure, so an attacker who keeps going gets
    slower while someone who mistyped a password once waits the base delay at worst.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_failures: dict[Scope, int] | None = None,
        window: timedelta | None = None,
        lock: timedelta | None = None,
        max_lock: timedelta | None = None,
    ) -> None:
        self.enabled = enabled
        self.max_failures: dict[Scope, int] = max_failures or {
            "account": settings.login_max_failures_per_account,
            "ip": settings.login_max_failures_per_ip,
        }
        self.window = window or timedelta(minutes=settings.login_failure_window_minutes)
        self.lock = lock or timedelta(seconds=settings.login_lock_seconds)
        self.max_lock = max_lock or timedelta(seconds=settings.login_max_lock_seconds)

    async def check(self, scope: Scope, key: str) -> None:
        """Raise if this bucket is currently locked out."""
        if not self.enabled:
            return

        now = datetime.now(UTC)
        async with session_factory() as session:
            locked_until = await session.scalar(
                select(LoginAttempt.locked_until).where(
                    LoginAttempt.scope == scope, LoginAttempt.key == key
                )
            )

        if locked_until is not None and locked_until > now:
            # Rounded up so a caller that waits exactly this long is past the lock.
            raise RateLimitError(retry_after=int((locked_until - now).total_seconds()) + 1)

    async def record_failure(self, scope: Scope, key: str) -> None:
        """Count one failed attempt and extend the lock if it crossed the limit."""
        if not self.enabled:
            return

        now = datetime.now(UTC)
        window_start = now - self.window

        # Upserted rather than read-then-written: two sign-in attempts racing on the
        # same account would otherwise both read the old count and store limit - 1.
        expired = LoginAttempt.window_start < window_start
        stmt = (
            insert(LoginAttempt)
            .values(scope=scope, key=key, failures=1, window_start=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=[LoginAttempt.scope, LoginAttempt.key],
                set_={
                    "failures": case((expired, 1), else_=LoginAttempt.failures + 1),
                    "window_start": case((expired, now), else_=LoginAttempt.window_start),
                    "updated_at": now,
                },
            )
            .returning(LoginAttempt.failures)
        )

        async with session_factory() as session:
            failures = await session.scalar(stmt)
            over = failures - self.max_failures[scope]
            if over >= 0:
                # The exponent is capped before it is used: max_lock bounds the result
                # anyway, and a long window with a small limit could otherwise raise
                # 2 to a power large enough to overflow the multiplication.
                lock = min(self.lock * 2 ** min(over, 32), self.max_lock)
                await session.execute(
                    update(LoginAttempt)
                    .where(LoginAttempt.scope == scope, LoginAttempt.key == key)
                    .values(locked_until=now + lock)
                )
            await session.commit()

    async def reset(self, scope: Scope, key: str) -> None:
        """Forget a bucket after a successful sign-in."""
        if not self.enabled:
            return

        async with session_factory() as session:
            await session.execute(
                delete(LoginAttempt).where(LoginAttempt.scope == scope, LoginAttempt.key == key)
            )
            await session.commit()
