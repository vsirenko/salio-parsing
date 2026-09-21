"""Shops, the channels we read them through, and the sellers behind them."""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import Country, Market, Seller, Shop, ShopGroup, ShopMarket, Source
from app.db.query import paginated
from app.features.shops.schemas import (
    Access,
    Fact,
    SellerCreate,
    SellerRead,
    ShopCreate,
    ShopGroupCreate,
    ShopGroupRead,
    ShopMarketRead,
    ShopMarketSet,
    ShopRead,
    ShopUpdate,
    SourceCreate,
    SourceRead,
    SourceUpdate,
)
from app.schemas.pagination import Pagination


class ShopService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- groups ---

    async def list_groups(self, pagination: Pagination) -> tuple[list[ShopGroupRead], int]:
        stmt = select(ShopGroup).order_by(ShopGroup.slug)
        rows, total = await paginated(self.session, stmt, pagination)
        return [ShopGroupRead.model_validate(row) for row in rows], total

    async def create_group(self, payload: ShopGroupCreate) -> ShopGroupRead:
        group = ShopGroup(**payload.model_dump())
        self.session.add(group)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        await self.session.refresh(group)
        audit.set_target("shop_group", group.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return ShopGroupRead.model_validate(group)

    # --- shops ---

    async def list_shops(
        self,
        pagination: Pagination,
        *,
        country_code: str | None = None,
        market_code: str | None = None,
        is_marketplace: bool | None = None,
    ) -> tuple[list[ShopRead], int]:
        stmt = select(Shop)
        if country_code is not None:
            stmt = stmt.where(Shop.country_code == country_code.upper())
        if is_marketplace is not None:
            stmt = stmt.where(Shop.is_marketplace.is_(is_marketplace))
        if market_code is not None:
            stmt = stmt.join(ShopMarket, ShopMarket.shop_id == Shop.id).where(
                ShopMarket.market_code == market_code.upper(),
                ShopMarket.is_enabled.is_(True),
            )

        rows, total = await paginated(self.session, stmt.order_by(Shop.id), pagination)
        return [ShopRead.model_validate(row) for row in rows], total

    async def get_shop(self, shop_id: int) -> ShopRead:
        return ShopRead.model_validate(await self._shop(shop_id))

    async def create_shop(self, payload: ShopCreate) -> ShopRead:
        await self._country(payload.country_code)
        if payload.shop_group_id is not None:
            await self._group(payload.shop_group_id)

        shop = Shop(**payload.model_dump())
        self.session.add(shop)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        if not shop.is_marketplace:
            # An ordinary shop has exactly one seller, which is the shop. Created here
            # rather than left to a second call, because an offer cannot attach to
            # anything without it and somebody would forget.
            self.session.add(Seller(shop_id=shop.id, external_id=shop.slug, name=shop.name))
            await self.session.flush()

        await self.session.refresh(shop)
        audit.set_target("shop", shop.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return ShopRead.model_validate(shop)

    async def update_shop(self, shop_id: int, payload: ShopUpdate) -> ShopRead:
        shop = await self._shop(shop_id)
        audit.set_target("shop", shop.id)
        sent = payload.model_dump(exclude_unset=True, mode="json")

        if payload.country_code is not None:
            await self._country(payload.country_code)
            shop.country_code = payload.country_code
        if "shop_group_id" in sent:
            if payload.shop_group_id is not None:
                await self._group(payload.shop_group_id)
            shop.shop_group_id = payload.shop_group_id
        if payload.name is not None:
            shop.name = payload.name
        if payload.slug is not None:
            shop.slug = payload.slug
        if "website" in sent:
            shop.website = payload.website
        if "rating" in sent:
            shop.rating = payload.rating

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        await self.session.refresh(shop)
        audit.record_changes(**sent)
        return ShopRead.model_validate(shop)

    # --- where its offers are shown ---

    async def list_shop_markets(self, shop_id: int) -> list[ShopMarketRead]:
        await self._shop(shop_id)
        rows = await self.session.scalars(
            select(ShopMarket).where(ShopMarket.shop_id == shop_id).order_by(ShopMarket.market_code)
        )
        return [ShopMarketRead.model_validate(row) for row in rows]

    async def set_shop_market(
        self, shop_id: int, market_code: str, payload: ShopMarketSet
    ) -> ShopMarketRead:
        await self._shop(shop_id)
        code = market_code.upper()
        await self._market(code)
        audit.set_target("shop", shop_id)

        row = await self.session.get(ShopMarket, (shop_id, code))
        if row is None:
            row = ShopMarket(shop_id=shop_id, market_code=code, is_enabled=payload.is_enabled)
            self.session.add(row)
        else:
            row.is_enabled = payload.is_enabled

        await self.session.flush()
        await self.session.refresh(row)
        audit.record_changes(market_code=code, is_enabled=payload.is_enabled)
        return ShopMarketRead.model_validate(row)

    async def remove_shop_market(self, shop_id: int, market_code: str) -> None:
        await self._shop(shop_id)
        code = market_code.upper()
        if await self.session.get(ShopMarket, (shop_id, code)) is None:
            raise NotFoundError(f"Shop {shop_id} is not attached to market '{code}'")

        audit.set_target("shop", shop_id)
        audit.record_changes(detached_market=code)
        await self.session.execute(
            delete(ShopMarket).where(ShopMarket.shop_id == shop_id, ShopMarket.market_code == code)
        )

    # --- how we read it ---

    async def list_sources(self, shop_id: int) -> list[SourceRead]:
        await self._shop(shop_id)
        rows = await self.session.scalars(
            select(Source).where(Source.shop_id == shop_id).order_by(Source.id)
        )
        return [SourceRead.model_validate(row) for row in rows]

    async def add_source(self, shop_id: int, payload: SourceCreate) -> SourceRead:
        await self._shop(shop_id)
        audit.set_target("shop", shop_id)

        self._check_delivers(payload.access, payload.delivers_full, payload.delivers_quick)
        if payload.cron_quick and not payload.delivers_quick:
            raise ValidationError(
                "A quick cron on a channel with no quick pass would schedule a run that"
                " brings nothing back.",
                code="quick_cron_needs_a_quick_pass",
            )
        source = Source(shop_id=shop_id, **payload.model_dump(mode="json"))
        self.session.add(source)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        await self.session.refresh(source)
        audit.record_changes(added_source=payload.slug, **payload.model_dump(mode="json"))
        return SourceRead.model_validate(source)

    async def update_source(self, source_id: int, payload: SourceUpdate) -> SourceRead:
        source = await self._source(source_id)
        audit.set_target("shop", source.shop_id)
        sent = payload.model_dump(exclude_unset=True, mode="json")

        if payload.access is not None:
            source.access = payload.access.value
        if payload.decode is not None:
            source.decode = payload.decode.value
        if payload.delivers_full is not None:
            source.delivers_full = [fact.value for fact in payload.delivers_full]
        if payload.delivers_quick is not None:
            source.delivers_quick = [fact.value for fact in payload.delivers_quick]
        # Checked against what the row will hold, not against what was sent: a partial
        # update that only narrows the full pass can still leave the quick one reaching
        # past it.
        self._check_delivers(
            Access(source.access),
            [Fact(f) for f in source.delivers_full],
            [Fact(f) for f in source.delivers_quick],
        )
        if payload.trust is not None:
            source.trust = payload.trust.value
        if "base_url" in sent:
            source.base_url = payload.base_url
        if payload.is_enabled is not None:
            source.is_enabled = payload.is_enabled
        if "category_id" in sent:
            source.category_id = payload.category_id
        if "cron_full" in sent:
            source.cron_full = payload.cron_full
        if "cron_quick" in sent:
            source.cron_quick = payload.cron_quick
        if "min_items" in sent:
            source.min_items = payload.min_items
        if payload.max_drop_pct is not None:
            source.max_drop_pct = payload.max_drop_pct
        if payload.min_price_coverage is not None:
            source.min_price_coverage = payload.min_price_coverage
        self._check_schedule(source)

        await self.session.flush()
        await self.session.refresh(source)
        audit.record_changes(source_id=source_id, **sent)
        return SourceRead.model_validate(source)

    @staticmethod
    def _check_schedule(source: Source) -> None:
        """Checked against the row, because narrowing either side breaks the pairing."""
        if source.cron_quick and not source.delivers_quick:
            raise ValidationError(
                "A quick cron on a channel with no quick pass would schedule a run that"
                " brings nothing back.",
                code="quick_cron_needs_a_quick_pass",
            )

    @staticmethod
    def _check_delivers(access: Access, full: list[Fact], quick: list[Fact]) -> None:
        """The two rules the caller gets wrong, named rather than left to a constraint.

        The database holds both as well, but a check-constraint violation arrives as one
        undifferentiated IntegrityError and would have to be guessed at.
        """
        beyond = sorted({fact.value for fact in quick} - {fact.value for fact in full})
        if beyond:
            raise ValidationError(
                f"The quick pass cannot deliver what the full one does not: {', '.join(beyond)}",
                code="quick_exceeds_full",
            )
        if access is Access.WHOLESALE and quick:
            raise ValidationError(
                "A wholesale channel has no quick pass — one request already returns"
                " everything, so there is nothing cheaper to run.",
                code="wholesale_has_no_quick_pass",
            )

    # --- who is selling ---

    async def list_sellers(self, shop_id: int) -> list[SellerRead]:
        await self._shop(shop_id)
        rows = await self.session.scalars(
            select(Seller).where(Seller.shop_id == shop_id).order_by(Seller.id)
        )
        return [SellerRead.model_validate(row) for row in rows]

    async def add_seller(self, shop_id: int, payload: SellerCreate) -> SellerRead:
        shop = await self._shop(shop_id)
        if not shop.is_marketplace:
            raise ValidationError(
                f"'{shop.slug}' is not a marketplace: it has exactly one seller, itself."
                " Adding traders to it would put several price lines where there is one.",
                code="not_a_marketplace",
            )

        audit.set_target("shop", shop_id)
        seller = Seller(shop_id=shop_id, **payload.model_dump())
        self.session.add(seller)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                f"'{payload.external_id}' is already a seller of this shop"
            ) from exc

        await self.session.refresh(seller)
        audit.record_changes(added_seller=payload.external_id)
        return SellerRead.model_validate(seller)

    # --- lookups ---

    async def _shop(self, shop_id: int) -> Shop:
        shop = await self.session.get(Shop, shop_id)
        if shop is None:
            raise NotFoundError(f"Shop {shop_id} not found")
        return shop

    async def _group(self, group_id: int) -> ShopGroup:
        group = await self.session.get(ShopGroup, group_id)
        if group is None:
            raise NotFoundError(f"Shop group {group_id} not found")
        return group

    async def _source(self, source_id: int) -> Source:
        source = await self.session.get(Source, source_id)
        if source is None:
            raise NotFoundError(f"Source {source_id} not found")
        return source

    async def _country(self, code: str) -> Country:
        country = await self.session.get(Country, code.upper())
        if country is None:
            raise ValidationError(
                f"Unknown country '{code}'. Add the country first.", code="unknown_country"
            )
        return country

    async def _market(self, code: str) -> Market:
        market = await self.session.get(Market, code)
        if market is None:
            raise ValidationError(
                f"Unknown market '{code}'. Open the market first.", code="unknown_market"
            )
        return market
