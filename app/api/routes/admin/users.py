"""Admin user management: /api/admin/users

Mounted on the guarded admin router, so every route here already requires an admin token.
"""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import UserServiceDep
from app.schemas.common import ErrorResponse, Page
from app.schemas.user import Role, UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["admin: users"])


@router.get("", response_model=Page[UserRead], summary="List users")
async def list_users(
    users: UserServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    role: Annotated[Role | None, Query(description="Filter by role")] = None,
) -> Page[UserRead]:
    items, total = await users.list_users(limit=limit, offset=offset, role=role)
    return Page[UserRead](
        items=[UserRead.model_validate(u, from_attributes=True) for u in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    responses={409: {"model": ErrorResponse, "description": "Email already taken"}},
)
async def create_user(payload: UserCreate, users: UserServiceDep) -> UserRead:
    user = await users.create_user(payload)
    return UserRead.model_validate(user, from_attributes=True)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user by id",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(user_id: int, users: UserServiceDep) -> UserRead:
    user = await users.get_user(user_id)
    return UserRead.model_validate(user, from_attributes=True)
