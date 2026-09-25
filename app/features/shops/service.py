"""Shops, the channels we read them through, and the sellers behind them."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, case, delete, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.schedule import next_slot
from app.db.models import (
    Country,
    Market,
    Offer,
    OfferMatch,
    Proxy,
    RawOffer,
    Run,
    Seller,
    Shop,
    ShopGroup,
    ShopMarket,
    Source,
    Variant,
)
from app.db.query import offer_is_listed, ordered, paginated_rows
from app.features.shops.schemas import (
    Access,
    CollectionHealth,
    Fact,
    GroupRef,
    MarketState,
    RunBrief,
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
from app.schemas.pagination import Pagination


class ShopService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- groups ---

    async def list_groups(self, pagination: Pagination) -> tuple[list[ShopGroupRead], int]:
        stmt = _group_rows().order_by(ShopGroup.slug)
        rows, total = await paginated_rows(self.session, stmt, pagination)
        return [_group_read(row) for row in rows], total

    async def get_group(self, group_id: int) -> ShopGroupRead:
        row = (await self.session.execute(_group_rows().where(ShopGroup.id == group_id))).first()
        if row is None:
            raise NotFoundError(f"Shop group {group_id} not found")
        return _group_read(row)

    async def create_group(self, payload: ShopGroupCreate) -> ShopGroupRead:
        group = ShopGroup(**payload.model_dump())
        self.session.add(group)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        audit.set_target("shop_group", group.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return await self.get_group(group.id)

    async def update_group(self, group_id: int, payload: ShopGroupUpdate) -> ShopGroupRead:
        group = await self._group(group_id)
        audit.set_target("shop_group", group.id)
        sent = payload.model_dump(exclude_unset=True, mode="json")
        if payload.name is not None:
            group.name = payload.name
        if payload.slug is not None:
            group.slug = payload.slug
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc
        audit.record_changes(**sent)
        return await self.get_group(group_id)

    # --- shops ---

    async def list_shops(
        self,
        pagination: Pagination,
        *,
        country_code: str | None = None,
        market_code: str | None = None,
        market_state: MarketState = MarketState.SHOWN,
        is_marketplace: bool | None = None,
        search: str | None = None,
        ids: list[int] | None = None,
        health: str | None = None,
    ) -> tuple[list[ShopRead], int]:
        stmt = _shop_rows()
        if country_code is not None:
            stmt = stmt.where(Shop.country_code == country_code.upper())
        if is_marketplace is not None:
            stmt = stmt.where(Shop.is_marketplace.is_(is_marketplace))
        if market_code is not None:
            attached = select(ShopMarket.shop_id).where(
                ShopMarket.market_code == market_code.upper()
            )
            if market_state is not MarketState.ATTACHED:
                attached = attached.where(
                    ShopMarket.is_enabled.is_(market_state is MarketState.SHOWN)
                )
            stmt = stmt.where(Shop.id.in_(attached))
        if ids:
            stmt = stmt.where(Shop.id.in_(ids))
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(Shop.name.ilike(pattern), Shop.slug.ilike(pattern), Shop.website.ilike(pattern))
            )
        columns = {c.name: c for c in stmt.selected_columns}
        if health is not None:
            stmt = stmt.where(_health_status(columns) == health)

        stmt = ordered(
            stmt,
            pagination,
            {
                **columns,
                "id": Shop.id,
                "name": Shop.name,
                "slug": Shop.slug,
                "created_at": Shop.created_at,
            },
            Shop.id,
        )
        rows, total = await paginated_rows(self.session, stmt, pagination)
        return [_shop_read(row) for row in rows], total

    async def get_shop(self, shop_id: int) -> ShopRead:
        # Re-read, not the object in hand: a rating written as 4.5 comes back 4.50.
        stmt = _shop_rows().where(Shop.id == shop_id).execution_options(populate_existing=True)
        row = (await self.session.execute(stmt)).first()
        if row is None:
            raise NotFoundError(f"Shop {shop_id} not found")
        return _shop_read(row)

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

        audit.set_target("shop", shop.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return await self.get_shop(shop.id)

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
        if "logo_url" in sent:
            shop.logo_url = payload.logo_url
        if "rating" in sent:
            shop.rating = payload.rating

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        audit.record_changes(**sent)
        return await self.get_shop(shop_id)

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
        rows = await self.session.execute(
            _source_rows().where(Source.shop_id == shop_id).order_by(Source.id)
        )
        now = datetime.now(UTC)
        return [_source_read(row, now) for row in rows.all()]

    async def get_source(self, source_id: int) -> SourceRead:
        stmt = (
            _source_rows().where(Source.id == source_id).execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            raise NotFoundError(f"Source {source_id} not found")
        return _source_read(row, datetime.now(UTC))

    async def remove_source(self, source_id: int) -> None:
        """Only a channel that has collected nothing. One that has is disabled instead
        (`is_enabled=false`): deleting it would take every observation it made with it —
        the listings' history, their readings, the runs — and that is the record."""
        source = await self._source(source_id)
        audit.set_target("shop", source.shop_id)
        observed = await self.session.scalar(
            select(func.count()).select_from(RawOffer).where(RawOffer.source_id == source_id)
        )
        runs = await self.session.scalar(
            select(func.count()).select_from(Run).where(Run.source_id == source_id)
        )
        if observed or runs:
            raise ConflictError(
                f"'{source.slug}' has {observed} observations and {runs} runs; disable it"
                " instead (is_enabled=false), which keeps its history",
                code="source_has_history",
                details={"observations": observed, "runs": runs},
            )
        audit.record_changes(removed_source=source.slug)
        await self.session.execute(delete(Source).where(Source.id == source_id))

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
        await self._check_proxy(payload.proxy_id)
        source = Source(shop_id=shop_id, **payload.model_dump(mode="json"))
        self.session.add(source)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        audit.record_changes(added_source=payload.slug, **payload.model_dump(mode="json"))
        return await self.get_source(source.id)

    async def _check_proxy(self, proxy_id: int | None) -> None:
        if proxy_id is not None and await self.session.get(Proxy, proxy_id) is None:
            raise ValidationError(f"Proxy {proxy_id} not found", code="unknown_proxy")

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
        if "proxy_id" in sent:
            await self._check_proxy(payload.proxy_id)
            source.proxy_id = payload.proxy_id
        self._check_schedule(source)

        await self.session.flush()
        audit.record_changes(source_id=source_id, **sent)
        return await self.get_source(source_id)

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
        rows = await self.session.execute(
            _seller_rows().where(Seller.shop_id == shop_id).order_by(Seller.id)
        )
        return [_seller_read(row) for row in rows.all()]

    async def update_seller(self, seller_id: int, payload: SellerUpdate) -> SellerRead:
        seller = await self.session.get(Seller, seller_id)
        if seller is None:
            raise NotFoundError(f"Seller {seller_id} not found")
        audit.set_target("shop", seller.shop_id)
        seller.name = payload.name
        await self.session.flush()
        audit.record_changes(seller_id=seller_id, name=payload.name)
        row = (await self.session.execute(_seller_rows().where(Seller.id == seller_id))).first()
        return _seller_read(row)

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

        audit.record_changes(added_seller=payload.external_id)
        row = (await self.session.execute(_seller_rows().where(Seller.id == seller.id))).first()
        return _seller_read(row)

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


