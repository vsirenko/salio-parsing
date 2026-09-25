"""Admin-side routes for this feature: /api/admin/users/* and /api/admin/auth/*

Both live here because they are the same entity seen from the admin panel — managing
accounts and holding a session on one. They are split across two routers by whether a
token is required, not by subject:

- `public_router` holds sign-in and refresh, which cannot require a token to obtain
  one, and is the only reason `admin_public_router` exists;
- `router` holds everything that does need one and rides the guarded admin router, so
  no route here guards itself by hand.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ClientIP, CurrentAdmin, UserServiceDep
from app.api.pagination import pagination_params
from app.core.config import settings
from app.core.security import (
    Audience,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.features.users.schemas import (
    LoginRequest,
    PasswordChange,
    PasswordReset,
    RefreshRequest,
    Role,
    TokenPair,
    UserCreate,
    UserInDB,
    UserRead,
    UserUpdate,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

# Three routers: one per prefix, split again by whether a token is required. Each
# declares its prefix and tag once, so a route below carries neither.
auth_public_router = APIRouter(prefix="/auth", tags=["admin: auth"])
auth_router = APIRouter(prefix="/auth", tags=["admin: auth"])
users_router = APIRouter(prefix="/users", tags=["admin: users"])

AUDIENCE = Audience.ADMIN

PageParams = Annotated[Pagination, Depends(pagination_params())]


def _token_pair(user: UserInDB) -> TokenPair:
    """Mint a pair at the account's current epoch — the only epoch that is accepted."""
    return TokenPair(
        access_token=create_access_token(user.id, user.token_epoch, AUDIENCE),
        refresh_token=create_refresh_token(user.id, user.token_epoch, AUDIENCE),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


# --- sessions: /api/admin/auth/* ---


@auth_public_router.post(
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


@auth_public_router.post(
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


@auth_router.post(
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


@auth_router.get("/me", response_model=UserRead, summary="Current admin")
async def me(current_user: CurrentAdmin) -> UserRead:
    return UserRead.model_validate(current_user)


# --- accounts: /api/admin/users/* ---


@users_router.get("", response_model=Page[UserRead], summary="List users")
async def list_users(
    users: UserServiceDep,
    pagination: PageParams,
    role: Annotated[Role | None, Query(description="Filter by role")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by whether it may sign in")] = None,
    search: Annotated[
        str | None, Query(max_length=200, description="Part of the email or the name")
    ] = None,
) -> Page[UserRead]:
    items, total = await users.list_users(pagination, role=role, is_active=is_active, search=search)
    return Page[UserRead].of([UserRead.model_validate(u) for u in items], total, pagination)


@users_router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    responses={409: {"model": ErrorResponse, "description": "Email already taken"}},
)
async def create_user(payload: UserCreate, users: UserServiceDep) -> UserRead:
    user = await users.create_user(payload)
    return UserRead.model_validate(user)


@users_router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user by id",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(user_id: int, users: UserServiceDep) -> UserRead:
    user = await users.get_user(user_id)
    return UserRead.model_validate(user)


@users_router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Update a user",
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "Would remove your own access"},
    },
)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    users: UserServiceDep,
    current_admin: CurrentAdmin,
) -> UserRead:
    """Edit name, role or active flag.

    Deactivation is how an account is retired: the audit trail points at the user row,
    so there is no delete here and deliberately no service method behind one.
    """
    user = await users.update_user(user_id, payload, actor_id=current_admin.id)
    return UserRead.model_validate(user)


@users_router.post(
    "/{user_id}/password",
    response_model=UserRead,
    summary="Set another user's password",
    responses={
        404: {"model": ErrorResponse, "description": "User not found"},
        409: {"model": ErrorResponse, "description": "Your own: use /auth/password"},
    },
)
async def reset_password(
    user_id: int,
    payload: PasswordReset,
    users: UserServiceDep,
    current_admin: CurrentAdmin,
) -> UserRead:
    """Every session the account has ends with it, refresh tokens included. The caller's own
    password is refused here (409 `own_password`): that one needs the current password."""
    user = await users.reset_password(user_id, payload.new_password, actor_id=current_admin.id)
    return UserRead.model_validate(user)
