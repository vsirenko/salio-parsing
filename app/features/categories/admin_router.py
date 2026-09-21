"""Categories behind the admin panel: /api/admin/categories

No delete: a category products already hang from cannot be removed, and one nothing hangs
from costs nothing to leave. Retiring a branch is `is_visible`, which keeps collecting and
keeps the history rather than losing both.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CategoryServiceDep
from app.api.pagination import pagination_params
from app.features.categories.schemas import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/categories", tags=["admin: categories"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[CategoryRead], summary="List categories")
async def list_categories(
    service: CategoryServiceDep,
    pagination: PageParams,
    parent_id: Annotated[int | None, Query(description="Children of this category")] = None,
    roots_only: Annotated[bool, Query(description="Only categories with no parent")] = False,
    is_visible_effective: Annotated[
        bool | None, Query(description="Filter by visibility after the cascade")
    ] = None,
) -> Page[CategoryRead]:
    items, total = await service.list_categories(
        pagination,
        parent_id=parent_id,
        roots_only=roots_only,
        is_visible_effective=is_visible_effective,
    )
    return Page[CategoryRead].of(items, total, pagination)


@router.post(
    "",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a category",
    responses={
        404: {"model": ErrorResponse, "description": "Parent not found"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def create_category(payload: CategoryCreate, service: CategoryServiceDep) -> CategoryRead:
    return await service.create_category(payload)


@router.get(
    "/{category_id}",
    response_model=CategoryRead,
    summary="Get a category",
    responses={404: {"model": ErrorResponse, "description": "Category not found"}},
)
async def get_category(category_id: int, service: CategoryServiceDep) -> CategoryRead:
    return await service.get_category(category_id)


@router.patch(
    "/{category_id}",
    response_model=CategoryRead,
    summary="Update a category",
    responses={
        404: {"model": ErrorResponse, "description": "Category or parent not found"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
        422: {"model": ErrorResponse, "description": "The move would close a loop"},
    },
)
async def update_category(
    category_id: int, payload: CategoryUpdate, service: CategoryServiceDep
) -> CategoryRead:
    """Hiding a category hides everything under it, and nothing is deleted or stops being
    collected. `is_visible_effective` is recomputed here rather than sent in."""
    return await service.update_category(category_id, payload)
