"""User lookup and authentication."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import AuthError, hash_password, verify_password
from app.db.models import User
from app.db.query import paginated
from app.schemas.auth import Audience
from app.schemas.pagination import Pagination
from app.schemas.user import Role, UserCreate, UserInDB, UserUpdate
from app.services.rate_limit import LoginRateLimiter, Scope

# Dev-only accounts, created on startup. `seed_users` is forced off in production.
SEED_ACCOUNTS = (
    ("admin@example.com", "admin-password", "Site Admin", Role.ADMIN),
    ("customer@example.com", "customer-password", "Demo Customer", Role.CUSTOMER),
)

# Which roles may sign in to which panel.
AUDIENCE_ROLES: dict[Audience, set[Role]] = {
    Audience.CLIENT: {Role.CUSTOMER},
    Audience.ADMIN: {Role.ADMIN},
}


class UserService:
    def __init__(self, session: AsyncSession, limiter: LoginRateLimiter | None = None) -> None:
        self.session = session
        # Optional so the startup seeding, which never authenticates, needs no limiter.
        self.limiter = limiter

    async def get_user(self, user_id: int) -> UserInDB:
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return UserInDB.model_validate(user)

    async def get_by_id_or_none(self, user_id: int) -> UserInDB | None:
        user = await self.session.get(User, user_id)
        return UserInDB.model_validate(user) if user else None

    async def _row_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.strip().lower())
        return await self.session.scalar(stmt)

    async def get_by_email(self, email: str) -> UserInDB | None:
        row = await self._row_by_email(email)
        return UserInDB.model_validate(row) if row else None

    async def get_for_token(self, user_id: int, epoch: int, audience: Audience) -> UserInDB:
        """The account a token names, or AuthError if the token should no longer work.

        Every reason a valid signature is not enough lives here, so the access path and
        the refresh path cannot drift apart: the account may have been deleted,
        disabled, moved to the other panel, or had its sessions cut.
        """
        user = await self.get_by_id_or_none(user_id)
        if user is None or not user.is_active:
            raise AuthError("Account is no longer active")
        if user.role not in AUDIENCE_ROLES[audience]:
            raise AuthError("This account cannot sign in here", code="wrong_panel")
        if epoch != user.token_epoch:
            raise AuthError("Session has ended", code="session_revoked")
        return user

    async def list_users(
        self, pagination: Pagination, *, role: Role | None = None
    ) -> tuple[list[UserInDB], int]:
        stmt = select(User)
        if role is not None:
            stmt = stmt.where(User.role == role.value)

        rows, total = await paginated(self.session, stmt.order_by(User.id), pagination)
        return [UserInDB.model_validate(row) for row in rows], total

    async def create_user(self, payload: UserCreate) -> UserInDB:
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role.value,
            is_active=payload.is_active,
            password_hash=hash_password(payload.password),
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"User '{payload.email}' already exists") from exc

        await self.session.refresh(user)
        audit.set_target("user", user.id)
        audit.record_changes(**payload.model_dump(exclude={"password"}))
        return UserInDB.model_validate(user)

    async def update_user(self, user_id: int, payload: UserUpdate, *, actor_id: int) -> UserInDB:
        """Apply the fields that were sent, refusing edits that would lock the panel."""
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")

        # Named before the guards below, so a refused edit is recorded against the
        # account it was aimed at rather than at nothing.
        audit.set_target("user", user.id)

        sent = payload.model_dump(exclude_unset=True)
        role_changing = payload.role is not None and payload.role is not Role(user.role)
        losing_admin = Role(user.role) is Role.ADMIN and role_changing
        disabling = payload.is_active is False and user.is_active

        # Refusing self-removal is all that is needed to keep the panel reachable: the
        # admin making the request is by definition an active admin, so whoever else
        # they disable or demote, one is always left standing. A separate "last admin"
        # count would never be able to fire.
        if user.id == actor_id and (losing_admin or disabling):
            raise ConflictError("You cannot remove your own access", code="self_lockout")

        if "full_name" in sent:
            user.full_name = payload.full_name
        if payload.role is not None:
            user.role = payload.role.value
        if payload.is_active is not None:
            user.is_active = payload.is_active

        if disabling:
            # Disabling already stops the access path, which re-reads the account on
            # every request. Bumping the epoch as well means the refresh tokens that
            # were outstanding do not spring back to life if the account is re-enabled.
            user.token_epoch += 1

        await self.session.flush()
        await self.session.refresh(user)
        audit.record_changes(**sent)
        return UserInDB.model_validate(user)

    async def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> UserInDB:
        """Replace the caller's own password, ending every session opened before now."""
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")

        # Named before the checks below, so a refused change is recorded against the
        # account it was aimed at rather than at nothing.
        audit.set_target("user", user.id)

        # 422 rather than 401: the caller is signed in and their token is fine, it is
        # the password in the body that is wrong. A 401 here would send a client
        # straight into its token-refresh or sign-out path for no reason.
        if not verify_password(current_password, user.password_hash):
            raise ValidationError("Current password is incorrect", code="invalid_current_password")
        if verify_password(new_password, user.password_hash):
            raise ValidationError(
                "The new password must differ from the current one",
                code="password_unchanged",
            )

        user.password_hash = hash_password(new_password)
        user.token_epoch += 1
        await self.session.flush()
        await self.session.refresh(user)
        audit.record_changes(password_changed=True)
        return UserInDB.model_validate(user)

    async def authenticate(
        self, email: str, password: str, audience: Audience, *, ip: str | None = None
    ) -> UserInDB:
        """Verify credentials and that this account belongs to the requested panel."""
        normalized = email.strip().lower()
        # Recorded even when the attempt fails — failed admin sign-ins are exactly
        # what an audit trail is read for.
        audit.set_actor(email=normalized)

        # Empty when there is no limiter, which makes every loop below a no-op.
        buckets: list[tuple[Scope, str]] = []
        if self.limiter is not None:
            buckets = [("account", normalized)] + ([("ip", ip)] if ip else [])

        for scope, key in buckets:
            await self.limiter.check(scope, key)

        try:
            user = await self._verify(normalized, password, audience)
        except AuthError:
            # Only credential failures are counted. An attempt made while the bucket is
            # already locked raises above and never reaches here, so hammering a locked
            # account cannot extend its own lock — the count grows again once the lock
            # has expired, and that is what makes the next one longer.
            for scope, key in buckets:
                await self.limiter.record_failure(scope, key)
            raise

        # Only the account bucket is cleared. Clearing the address bucket too would let
        # anyone holding one valid account wipe the budget for every account behind
        # that address between guesses.
        if buckets:
            await self.limiter.reset("account", normalized)

        user.last_login_at = datetime.now(UTC)
        await self.session.flush()
        audit.set_actor(actor_id=user.id)
        return UserInDB.model_validate(user)

    async def _verify(self, normalized_email: str, password: str, audience: Audience) -> User:
        user = await self._row_by_email(normalized_email)

        # Hash a throwaway value for unknown emails so response time does not reveal
        # whether the account exists.
        if user is None:
            hash_password(password)
            raise AuthError()
        if not verify_password(password, user.password_hash):
            raise AuthError()
        if not user.is_active:
            raise AuthError("Account is disabled", code="account_disabled")
        if Role(user.role) not in AUDIENCE_ROLES[audience]:
            raise AuthError("This account cannot sign in here", code="wrong_panel")
        return user


async def seed_users(session: AsyncSession) -> int:
    """Create the demo accounts if they are missing. Idempotent."""
    service = UserService(session)
    created = 0
    for email, password, full_name, role in SEED_ACCOUNTS:
        if await service.get_by_email(email):
            continue
        await service.create_user(
            UserCreate(email=email, password=password, full_name=full_name, role=role)
        )
        created += 1
    await session.commit()
    return created
