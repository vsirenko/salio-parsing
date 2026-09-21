"""User lookup and authentication.

In-memory storage, same as ProductService — replace the dict with DB calls and the
API layer stays untouched.
"""

import asyncio
from datetime import UTC, datetime

from app.core import audit
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import AuthError, hash_password, verify_password
from app.schemas.auth import Audience
from app.schemas.pagination import Pagination
from app.schemas.user import Role, UserCreate, UserInDB

# Dev-only accounts. `seed_users` is forced off in production by Settings.
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
    def __init__(self) -> None:
        self._items: dict[int, UserInDB] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()
        if settings.seed_users:
            self._seed()

    def _seed(self) -> None:
        for email, password, full_name, role in SEED_ACCOUNTS:
            self._insert(UserCreate(email=email, password=password, full_name=full_name, role=role))

    def _insert(self, payload: UserCreate) -> UserInDB:
        user = UserInDB(
            id=self._next_id,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            created_at=datetime.now(UTC),
            last_login_at=None,
            password_hash=hash_password(payload.password),
        )
        self._items[user.id] = user
        self._next_id += 1
        return user

    async def get_user(self, user_id: int) -> UserInDB:
        user = self._items.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def get_by_id_or_none(self, user_id: int) -> UserInDB | None:
        return self._items.get(user_id)

    async def get_by_email(self, email: str) -> UserInDB | None:
        needle = email.strip().lower()
        return next((u for u in self._items.values() if u.email == needle), None)

    async def list_users(
        self, pagination: Pagination, *, role: Role | None = None
    ) -> tuple[list[UserInDB], int]:
        items = [u for u in self._items.values() if role is None or u.role is role]
        items.sort(key=lambda u: u.id)
        return pagination.slice(items), len(items)

    async def create_user(self, payload: UserCreate) -> UserInDB:
        async with self._lock:
            if await self.get_by_email(payload.email):
                raise ConflictError(f"User '{payload.email}' already exists")
            user = self._insert(payload)

        audit.set_target("user", user.id)
        audit.record_changes(**payload.model_dump(exclude={"password"}))
        return user

    async def authenticate(self, email: str, password: str, audience: Audience) -> UserInDB:
        """Verify credentials and that this account belongs to the requested panel."""
        # Recorded even when the attempt fails — failed admin sign-ins are exactly
        # what an audit trail is read for.
        audit.set_actor(email=email.strip().lower())
        user = await self.get_by_email(email)

        # Hash a throwaway value for unknown emails so response time does not reveal
        # whether the account exists.
        if user is None:
            hash_password(password)
            raise AuthError()
        if not verify_password(password, user.password_hash):
            raise AuthError()
        if not user.is_active:
            raise AuthError("Account is disabled", code="account_disabled")
        if user.role not in AUDIENCE_ROLES[audience]:
            raise AuthError("This account cannot sign in here", code="wrong_panel")

        user.last_login_at = datetime.now(UTC)
        audit.set_actor(actor_id=user.id)
        return user


user_service = UserService()
