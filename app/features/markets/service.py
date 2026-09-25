"""Markets: the storefronts we run."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Country,
    Market,
    Offer,
    OfferMatch,
    Product,
    Seller,
    ShopMarket,
    Variant,
)
from app.db.query import offer_is_listed, paginated_rows
from app.features.markets.schemas import MarketCreate, MarketRead, MarketUpdate
from app.schemas.pagination import Pagination


class MarketService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_markets(
        self, pagination: Pagination, *, is_enabled: bool | None = None
    ) -> tuple[list[MarketRead], int]:
        stmt = _market_rows()
        if is_enabled is not None:
            stmt = stmt.where(Market.is_enabled.is_(is_enabled))

        rows, total = await paginated_rows(self.session, stmt.order_by(Market.code), pagination)
        return [_market_read(row) for row in rows], total

    async def get_market(self, code: str) -> MarketRead:
        return await self._read(code.upper())

    async def create_market(self, payload: MarketCreate) -> MarketRead:
        # Checked here rather than left to the foreign key, so the caller is told which
        # country is missing instead of reading a constraint name. The model comes from
        # `app.db.models`, which every feature shares.
        if await self.session.get(Country, payload.code) is None:
            raise ValidationError(
                f"Unknown country '{payload.code}'. Add the country first.",
                code="unknown_country",
            )

        market = Market(**payload.model_dump())
        self.session.add(market)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            # Either the country already has a market or the slug is taken; both are
            # "this name is spoken for", and the caller can see which from the payload.
            raise ConflictError(
                f"A market for '{payload.code}' or the slug '{payload.slug}' already exists"
            ) from exc

        await self.session.refresh(market)
        audit.set_target("market", market.code)
        audit.record_changes(**payload.model_dump(mode="json"))
        return await self._read(market.code)

    async def update_market(self, code: str, payload: MarketUpdate) -> MarketRead:
        market = await self._row(code)

        # Named before anything can fail, so a refused edit is recorded against the
        # market it was aimed at rather than at nothing.
        audit.set_target("market", market.code)

        sent = payload.model_dump(exclude_unset=True, mode="json")
        if payload.name is not None:
            market.name = payload.name
        if payload.slug is not None:
            market.slug = payload.slug
        if payload.languages is not None:
            market.languages = payload.languages
        if payload.is_enabled is not None:
            market.is_enabled = payload.is_enabled

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        await self.session.refresh(market)
        audit.record_changes(**sent)
        return await self._read(market.code)

    async def _read(self, code: str) -> MarketRead:
        row = (await self.session.execute(_market_rows().where(Market.code == code))).first()
        if row is None:
            raise NotFoundError(f"Market '{code}' not found")
        return _market_read(row)

    async def _row(self, code: str) -> Market:
        market = await self.session.get(Market, code.upper())
        if market is None:
            raise NotFoundError(f"Market '{code}' not found")
        return market


def _market_rows() -> Any:
    """A market with what the list shows beside it, counted in place per row.

    The storefront's view, not the collector's: a listing counts where its shop is shown,
    because a shop attached and hidden sells nothing on that storefront yet.
    """
    shown = (
        select(ShopMarket.shop_id)
        .where(ShopMarket.market_code == Market.code, ShopMarket.is_enabled.is_(True))
        .correlate(Market)
    )
    on_sale = (
        select(func.count(Offer.id))
        .join(Seller, Seller.id == Offer.seller_id)
        .where(Offer.market_code == Market.code, Seller.shop_id.in_(shown), offer_is_listed())
    )
    families = (
        select(func.count(func.distinct(Variant.product_id)))
        .select_from(Offer)
        .join(Seller, Seller.id == Offer.seller_id)
        .join(OfferMatch, (OfferMatch.offer_id == Offer.id) & OfferMatch.superseded_at.is_(None))
        .join(Variant, Variant.id == OfferMatch.variant_id)
        .join(Product, Product.id == Variant.product_id)
        .where(
            Offer.market_code == Market.code,
            Seller.shop_id.in_(shown),
            Offer.condition == "new",
            Product.is_visible.is_(True),
            offer_is_listed(),
        )
    )
    attached = select(func.count()).where(ShopMarket.market_code == Market.code)
    return select(
        Market,
        attached.where(ShopMarket.is_enabled.is_(True)).scalar_subquery().label("shops_shown"),
        attached.scalar_subquery().label("shops_attached"),
        on_sale.scalar_subquery().label("offers_count"),
        families.scalar_subquery().label("products_count"),
    )


def _market_read(row: Any) -> MarketRead:
    market = row.Market
    return MarketRead(
        code=market.code,
        name=market.name,
        slug=market.slug,
        languages=list(market.languages),
        is_enabled=market.is_enabled,
        shops_shown=row.shops_shown or 0,
        shops_attached=row.shops_attached or 0,
        offers_count=row.offers_count or 0,
        products_count=row.products_count or 0,
    )
