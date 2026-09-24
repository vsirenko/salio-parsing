"""The catalogue behind the admin panel.

    /api/admin/products    the families a human searches for
    /api/admin/variants    the things that are bought

Write endpoints exist because the matcher does not yet, and nothing else can create a row.
Once it does, most of this becomes read and correct rather than create.

There is no delete and no merge. A merge has to move offers and price history with it, and
neither exists; building the operation before there is anything to move would be guessing
at its hardest part.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CatalogServiceDep
from app.api.pagination import pagination_params
from app.features.catalog.schemas import (
    PRODUCT_SORT,
    VARIANT_SORT,
    IdentifierCreate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    VariantAttributeRead,
    VariantAttributeSet,
    VariantCreate,
    VariantGtinRead,
    VariantMpnRead,
    VariantRead,
    VariantUpdate,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

products_router = APIRouter(prefix="/products", tags=["admin: catalogue"])
variants_router = APIRouter(prefix="/variants", tags=["admin: catalogue"])

PageParams = Annotated[Pagination, Depends(pagination_params())]
VariantPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=VARIANT_SORT, default_sort="id"))
]
ProductPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=PRODUCT_SORT, default_sort="id"))
]


# --- products ---


@products_router.get("", response_model=Page[ProductRead], summary="List products")
async def list_products(
    service: CatalogServiceDep,
    pagination: ProductPageParams,
    brand_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    category_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    is_visible: Annotated[bool | None, Query()] = None,
    created_from: Annotated[datetime | None, Query(description="Inclusive")] = None,
    created_to: Annotated[datetime | None, Query(description="Exclusive")] = None,
    search: Annotated[
        str | None,
        Query(
            max_length=200,
            description=(
                "Title, model or slug contains; an id (up to 7 digits); a barcode (8 to 14"
                " digits, any padding); an entry's part number"
            ),
        ),
    ] = None,
) -> Page[ProductRead]:
    items, total = await service.list_products(
        pagination,
        brand_ids=brand_id,
        category_ids=category_id,
        is_visible=is_visible,
        created_from=created_from,
        created_to=created_to,
        search=search,
    )
    return Page[ProductRead].of(items, total, pagination)


@products_router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product",
    responses={404: {"model": ErrorResponse, "description": "Brand or category not found"}},
)
async def create_product(payload: ProductCreate, service: CatalogServiceDep) -> ProductRead:
    """A family, not a thing that is bought: no price and no barcode. Its title and slug
    are generated from the brand and the model."""
    return await service.create_product(payload)


@products_router.get(
    "/{product_id}",
    response_model=ProductRead,
    summary="Get a product",
    responses={404: {"model": ErrorResponse, "description": "Product not found"}},
)
async def get_product(product_id: int, service: CatalogServiceDep) -> ProductRead:
    return await service.get_product(product_id)


@products_router.patch(
    "/{product_id}",
    response_model=ProductRead,
    summary="Update a product",
    responses={404: {"model": ErrorResponse, "description": "Product or category not found"}},
)
async def update_product(
    product_id: int, payload: ProductUpdate, service: CatalogServiceDep
) -> ProductRead:
    """`title` and `slug` are not editable — both are derived. A generated title is
    corrected through `title_override`, which survives the next regeneration."""
    return await service.update_product(product_id, payload)


# --- variants ---


@variants_router.get("", response_model=Page[VariantRead], summary="List variants")
async def list_variants(
    service: CatalogServiceDep,
    pagination: VariantPageParams,
    product_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    category_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    brand_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    identified: Annotated[
        bool | None, Query(description="Whether an identity key could be computed")
    ] = None,
    is_visible: Annotated[bool | None, Query()] = None,
    search: Annotated[
        str | None,
        Query(
            max_length=200,
            description=(
                "Title, model or slug contains; an id (up to 7 digits); a barcode (8 to 14"
                " digits, any padding); a part number"
            ),
        ),
    ] = None,
) -> Page[VariantRead]:
    items, total = await service.list_variants(
        pagination,
        product_ids=product_id,
        category_ids=category_id,
        brand_ids=brand_id,
        identified=identified,
        is_visible=is_visible,
        search=search,
    )
    return Page[VariantRead].of(items, total, pagination)


@variants_router.post(
    "",
    response_model=VariantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a variant",
    responses={
        404: {"model": ErrorResponse, "description": "Brand, category or product not found"},
        422: {"model": ErrorResponse, "description": "unit_count disagrees with kind"},
    },
)
async def create_variant(payload: VariantCreate, service: CatalogServiceDep) -> VariantRead:
    """`product_id` may be left out: a variant that matched nothing does not belong to a
    family yet, and inventing one from a single data point would be a guess."""
    return await service.create_variant(payload)


@variants_router.get(
    "/{variant_id}",
    response_model=VariantRead,
    summary="Get a variant",
    responses={404: {"model": ErrorResponse, "description": "Variant not found"}},
)
async def get_variant(variant_id: int, service: CatalogServiceDep) -> VariantRead:
    return await service.get_variant(variant_id)


@variants_router.patch(
    "/{variant_id}",
    response_model=VariantRead,
    summary="Update a variant",
    responses={404: {"model": ErrorResponse, "description": "Variant or reference not found"}},
)
async def update_variant(
    variant_id: int, payload: VariantUpdate, service: CatalogServiceDep
) -> VariantRead:
    """Anything the title or the identity key is built from regenerates both."""
    return await service.update_variant(variant_id, payload)


@variants_router.get(
    "/{variant_id}/attributes",
    response_model=list[VariantAttributeRead],
    summary="What is known about a variant",
)
async def list_variant_attributes(
    variant_id: int, service: CatalogServiceDep
) -> list[VariantAttributeRead]:
    return await service.list_variant_attributes(variant_id)


@variants_router.put(
    "/{variant_id}/attributes",
    response_model=VariantAttributeRead,
    summary="Set one attribute of a variant",
    responses={
        404: {"model": ErrorResponse, "description": "Variant or attribute not found"},
        422: {"model": ErrorResponse, "description": "Value does not match the type"},
    },
)
async def set_variant_attribute(
    variant_id: int, payload: VariantAttributeSet, service: CatalogServiceDep
) -> VariantAttributeRead:
    """Setting an identity-bearing attribute recomputes the identity key — which appears
    the moment the last missing axis is filled in, and disappears again if one is cleared."""
    return await service.set_variant_attribute(variant_id, payload)


@variants_router.delete(
    "/{variant_id}/attributes/{attribute_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear one attribute of a variant",
    responses={404: {"model": ErrorResponse, "description": "Not set on this variant"}},
)
async def clear_variant_attribute(
    variant_id: int, attribute_id: int, service: CatalogServiceDep
) -> Response:
    await service.clear_variant_attribute(variant_id, attribute_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@variants_router.get(
    "/{variant_id}/gtins", response_model=list[VariantGtinRead], summary="Barcodes"
)
async def list_gtins(variant_id: int, service: CatalogServiceDep) -> list[VariantGtinRead]:
    return await service.list_gtins(variant_id)


@variants_router.post(
    "/{variant_id}/gtins",
    response_model=VariantGtinRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a barcode",
    responses={409: {"model": ErrorResponse, "description": "Already here, or not a barcode"}},
)
async def add_gtin(
    variant_id: int, payload: IdentifierCreate, service: CatalogServiceDep
) -> VariantGtinRead:
    """Plural on purpose: regional packaging and a change of supplier both give one variant
    another barcode."""
    return await service.add_gtin(variant_id, payload)


@variants_router.get(
    "/{variant_id}/mpns", response_model=list[VariantMpnRead], summary="Part numbers"
)
async def list_mpns(variant_id: int, service: CatalogServiceDep) -> list[VariantMpnRead]:
    return await service.list_mpns(variant_id)


@variants_router.post(
    "/{variant_id}/mpns",
    response_model=VariantMpnRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a part number",
    responses={409: {"model": ErrorResponse, "description": "Already on this variant"}},
)
async def add_mpn(
    variant_id: int, payload: IdentifierCreate, service: CatalogServiceDep
) -> VariantMpnRead:
    """Stored beside the brand, because two makers reuse the same part number freely."""
    return await service.add_mpn(variant_id, payload)
