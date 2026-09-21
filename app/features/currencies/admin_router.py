"""Currencies behind the admin panel: /api/admin/currencies

Read-only. The list is ISO 4217; a new one arrives with a migration, not a POST.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrencyServiceDep
from app.api.pagination import pagination_params
from app.features.currencies.schemas import CurrencyRead
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/currencies", tags=["admin: currencies"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[CurrencyRead], summary="List currencies")
async def list_currencies(
    service: CurrencyServiceDep, pagination: PageParams
) -> Page[CurrencyRead]:
    items, total = await service.list_currencies(pagination)
    return Page[CurrencyRead].of(items, total, pagination)
