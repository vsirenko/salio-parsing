"""Admin-side authentication: /api/admin/auth/*

Deliberately outside the guarded admin router — you cannot require an admin token
to obtain an admin token.
"""

from fastapi import APIRouter

from app.api.deps import CurrentAdmin, UserServiceDep
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.schemas.auth import Audience, LoginRequest, RefreshRequest, TokenPair, TokenType
from app.schemas.common import ErrorResponse
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["admin: auth"])

AUDIENCE = Audience.ADMIN


def _token_pair(user_id: int) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id, AUDIENCE),
        refresh_token=create_refresh_token(user_id, AUDIENCE),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in to the admin panel",
    responses={401: {"model": ErrorResponse, "description": "Invalid credentials"}},
)
async def login(payload: LoginRequest, users: UserServiceDep) -> TokenPair:
    user = await users.authenticate(payload.email, payload.password, AUDIENCE)
    return _token_pair(user.id)


@router.post("/refresh", response_model=TokenPair, summary="Refresh the admin session")
async def refresh(payload: RefreshRequest, users: UserServiceDep) -> TokenPair:
    claims = decode_token(
        payload.refresh_token, expected_audience=AUDIENCE, expected_type=TokenType.REFRESH
    )
    user = await users.get_user(claims.sub)
    return _token_pair(user.id)


@router.get("/me", response_model=UserRead, summary="Current admin")
async def me(current_user: CurrentAdmin) -> UserRead:
    return UserRead.model_validate(current_user, from_attributes=True)
