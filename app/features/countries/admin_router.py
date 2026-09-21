"""Countries behind the admin panel: /api/admin/countries

The seed carries only the markets we serve. Others are added here as shops from them
appear, and the PATCH exists for the one field that genuinely moves — the VAT rate.

No delete: a country a shop already points at cannot be removed, and one nothing points
at costs nothing to leave.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CountryServiceDep
from app.api.pagination import pagination_params
from app.features.countries.schemas import CountryCreate, CountryRead, CountryUpdate
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/countries", tags=["admin: countries"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[CountryRead], summary="List countries")
async def list_countries(
    service: CountryServiceDep,
    pagination: PageParams,
    is_eu: Annotated[bool | None, Query(description="Filter by EU membership")] = None,
) -> Page[CountryRead]:
    items, total = await service.list_countries(pagination, is_eu=is_eu)
    return Page[CountryRead].of(items, total, pagination)


@router.post(
    "",
    response_model=CountryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a country",
    responses={
        409: {"model": ErrorResponse, "description": "Country already exists"},
        422: {"model": ErrorResponse, "description": "Unknown currency"},
    },
)
async def create_country(payload: CountryCreate, service: CountryServiceDep) -> CountryRead:
    return await service.create_country(payload)


@router.get(
    "/{code}",
    response_model=CountryRead,
    summary="Get a country by ISO code",
    responses={404: {"model": ErrorResponse, "description": "Country not found"}},
)
async def get_country(code: str, service: CountryServiceDep) -> CountryRead:
    return await service.get_country(code)


@router.patch(
    "/{code}",
    response_model=CountryRead,
    summary="Update a country",
    responses={
        404: {"model": ErrorResponse, "description": "Country not found"},
        422: {"model": ErrorResponse, "description": "Unknown currency"},
    },
)
async def update_country(
    code: str, payload: CountryUpdate, service: CountryServiceDep
) -> CountryRead:
    """Mainly the VAT rate, which changes and is not ours to guess.

    Nothing is computed from the rate — prices are stored as the buyer sees them — so it
    only explains why two prices differ. Sending null puts it back to unknown, which is
    how a wrong rate is withdrawn rather than replaced by another guess.
    """
    return await service.update_country(code, payload)
