"""Admin-side authentication: /api/admin/auth/*

Two routers, mounted on the two admin routers:

- `public_router` holds sign-in and refresh, which cannot require a token to obtain
  one, and is the only reason `admin_public_router` exists;
- `router` holds everything that does need a token and rides the guarded admin router
  with everything else, so no route here guards itself by hand.
"""

from fastapi import APIRouter

from app.api.deps import ClientIP, CurrentAdmin, UserServiceDep
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

public_router = APIRouter(prefix="/auth", tags=["admin: auth"])
router = APIRouter(prefix="/auth", tags=["admin: auth"])

AUDIENCE = Audience.ADMIN


def _token_pair(user: UserInDB) -> TokenPair:
    """Mint a pair at the account's current epoch — the only epoch that is accepted."""
    return TokenPair(
        access_token=create_access_token(user.id, user.token_epoch, AUDIENCE),
        refresh_token=create_refresh_token(user.id, user.token_epoch, AUDIENCE),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@public_router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in to the admin panel",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        429: {"model": ErrorResponse, "description": "Too many failed attempts"},
    },
)
async def login(payload: LoginRequest, users: UserServiceDep, ip: ClientIP) -> TokenPair:
    user = await users.authenticate(payload.email, payload.password, AUDIENCE, ip=ip)
    return _token_pair(user)


@public_router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Refresh the admin session",
    responses={401: {"model": ErrorResponse, "description": "Invalid or expired token"}},
)
async def refresh(payload: RefreshRequest, users: UserServiceDep) -> TokenPair:
    claims = decode_token(
        payload.refresh_token, expected_audience=AUDIENCE, expected_type=TokenType.REFRESH
    )
    # Same check the access path runs: a signature that still verifies is not a reason
    # to hand a disabled, demoted or signed-out account a fresh pair.
    user = await users.get_for_token(claims.sub, claims.epoch, AUDIENCE)
    return _token_pair(user)


@router.post(
    "/password",
    response_model=TokenPair,
    summary="Change your password",
    responses={422: {"model": ErrorResponse, "description": "Current password is wrong"}},
)
async def change_password(
    payload: PasswordChange, current_user: CurrentAdmin, users: UserServiceDep
) -> TokenPair:
    """Ends every other session and hands this one a fresh pair.

    The pair is returned rather than a 204 so the admin who just changed their own
    password is not signed out by their own request.
    """
    user = await users.change_password(
        current_user.id, payload.current_password, payload.new_password
    )
    return _token_pair(user)


@router.get("/me", response_model=UserRead, summary="Current admin")
async def me(current_user: CurrentAdmin) -> UserRead:
    return UserRead.model_validate(current_user)
