"""Attributes behind the admin panel.

    /api/admin/attributes                      the canonical registry
    /api/admin/attributes/{id}/aliases         what the sources call it
    /api/admin/attributes/{id}/values          canonical values, enums only
    /api/admin/categories/{id}/attributes      what a category makes of them

The registry is global on purpose. Defining attributes inside each category would mean
repeating every alias and every value per category, would make a cross-category facet
impossible, and would stop the mapping queue from ever draining — opening the thirtieth
category would mean mapping `Krāsa` for the thirtieth time.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import AttributeServiceDep
from app.api.pagination import pagination_params
from app.features.attributes.schemas import (
    AliasCreate,
    AliasRead,
    AttributeCreate,
    AttributeRead,
    CategoryAttributeCreate,
    CategoryAttributeRead,
    CategoryAttributeUpdate,
    ValueAliasRead,
    ValueCreate,
    ValueRead,
    ValueType,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/attributes", tags=["admin: attributes"])
category_router = APIRouter(prefix="/categories", tags=["admin: attributes"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[AttributeRead], summary="List attributes")
async def list_attributes(
    service: AttributeServiceDep,
    pagination: PageParams,
    value_type: Annotated[ValueType | None, Query(description="Filter by type")] = None,
) -> Page[AttributeRead]:
    items, total = await service.list_attributes(pagination, value_type=value_type)
    return Page[AttributeRead].of(items, total, pagination)


@router.post(
    "",
    response_model=AttributeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an attribute",
    responses={409: {"model": ErrorResponse, "description": "Key already taken"}},
)
async def create_attribute(payload: AttributeCreate, service: AttributeServiceDep) -> AttributeRead:
    """An attribute is one attribute only if its values mean the same everywhere. Size 42
    in shoes and size 42 in clothing are different scales, so they are two."""
    return await service.create_attribute(payload)


@router.get(
    "/{attribute_id}",
    response_model=AttributeRead,
    summary="Get an attribute",
    responses={404: {"model": ErrorResponse, "description": "Attribute not found"}},
)
async def get_attribute(attribute_id: int, service: AttributeServiceDep) -> AttributeRead:
    return await service.get_attribute(attribute_id)


@router.get("/{attribute_id}/aliases", response_model=list[AliasRead], summary="List aliases")
async def list_aliases(attribute_id: int, service: AttributeServiceDep) -> list[AliasRead]:
    return await service.list_aliases(attribute_id)


@router.post(
    "/{attribute_id}/aliases",
    response_model=AliasRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an alias",
    responses={409: {"model": ErrorResponse, "description": "Already an alias here"}},
)
async def add_alias(
    attribute_id: int, payload: AliasCreate, service: AttributeServiceDep
) -> AliasRead:
    """Case and trailing punctuation are normalized away rather than stored, so `Krāsa`,
    `krāsa` and `Krāsa:` are one alias. A declension is not derivable and is a row of its
    own."""
    return await service.add_alias(attribute_id, payload)


@router.get("/{attribute_id}/values", response_model=list[ValueRead], summary="List values")
async def list_values(attribute_id: int, service: AttributeServiceDep) -> list[ValueRead]:
    return await service.list_values(attribute_id)


@router.post(
    "/{attribute_id}/values",
    response_model=ValueRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a canonical value",
    responses={
        409: {"model": ErrorResponse, "description": "Value already exists"},
        422: {"model": ErrorResponse, "description": "Not an enum attribute"},
    },
)
async def add_value(
    attribute_id: int, payload: ValueCreate, service: AttributeServiceDep
) -> ValueRead:
    """Only enums have these. A number is parsed out of its string and rounded to the
    attribute's scale, so it never needs a lookup table."""
    return await service.add_value(attribute_id, payload)


@router.post(
    "/values/{value_id}/aliases",
    response_model=ValueAliasRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a value alias",
    responses={409: {"model": ErrorResponse, "description": "Already resolves here"}},
)
async def add_value_alias(
    value_id: int, payload: AliasCreate, service: AttributeServiceDep
) -> ValueAliasRead:
    """`melns`, `juodas`, `must`, `чёрный` all resolve to one canonical value."""
    return await service.add_value_alias(value_id, payload)


# --- what a category makes of them ---


@router.get(
    "/by-category/{category_id}",
    response_model=list[CategoryAttributeRead],
    summary="Attributes of a category",
)
async def list_for_category(
    category_id: int, service: AttributeServiceDep
) -> list[CategoryAttributeRead]:
    return await service.list_for_category(category_id)


@category_router.post(
    "/{category_id}/attributes",
    response_model=CategoryAttributeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach an attribute to a category",
    responses={
        404: {"model": ErrorResponse, "description": "Category or attribute not found"},
        409: {"model": ErrorResponse, "description": "Already attached"},
        422: {"model": ErrorResponse, "description": "Free text cannot carry identity"},
    },
)
async def attach(
    category_id: int, payload: CategoryAttributeCreate, service: AttributeServiceDep
) -> CategoryAttributeRead:
    """`identity_bearing` lives here rather than on the attribute, because the answer
    differs by category: weight is an axis for food and a specification for a washing
    machine."""
    return await service.attach(category_id, payload)


@category_router.patch(
    "/{category_id}/attributes/{attribute_id}",
    response_model=CategoryAttributeRead,
    summary="Change what a category makes of an attribute",
    responses={
        404: {"model": ErrorResponse, "description": "Not attached"},
        422: {"model": ErrorResponse, "description": "Free text cannot carry identity"},
    },
)
async def update_link(
    category_id: int,
    attribute_id: int,
    payload: CategoryAttributeUpdate,
    service: AttributeServiceDep,
) -> CategoryAttributeRead:
    """Turning `identity_bearing` on or off invalidates every identity key in the
    category and requires re-matching it. That is an operation the size of a migration,
    not a checkbox."""
    return await service.update_link(category_id, attribute_id, payload)


@category_router.delete(
    "/{category_id}/attributes/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach an attribute from a category",
    responses={404: {"model": ErrorResponse, "description": "Not attached"}},
)
async def detach(category_id: int, attribute_id: int, service: AttributeServiceDep) -> Response:
    await service.detach(category_id, attribute_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
