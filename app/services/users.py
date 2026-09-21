"""User lookup and authentication."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import AuthError, hash_password, verify_password
from app.db.models import User
from app.db.query import paginated
from app.schemas.auth import Audience
from app.schemas.pagination import Pagination
from app.schemas.user import Role, UserCreate, UserInDB

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
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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

    async def authenticate(self, email: str, password: str, audience: Audience) -> UserInDB:
        """Verify credentials and that this account belongs to the requested panel."""
        # Recorded even when the attempt fails — failed admin sign-ins are exactly
        # what an audit trail is read for.
        audit.set_actor(email=email.strip().lower())
        user = await self._row_by_email(email)

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

        user.last_login_at = datetime.now(UTC)
        await self.session.flush()
        audit.set_actor(actor_id=user.id)
        return UserInDB.model_validate(user)


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
