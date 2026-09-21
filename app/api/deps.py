"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.security import AuthError, ForbiddenError, decode_token
from app.db.session import get_session
from app.schemas.auth import Audience, TokenType
from app.schemas.user import Role, UserInDB
from app.services.audit import AuditService
from app.services.products import ProductService
from app.services.users import UserService

# auto_error=False so a missing header raises our own AuthError shape, not Starlette's.
bearer_scheme = HTTPBearer(auto_error=False)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_product_service(session: SessionDep) -> ProductService:
    return ProductService(session)


def get_user_service(session: SessionDep) -> UserService:
    return UserService(session)


def get_audit_service(session: SessionDep) -> AuditService:
    return AuditService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


async def _authenticate(
    credentials: Credentials, users: UserService, audience: Audience
) -> UserInDB:
    if credentials is None:
        raise AuthError("Missing bearer token")

    payload = decode_token(
        credentials.credentials, expected_audience=audience, expected_type=TokenType.ACCESS
    )
    user = await users.get_by_id_or_none(payload.sub)
    if user is None or not user.is_active:
        raise AuthError("Account is no longer active")

    audit.set_actor(actor_id=user.id, email=user.email)
    return user


async def get_current_client(credentials: Credentials, users: UserServiceDep) -> UserInDB:
    """Signed-in customer. Only accepts tokens minted for the client panel."""
    return await _authenticate(credentials, users, Audience.CLIENT)


async def get_current_admin(credentials: Credentials, users: UserServiceDep) -> UserInDB:
    """Signed-in staff member. Only accepts tokens minted for the admin panel."""
    user = await _authenticate(credentials, users, Audience.ADMIN)
    # The audience check above already covers this; the role check is the second lock.
    if user.role is not Role.ADMIN:
        raise ForbiddenError()
    return user


CurrentClient = Annotated[UserInDB, Depends(get_current_client)]
CurrentAdmin = Annotated[UserInDB, Depends(get_current_admin)]