# --- rows as a list shows them ---

# A full pass that ended like this says the channel's collection is broken.
_BROKEN = ("failed", "rejected", "interrupted")


def _group_rows() -> Select[Any]:
    shops = (
        select(func.count(Shop.id))
        .where(Shop.shop_group_id == ShopGroup.id)
        .correlate(ShopGroup)
        .scalar_subquery()
    )
    return select(ShopGroup, shops.label("shops_count"))


def _group_read(row: Any) -> ShopGroupRead:
    group = row[0]
    return ShopGroupRead(id=group.id, slug=group.slug, name=group.name, shops_count=row.shops_count)


def _shop_rows() -> Select[Any]:
    """Each shop with its markets, counts and the health of its collection, correlated."""

    def scalar(stmt: Any) -> Any:
        return stmt.correlate(Shop).scalar_subquery()

    newest_full_status = (
        select(Run.status)
        .where(Run.source_id == Source.id, Run.kind == "full", Run.status.in_(("ok", *_BROKEN)))
        .order_by(Run.started_at.desc(), Run.id.desc())
        .limit(1)
        .correlate(Source)
        .scalar_subquery()
    )
    enabled = (Source.shop_id == Shop.id) & Source.is_enabled.is_(True)
    # Counted in place, not over a derived table: a subquery in FROM does not correlate,
    # and `shops` would be joined in again and every row would count every shop's listings.
    on_sale = (
        select(func.count(Offer.id))
        .join(Seller, Seller.id == Offer.seller_id)
        .where(Seller.shop_id == Shop.id, offer_is_listed())
    )
    return select(
        Shop,
        ShopGroup.name.label("group_name"),
        scalar(
            select(func.array_agg(ShopMarket.market_code)).where(
                ShopMarket.shop_id == Shop.id, ShopMarket.is_enabled.is_(True)
            )
        ).label("markets"),
        scalar(
            select(func.array_agg(ShopMarket.market_code)).where(
                ShopMarket.shop_id == Shop.id, ShopMarket.is_enabled.is_(False)
            )
        ).label("hidden_markets"),
        scalar(select(func.count(Source.id)).where(Source.shop_id == Shop.id)).label(
            "sources_count"
        ),
        scalar(select(func.count(Seller.id)).where(Seller.shop_id == Shop.id)).label(
            "sellers_count"
        ),
        scalar(on_sale).label("offers_count"),
        scalar(
            select(func.count(func.distinct(Variant.product_id)))
            .select_from(Offer)
            .join(Seller, Seller.id == Offer.seller_id)
            .join(
                OfferMatch,
                (OfferMatch.offer_id == Offer.id) & OfferMatch.superseded_at.is_(None),
            )
            .join(Variant, Variant.id == OfferMatch.variant_id)
            .where(Seller.shop_id == Shop.id, Offer.condition == "new", offer_is_listed())
        ).label("products_count"),
        scalar(
            select(func.max(Run.finished_at))
            .join(Source, Source.id == Run.source_id)
            .where(Source.shop_id == Shop.id, Run.kind == "full", Run.status == "ok")
        ).label("last_full_ok_at"),
        scalar(select(func.count(Source.id)).where(enabled)).label("enabled_sources"),
        scalar(select(func.count(Source.id)).where(enabled, newest_full_status.in_(_BROKEN))).label(
            "failing_sources"
        ),
        scalar(select(func.count(Source.id)).where(enabled, newest_full_status == "ok")).label(
            "sound_sources"
        ),
    ).outerjoin(ShopGroup, ShopGroup.id == Shop.shop_group_id)


