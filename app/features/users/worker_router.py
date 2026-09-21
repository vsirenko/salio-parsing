"""Signing a collector in.

POST /api/worker/auth/login     credentials in, a worker token out
POST /api/worker/auth/refresh

Only these two. A worker has no password to change and no profile to read — it is an
account a machine holds, not a person's.
"""

from fastapi import APIRouter

from app.api.deps import ClientIP, UserServiceDep
from app.core.config import settings
from app.core.security import (
    Audience,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.features.users.schemas import LoginRequest, RefreshRequest, TokenPair, UserInDB
from app.schemas.common import ErrorResponse

auth_public_router = APIRouter(prefix="/auth", tags=["worker"])

AUDIENCE = Audience.WORKER


def _token_pair(user: UserInDB) -> TokenPair:
    """Mint a pair at the account's current epoch — the only epoch that is accepted."""
    return TokenPair(
        access_token=create_access_token(user.id, user.token_epoch, AUDIENCE),
        refresh_token=create_refresh_token(user.id, user.token_epoch, AUDIENCE),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@auth_public_router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign a collector in",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        429: {"model": ErrorResponse, "description": "Too many failed attempts"},
    },
)
async def login(payload: LoginRequest, users: UserServiceDep, ip: ClientIP) -> TokenPair:
    """Rate limited like any other sign-in: a machine account's password is still a
    password, and a machine that has lost its credentials retries harder than a person."""
    user = await users.authenticate(payload.email, payload.password, AUDIENCE, ip=ip)
    return _token_pair(user)


@auth_public_router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Refresh a collector session",
    responses={401: {"model": ErrorResponse, "description": "Invalid or expired token"}},
)
async def refresh(payload: RefreshRequest, users: UserServiceDep) -> TokenPair:
    claims = decode_token(
        payload.refresh_token, expected_audience=AUDIENCE, expected_type=TokenType.REFRESH
    )
    user = await users.get_for_token(claims.sub, claims.epoch, AUDIENCE)
    return _token_pair(user)
