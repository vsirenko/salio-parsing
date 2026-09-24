"""Categories behind the admin panel: /api/admin/categories

No delete: a category products already hang from cannot be removed, and one nothing hangs
from costs nothing to leave. Retiring a branch is `is_visible`, which keeps collecting and
keeps the history rather than losing both.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CategoryServiceDep
from app.api.pagination import pagination_params
from app.features.categories.schemas import (
    CATEGORY_SORT,
    CategoryAliasCreate,
    CategoryAliasRead,
    CategoryCreate,
    CategoryNode,
    CategoryRead,
    CategoryRow,
    CategoryUpdate,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/categories", tags=["admin: categories"])

PageParams = Annotated[Pagination, Depends(pagination_params())]
CategoryPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=CATEGORY_SORT, default_sort="name"))
]


@router.get("", response_model=Page[CategoryRow], summary="List categories")
async def list_categories(
    service: CategoryServiceDep,
    pagination: CategoryPageParams,
    parent_id: Annotated[int | None, Query(description="Children of this category")] = None,
    roots_only: Annotated[bool, Query(description="Only categories with no parent")] = False,
    is_visible_effective: Annotated[
        bool | None, Query(description="Filter by visibility after the cascade")
    ] = None,
    search: Annotated[
        str | None, Query(max_length=200, description="Name, slug or a name a shop gives it")
    ] = None,
    ids: Annotated[list[int] | None, Query(description="Only these. Repeat for several")] = None,
) -> Page[CategoryRow]:
    items, total = await service.list_categories(
        pagination,
        parent_id=parent_id,
        roots_only=roots_only,
        is_visible_effective=is_visible_effective,
        search=search,
        ids=ids,
    )
    return Page[CategoryRow].of(items, total, pagination)


@router.get("/tree", response_model=list[CategoryNode], summary="The whole tree at once")
async def tree(service: CategoryServiceDep) -> list[CategoryNode]:
    """Every category, nested under its parent, each with its own counts and its branch's
    totals — for a tree page and for the category filter of the product and entry lists."""
    return await service.tree()


@router.post(
    "",
    response_model=CategoryRow,
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
    response_model=CategoryRow,
    summary="Get a category",
    responses={404: {"model": ErrorResponse, "description": "Category not found"}},
)
async def get_category(category_id: int, service: CategoryServiceDep) -> CategoryRead:
    return await service.get_category(category_id)


@router.patch(
    "/{category_id}",
    response_model=CategoryRow,
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


@router.get(
    "/{category_id}/aliases",
    response_model=list[CategoryAliasRead],
    summary="What shops call this category",
)
async def list_aliases(category_id: int, service: CategoryServiceDep) -> list[CategoryAliasRead]:
    return await service.list_aliases(category_id)


@router.post(
    "/{category_id}/aliases",
    response_model=CategoryAliasRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a name a shop gives this category",
    responses={
        404: {"model": ErrorResponse, "description": "Category not found"},
        409: {"model": ErrorResponse, "description": "Already a name for it"},
    },
)
async def add_alias(
    category_id: int, payload: CategoryAliasCreate, service: CategoryServiceDep
) -> CategoryAliasRead:
    """Two jobs at once: the word a shop puts at the front of a title, and the name it
    gives the section a listing came from."""
    return await service.add_alias(category_id, payload)


@router.delete(
    "/{category_id}/aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop reading a name as this category",
    responses={404: {"model": ErrorResponse, "description": "No such alias on this category"}},
)
async def remove_alias(category_id: int, alias_id: int, service: CategoryServiceDep) -> Response:
    """The name stops being cut off the front of titles and stops naming the section a
    listing came from — on the next reading; what is stored is read again by a reparse."""
    await service.remove_alias(category_id, alias_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
