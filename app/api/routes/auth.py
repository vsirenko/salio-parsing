"""Client-side authentication: /api/auth/*"""

from fastapi import APIRouter

from app.api.deps import ClientIP, CurrentClient, UserServiceDep
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.schemas.auth import (
    Audience,
    LoginRequest,
    PasswordChange,
    RefreshRequest,
    TokenPair,
    TokenType,
)
from app.schemas.common import ErrorResponse
from app.schemas.user import UserInDB, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

AUDIENCE = Audience.CLIENT


def _token_pair(user: UserInDB) -> TokenPair:
    """Mint a pair at the account's current epoch — the only epoch that is accepted."""
    return TokenPair(
        access_token=create_access_token(user.id, user.token_epoch, AUDIENCE),
        refresh_token=create_refresh_token(user.id, user.token_epoch, AUDIENCE),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in as a customer",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        429: {"model": ErrorResponse, "description": "Too many failed attempts"},
    },
)
async def login(payload: LoginRequest, users: UserServiceDep, ip: ClientIP) -> TokenPair:
    user = await users.authenticate(payload.email, payload.password, AUDIENCE, ip=ip)
    return _token_pair(user)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Exchange a refresh token for a new pair",
    responses={401: {"model": ErrorResponse, "description": "Invalid or expired token"}},
)
async def refresh(payload: RefreshRequest, users: UserServiceDep) -> TokenPair:
    claims = decode_token(
        payload.refresh_token, expected_audience=AUDIENCE, expected_type=TokenType.REFRESH
    )
    # Same check the access path runs: a signature that still verifies is not a reason
    # to hand a disabled or signed-out account a fresh pair.
    user = await users.get_for_token(claims.sub, claims.epoch, AUDIENCE)
    return _token_pair(user)


@router.post(
    "/password",
    response_model=TokenPair,
    summary="Change your password",
    responses={422: {"model": ErrorResponse, "description": "Current password is wrong"}},
)
async def change_password(
    payload: PasswordChange, current_user: CurrentClient, users: UserServiceDep
) -> TokenPair:
    """Ends every other session and hands this one a fresh pair.

    The pair is returned rather than a 204 so the caller who just changed their own
    password is not signed out by their own request.
    """
    user = await users.change_password(
        current_user.id, payload.current_password, payload.new_password
    )
    return _token_pair(user)


@router.get("/me", response_model=UserRead, summary="Current customer")
async def me(current_user: CurrentClient) -> UserRead:
    return UserRead.model_validate(current_user)
