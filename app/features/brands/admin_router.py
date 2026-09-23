"""Brands behind the admin panel: /api/admin/brands

No delete: a brand variants already point at cannot go, and one nothing points at costs
nothing to keep. A wrong alias is removable; a wrong brand is merged, which is catalogue
work and does not exist yet.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import BrandServiceDep
from app.api.pagination import pagination_params
from app.features.brands.schemas import (
    BrandAliasCreate,
    BrandAliasRead,
    BrandCreate,
    BrandMatch,
    BrandRead,
    BrandUpdate,
    ModelAliasCreate,
    ModelAliasRead,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/brands", tags=["admin: brands"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[BrandRead], summary="List brands")
async def list_brands(
    service: BrandServiceDep,
    pagination: PageParams,
    search: Annotated[str | None, Query(max_length=200, description="Name contains")] = None,
) -> Page[BrandRead]:
    items, total = await service.list_brands(pagination, search=search)
    return Page[BrandRead].of(items, total, pagination)


@router.get(
    "/resolve",
    response_model=list[BrandMatch],
    summary="What a string resolves to",
)
async def resolve(
    service: BrandServiceDep,
    q: Annotated[str, Query(min_length=1, max_length=200, description="As a source wrote it")],
    titles_only: Annotated[
        bool, Query(description="Drop line aliases, which a title must not be read for")
    ] = False,
) -> list[BrandMatch]:
    """What the matcher will call, exposed so it can be tried by hand.

    One result is a deterministic signal, two are evidence the category has to settle, and
    none means the string belongs in the candidate queue.
    """
    return await service.resolve(q, titles_only=titles_only)


@router.post(
    "",
    response_model=BrandRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a brand",
    responses={409: {"model": ErrorResponse, "description": "Slug already taken"}},
)
async def create_brand(payload: BrandCreate, service: BrandServiceDep) -> BrandRead:
    """The name is not unique on purpose: Delta is taps and machine tools, two companies
    sharing a string. The slug separates them."""
    return await service.create_brand(payload)


@router.get(
    "/{brand_id}",
    response_model=BrandRead,
    summary="Get a brand",
    responses={404: {"model": ErrorResponse, "description": "Brand not found"}},
)
async def get_brand(brand_id: int, service: BrandServiceDep) -> BrandRead:
    return await service.get_brand(brand_id)


@router.patch(
    "/{brand_id}",
    response_model=BrandRead,
    summary="Update a brand",
    responses={
        404: {"model": ErrorResponse, "description": "Brand not found"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def update_brand(brand_id: int, payload: BrandUpdate, service: BrandServiceDep) -> BrandRead:
    return await service.update_brand(brand_id, payload)


@router.get(
    "/{brand_id}/aliases",
    response_model=list[BrandAliasRead],
    summary="List a brand's aliases",
)
async def list_aliases(brand_id: int, service: BrandServiceDep) -> list[BrandAliasRead]:
    return await service.list_aliases(brand_id)


@router.post(
    "/{brand_id}/aliases",
    response_model=BrandAliasRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an alias",
    responses={409: {"model": ErrorResponse, "description": "Already an alias here"}},
)
async def add_alias(
    brand_id: int, payload: BrandAliasCreate, service: BrandServiceDep
) -> BrandAliasRead:
    """`kind` says where the alias may be read from, not how sure we are. `spelling` is
    safe anywhere; `line` — iPhone, Galaxy — only in a feed's brand field."""
    return await service.add_alias(brand_id, payload)


@router.delete(
    "/{brand_id}/aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an alias",
    responses={404: {"model": ErrorResponse, "description": "Not an alias of this brand"}},
)
async def remove_alias(brand_id: int, alias_id: int, service: BrandServiceDep) -> Response:
    await service.remove_alias(brand_id, alias_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{brand_id}/models",
    response_model=list[ModelAliasRead],
    summary="List a brand's model names",
)
async def list_models(
    brand_id: int,
    service: BrandServiceDep,
    category_id: Annotated[int | None, Query(description="One kind of product")] = None,
) -> list[ModelAliasRead]:
    """Every spelling of every model this maker is known to make, and the name the
    catalogue gives each, per category. The reader finds these whole in a title — only the
    listing's own category's — and a title holding none keeps what the shop's rule cut out."""
    return await service.list_models(brand_id, category_id=category_id)


@router.post(
    "/{brand_id}/models",
    response_model=ModelAliasRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a model name",
    responses={
        404: {"model": ErrorResponse, "description": "Brand or category not found"},
        409: {"model": ErrorResponse, "description": "Already names a model here"},
    },
)
async def add_model(
    brand_id: int, payload: ModelAliasCreate, service: BrandServiceDep
) -> ModelAliasRead:
    """`alias` is what a shop writes, `model` is what the catalogue calls it. Adding the
    canonical spelling as an alias of itself is the usual first row. Registry work moves
    no ruleset version, so it has to be followed by a reparse to reach stored readings."""
    return await service.add_model(brand_id, payload)


@router.delete(
    "/{brand_id}/models/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a model name",
    responses={404: {"model": ErrorResponse, "description": "Not a model name of this brand"}},
)
async def remove_model(brand_id: int, alias_id: int, service: BrandServiceDep) -> Response:
    await service.remove_model(brand_id, alias_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
