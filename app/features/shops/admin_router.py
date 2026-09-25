"""Shops behind the admin panel.

    /api/admin/shop-groups              one retail brand across countries, optional
    /api/admin/shops                    who the buyer deals with
    /api/admin/shops/{id}/markets       where its offers are shown
    /api/admin/shops/{id}/sources       how we read it
    /api/admin/shops/{id}/sellers       who is actually selling inside it
    /api/admin/sources/{id}             one channel, its last run and next slot
    /api/admin/sellers/{id}             rename a seller

No delete on a shop: offers and price history will point at it, and the way to retire one
is to switch its markets off — which keeps the history instead of losing it.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import ShopServiceDep
from app.api.pagination import pagination_params
from app.features.shops.schemas import (
    SHOP_SORT,
    MarketState,
    SellerCreate,
    SellerRead,
    SellerUpdate,
    ShopCreate,
    ShopGroupCreate,
    ShopGroupRead,
    ShopGroupUpdate,
    ShopMarketRead,
    ShopMarketSet,
    ShopRead,
    ShopUpdate,
    SourceCreate,
    SourceRead,
    SourceUpdate,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

groups_router = APIRouter(prefix="/shop-groups", tags=["admin: shops"])
router = APIRouter(prefix="/shops", tags=["admin: shops"])
sources_router = APIRouter(prefix="/sources", tags=["admin: shops"])
sellers_router = APIRouter(prefix="/sellers", tags=["admin: shops"])

PageParams = Annotated[Pagination, Depends(pagination_params())]
ShopPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=SHOP_SORT, default_sort="name"))
]


@groups_router.get("", response_model=Page[ShopGroupRead], summary="List shop groups")
async def list_groups(service: ShopServiceDep, pagination: PageParams) -> Page[ShopGroupRead]:
    items, total = await service.list_groups(pagination)
    return Page[ShopGroupRead].of(items, total, pagination)


@groups_router.post(
    "",
    response_model=ShopGroupRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a shop group",
    responses={409: {"model": ErrorResponse, "description": "Slug already taken"}},
)
async def create_group(payload: ShopGroupCreate, service: ShopServiceDep) -> ShopGroupRead:
    """Optional. MediaMarkt DE and ES are separate shops with separate prices and VAT, but
    a buyer sees one logo."""
    return await service.create_group(payload)


@groups_router.get(
    "/{group_id}",
    response_model=ShopGroupRead,
    summary="Get a shop group",
    responses={404: {"model": ErrorResponse, "description": "Group not found"}},
)
async def get_group(group_id: int, service: ShopServiceDep) -> ShopGroupRead:
    return await service.get_group(group_id)


@groups_router.patch(
    "/{group_id}",
    response_model=ShopGroupRead,
    summary="Update a shop group",
    responses={
        404: {"model": ErrorResponse, "description": "Group not found"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def update_group(
    group_id: int, payload: ShopGroupUpdate, service: ShopServiceDep
) -> ShopGroupRead:
    return await service.update_group(group_id, payload)


# --- shops ---


@router.get("", response_model=Page[ShopRead], summary="List shops")
async def list_shops(
    service: ShopServiceDep,
    pagination: ShopPageParams,
    country_code: Annotated[
        str | None, Query(max_length=2, description="Where it is based")
    ] = None,
    market_code: Annotated[
        str | None, Query(max_length=2, description="Shown in this market")
    ] = None,
    market_state: Annotated[
        MarketState,
        Query(description="With `market_code`: shown there, attached and hidden, or either"),
    ] = MarketState.SHOWN,
    is_marketplace: Annotated[bool | None, Query()] = None,
    search: Annotated[
        str | None, Query(max_length=200, description="Name, slug or website contains")
    ] = None,
    ids: Annotated[
        list[int] | None,
        Query(
            description="Only these shops — the ones a filter in a URL names. Repeat for several."
        ),
    ] = None,
    health: Annotated[
        Literal["ok", "failing", "never"] | None,
        Query(
            description="`failing`: an enabled channel's newest full pass broke; `never`: no"
            " enabled channel has a sound full pass; `ok`: the rest"
        ),
    ] = None,
) -> Page[ShopRead]:
    """Each row counts what the shop holds — channels, sellers, listings on sale, the
    products they are placed on — and says how its collection is going."""
    items, total = await service.list_shops(
        pagination,
        country_code=country_code,
        market_code=market_code,
        market_state=market_state,
        is_marketplace=is_marketplace,
        search=search,
        ids=ids,
        health=health,
    )
    return Page[ShopRead].of(items, total, pagination)


@router.post(
    "",
    response_model=ShopRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a shop",
    responses={
        409: {"model": ErrorResponse, "description": "Slug already taken"},
        422: {"model": ErrorResponse, "description": "Unknown country"},
    },
)
async def create_shop(payload: ShopCreate, service: ShopServiceDep) -> ShopRead:
    """`country_code` is where the shop is based, not where it sells: a German shop
    delivering to Riga is describable even though we run no German storefront.

    An ordinary shop gets its single seller — itself — created with it.
    """
    return await service.create_shop(payload)


@router.get(
    "/{shop_id}",
    response_model=ShopRead,
    summary="Get a shop",
    responses={404: {"model": ErrorResponse, "description": "Shop not found"}},
)
async def get_shop(shop_id: int, service: ShopServiceDep) -> ShopRead:
    return await service.get_shop(shop_id)


@router.patch(
    "/{shop_id}",
    response_model=ShopRead,
    summary="Update a shop",
    responses={
        404: {"model": ErrorResponse, "description": "Shop or group not found"},
        409: {"model": ErrorResponse, "description": "Slug already taken"},
    },
)
async def update_shop(shop_id: int, payload: ShopUpdate, service: ShopServiceDep) -> ShopRead:
    """`is_marketplace` is not editable: flipping it would either strand the sellers a
    marketplace has or leave an ordinary shop without the one it needs."""
    return await service.update_shop(shop_id, payload)


# --- where its offers are shown ---


@router.get("/{shop_id}/markets", response_model=list[ShopMarketRead], summary="Markets of a shop")
async def list_shop_markets(shop_id: int, service: ShopServiceDep) -> list[ShopMarketRead]:
    return await service.list_shop_markets(shop_id)


@router.put(
    "/{shop_id}/markets/{market_code}",
    response_model=ShopMarketRead,
    summary="Show a shop in a market",
    responses={
        404: {"model": ErrorResponse, "description": "Shop not found"},
        422: {"model": ErrorResponse, "description": "Unknown market"},
    },
)
async def set_shop_market(
    shop_id: int, market_code: str, payload: ShopMarketSet, service: ShopServiceDep
) -> ShopMarketRead:
    """Delivery is the reason, the decision is ours: a shop may ship to Lithuania while we
    choose not to show it there yet. Attached disabled by default."""
    return await service.set_shop_market(shop_id, market_code, payload)


@router.delete(
    "/{shop_id}/markets/{market_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a shop from a market",
    responses={404: {"model": ErrorResponse, "description": "Not attached"}},
)
async def remove_shop_market(shop_id: int, market_code: str, service: ShopServiceDep) -> Response:
    await service.remove_shop_market(shop_id, market_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- how we read it ---


@router.get("/{shop_id}/sources", response_model=list[SourceRead], summary="Sources of a shop")
async def list_sources(shop_id: int, service: ShopServiceDep) -> list[SourceRead]:
    return await service.list_sources(shop_id)


@router.post(
    "/{shop_id}/sources",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a source",
    responses={409: {"model": ErrorResponse, "description": "Slug already taken"}},
)
async def add_source(shop_id: int, payload: SourceCreate, service: ShopServiceDep) -> SourceRead:
    """A shop may have several. A feed and a scraper of the same shop converge on one
    offer, each leaving its own observation — which is how a barcode from the feed and a
    description from the page end up on the same row."""
    return await service.add_source(shop_id, payload)


@sources_router.get(
    "/{source_id}",
    response_model=SourceRead,
    summary="Get a source",
    responses={404: {"model": ErrorResponse, "description": "Source not found"}},
)
async def get_source(source_id: int, service: ShopServiceDep) -> SourceRead:
    return await service.get_source(source_id)


@sources_router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a source that has collected nothing",
    responses={
        404: {"model": ErrorResponse, "description": "Source not found"},
        409: {"model": ErrorResponse, "description": "It has history; disable it instead"},
    },
)
async def remove_source(source_id: int, service: ShopServiceDep) -> Response:
    """For one added by mistake. A channel that has run is retired with `is_enabled=false`:
    its observations and runs are the listings' history, and a delete would take them."""
    await service.remove_source(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sources_router.patch(
    "/{source_id}",
    response_model=SourceRead,
    summary="Update a source",
    responses={404: {"model": ErrorResponse, "description": "Source not found"}},
)
async def update_source(
    source_id: int, payload: SourceUpdate, service: ShopServiceDep
) -> SourceRead:
    """`trust` is the channel's, not the shop's: a feed carrying barcodes is worth more
    than a title scraped out of markup, whatever buyers think of the shop."""
    return await service.update_source(source_id, payload)


# --- who is selling ---


@router.get("/{shop_id}/sellers", response_model=list[SellerRead], summary="Sellers of a shop")
async def list_sellers(shop_id: int, service: ShopServiceDep) -> list[SellerRead]:
    return await service.list_sellers(shop_id)


@router.post(
    "/{shop_id}/sellers",
    response_model=SellerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a seller",
    responses={
        409: {"model": ErrorResponse, "description": "Already a seller here"},
        422: {"model": ErrorResponse, "description": "Not a marketplace"},
    },
)
async def add_seller(shop_id: int, payload: SellerCreate, service: ShopServiceDep) -> SellerRead:
    """Only a marketplace has more than one. Price history is keyed by seller, so treating
    a marketplace itself as the seller would draw one price line through forty independent
    traders."""
    return await service.add_seller(shop_id, payload)


@sellers_router.patch(
    "/{seller_id}",
    response_model=SellerRead,
    summary="Rename a seller",
    responses={404: {"model": ErrorResponse, "description": "Seller not found"}},
)
async def update_seller(
    seller_id: int, payload: SellerUpdate, service: ShopServiceDep
) -> SellerRead:
    """The name only. `external_id` is how the marketplace names the trader in its feed,
    and changing it would detach every listing already filed under them."""
    return await service.update_seller(seller_id, payload)
