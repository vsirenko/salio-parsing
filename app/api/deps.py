"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.net import client_ip
from app.core.security import Audience, AuthError, ForbiddenError, TokenType, decode_token
from app.db.session import get_session
from app.features.audit.service import AuditService
from app.features.countries.service import CountryService
from app.features.currencies.service import CurrencyService
from app.features.markets.service import MarketService
from app.features.products.service import ProductService
from app.features.rate_limit.service import LoginRateLimiter
from app.features.users.schemas import Role, UserInDB
from app.features.users.service import UserService

# auto_error=False so a missing header raises our own AuthError shape, not Starlette's.
bearer_scheme = HTTPBearer(auto_error=False)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_product_service(session: SessionDep) -> ProductService:
    return ProductService(session)


# Stateless: it holds the configured limits and reaches the counters through the
# session factory, so one instance serves every request.
login_rate_limiter = LoginRateLimiter(enabled=settings.login_rate_limit_enabled)


def get_user_service(session: SessionDep) -> UserService:
    return UserService(session, limiter=login_rate_limiter)


def get_client_ip(request: Request) -> str | None:
    return client_ip(request, trust_proxy_headers=settings.trust_proxy_headers)


def get_audit_service(session: SessionDep) -> AuditService:
    return AuditService(session)


def get_currency_service(session: SessionDep) -> CurrencyService:
    return CurrencyService(session)


def get_country_service(session: SessionDep) -> CountryService:
    return CountryService(session)


def get_market_service(session: SessionDep) -> MarketService:
    return MarketService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
CurrencyServiceDep = Annotated[CurrencyService, Depends(get_currency_service)]
CountryServiceDep = Annotated[CountryService, Depends(get_country_service)]
MarketServiceDep = Annotated[MarketService, Depends(get_market_service)]
ClientIP = Annotated[str | None, Depends(get_client_ip)]


async def _authenticate(
    credentials: Credentials, users: UserService, audience: Audience
) -> UserInDB:
    if credentials is None:
        raise AuthError("Missing bearer token")

    payload = decode_token(
        credentials.credentials, expected_audience=audience, expected_type=TokenType.ACCESS
    )
    user = await users.get_for_token(payload.sub, payload.epoch, audience)

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
