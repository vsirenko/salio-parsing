"""Admin user management: /api/admin/users

Mounted on the guarded admin router, so every route here already requires an admin token.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import UserServiceDep
from app.api.pagination import pagination_params
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination
from app.schemas.user import Role, UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["admin: users"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[UserRead], summary="List users")
async def list_users(
    users: UserServiceDep,
    pagination: PageParams,
    role: Annotated[Role | None, Query(description="Filter by role")] = None,
) -> Page[UserRead]:
    items, total = await users.list_users(pagination, role=role)
    return Page[UserRead].of([UserRead.model_validate(u) for u in items], total, pagination)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    responses={409: {"model": ErrorResponse, "description": "Email already taken"}},
)
async def create_user(payload: UserCreate, users: UserServiceDep) -> UserRead:
    user = await users.create_user(payload)
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    summary="Get a user by id",
    responses={404: {"model": ErrorResponse, "description": "User not found"}},
)
async def get_user(user_id: int, users: UserServiceDep) -> UserRead:
    user = await users.get_user(user_id)
    return UserRead.model_validate(user)
