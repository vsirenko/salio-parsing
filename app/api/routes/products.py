from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import get_product_service
from app.api.pagination import pagination_params
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination
from app.schemas.product import ProductCreate, ProductRead
from app.services.products import ProductService

router = APIRouter(prefix="/products", tags=["products"])

ServiceDep = Annotated[ProductService, Depends(get_product_service)]
PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[ProductRead], summary="List products")
async def list_products(
    service: ServiceDep,
    pagination: PageParams,
    search: Annotated[
        str | None, Query(max_length=200, description="Case-insensitive name filter")
    ] = None,
    in_stock: Annotated[bool | None, Query(description="Filter by availability")] = None,
) -> Page[ProductRead]:
    items, total = await service.list_products(pagination, search=search, in_stock=in_stock)
    return Page[ProductRead].of(items, total, pagination)


@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
    responses={409: {"model": ErrorResponse, "description": "Product name already taken"}},
)
async def create_product(payload: ProductCreate, service: ServiceDep) -> ProductRead:
    return await service.create_product(payload)


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    summary="Get a product by id",
    responses={404: {"model": ErrorResponse, "description": "Product not found"}},
)
async def get_product(product_id: int, service: ServiceDep) -> ProductRead:
    return await service.get_product(product_id)