def _health_status(columns: dict[str, Any]) -> Any:
    return case(
        (columns["failing_sources"] > 0, "failing"),
        (columns["sound_sources"] == 0, "never"),
        else_="ok",
    )


def _shop_read(row: Any) -> ShopRead:
    shop = row[0]
    status = "failing" if row.failing_sources else "never" if not row.sound_sources else "ok"
    return ShopRead(
        id=shop.id,
        slug=shop.slug,
        name=shop.name,
        country_code=shop.country_code,
        group=GroupRef(id=shop.shop_group_id, name=row.group_name) if shop.shop_group_id else None,
        website=shop.website,
        logo_url=shop.logo_url,
        is_marketplace=shop.is_marketplace,
        rating=shop.rating,
        created_at=shop.created_at,
        markets=sorted(row.markets or []),
        hidden_markets=sorted(row.hidden_markets or []),
        sources_count=row.sources_count,
        sellers_count=row.sellers_count,
        offers_count=row.offers_count,
        products_count=row.products_count,
        health=CollectionHealth(
            status=status,
            last_full_ok_at=row.last_full_ok_at,
            enabled_sources=row.enabled_sources,
            failing_sources=row.failing_sources,
        ),
    )


def _source_rows() -> Select[Any]:
    """Each channel with its newest run beside it, its newest ok full pass and its listings
    on sale now."""
    newest = (
        select(Run)
        .where(Run.source_id == Source.id)
        .order_by(Run.started_at.desc(), Run.id.desc())
        .limit(1)
        .correlate(Source)
        .lateral("newest")
    )
    last_ok = (
        select(func.max(Run.finished_at))
        .where(Run.source_id == Source.id, Run.kind == "full", Run.status == "ok")
        .correlate(Source)
        .scalar_subquery()
    )
    on_sale = (
        select(func.count(func.distinct(RawOffer.offer_id)))
        .join(Offer, Offer.id == RawOffer.offer_id)
        .where(RawOffer.source_id == Source.id, offer_is_listed())
        .correlate(Source)
        .scalar_subquery()
    )
    return select(
        Source,
        newest.c.id.label("run_id"),
        newest.c.kind.label("run_kind"),
        newest.c.status.label("run_status"),
        newest.c.started_at.label("run_started_at"),
        newest.c.finished_at.label("run_finished_at"),
        newest.c.items_seen.label("run_items_seen"),
        newest.c.error.label("run_error"),
        last_ok.label("last_full_ok_at"),
        on_sale.label("offers_count"),
    ).outerjoin(newest, true())


def _source_read(row: Any, now: datetime) -> SourceRead:
    source = row[0]
    read = SourceRead.model_validate(source)
    return read.model_copy(
        update={
            "last_run": RunBrief(
                id=row.run_id,
                kind=row.run_kind,
                status=row.run_status,
                started_at=row.run_started_at,
                finished_at=row.run_finished_at,
                items_seen=row.run_items_seen,
                error=row.run_error,
            )
            if row.run_id is not None
            else None,
            "last_full_ok_at": row.last_full_ok_at,
            "next_full_at": next_slot(source.cron_full, now) if source.is_enabled else None,
            "next_quick_at": next_slot(source.cron_quick, now) if source.is_enabled else None,
            "offers_count": row.offers_count,
        }
    )


def _seller_rows() -> Select[Any]:
    on_sale = (
        select(func.count(Offer.id))
        .where(Offer.seller_id == Seller.id, offer_is_listed())
        .correlate(Seller)
        .scalar_subquery()
    )
    return select(Seller, on_sale.label("offers_count"))


def _seller_read(row: Any) -> SellerRead:
    seller = row[0]
    return SellerRead(
        id=seller.id,
        shop_id=seller.shop_id,
        external_id=seller.external_id,
        name=seller.name,
        offers_count=row.offers_count,
    )
