"""Markets behind the admin panel: /api/admin/markets

Opening a market is a process, not a release: it is created here, the parsers are wired
to it, categories are mapped, and only then is it enabled. Nothing is seeded — countries
and currencies are facts about the world, a market is a decision.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import MarketServiceDep
from app.api.pagination import pagination_params
from app.core.languages import LANGUAGES
from app.features.markets.schemas import LanguageRead, MarketCreate, MarketRead, MarketUpdate
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

router = APIRouter(prefix="/markets", tags=["admin: markets"])

PageParams = Annotated[Pagination, Depends(pagination_params())]


@router.get("", response_model=Page[MarketRead], summary="List markets")
async def list_markets(
    service: MarketServiceDep,
    pagination: PageParams,
    is_enabled: Annotated[bool | None, Query(description="Filter by whether it is shown")] = None,
) -> Page[MarketRead]:
    items, total = await service.list_markets(pagination, is_enabled=is_enabled)
    return Page[MarketRead].of(items, total, pagination)


@router.post(
    "",
    response_model=MarketRead,
    status_code=status.HTTP_201_CREATED,
    summary="Open a market",
    responses={
        409: {"model": ErrorResponse, "description": "Country already has a market, or slug taken"},
        422: {"model": ErrorResponse, "description": "Unknown country"},
    },
)
async def create_market(payload: MarketCreate, service: MarketServiceDep) -> MarketRead:
    """The country has to exist first — a market is a country we have decided to sell in,
    and `countries` is where the VAT rate and the currency come from."""
    return await service.create_market(payload)


@router.get(
    "/languages",
    response_model=list[LanguageRead],
    summary="The languages a market may be read in",
)
async def list_languages() -> list[LanguageRead]:
    """ISO 639-1, every code with its English name, in code order — what `languages`
    accepts. Declared before `/{code}` so the path is not read as a market."""
    return [LanguageRead(code=code, name=name) for code, name in LANGUAGES.items()]


@router.get(
    "/{code}",
    response_model=MarketRead,
    summary="Get a market by country code",
    responses={404: {"model": ErrorResponse, "description": "Market not found"}},
)
async def get_market(code: str, service: MarketServiceDep) -> MarketRead:
    return await service.get_market(code)


@router.patch(
    "/{code}",
    response_model=MarketRead,
    summary="Update a market",
    responses={
        404: {"model": ErrorResponse, "description": "Market not found"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def update_market(code: str, payload: MarketUpdate, service: MarketServiceDep) -> MarketRead:
    """Mostly `is_enabled`, which is what turns a prepared market into a visible one.

    Changing `slug` moves every URL of that storefront, not one page. There is no
    redirect table yet, so until there is, treat a live market's slug as fixed.
    """
    return await service.update_market(code, payload)
