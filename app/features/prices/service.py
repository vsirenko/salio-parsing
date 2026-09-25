"""The two histories: what a listing cost, and whether it could be bought."""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import AvailabilityEvent, Offer, PriceEvent, Product, Variant
from app.db.query import paginated
from app.features.prices.schemas import (
    AvailabilityEventRead,
    DayPrice,
    PriceEventRead,
    PriceSeries,
    ShopPoint,
    ShopSeries,
)
from app.schemas.pagination import Pagination


class PriceService:
    """Owns both sides of both series on purpose.

    When a change counts is the same knowledge as what the table means, so it lives here
    rather than in whatever happens to be ingesting. Ingestion calls `record_*`; it does
    not decide.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- writing ---

    async def record_price(
        self,
        offer: Offer,
        *,
        price: Decimal | None,
        currency_code: str | None,
        source_id: int | None = None,
    ) -> PriceEvent | None:
        """A row only when the price has moved.

        Changes, never snapshots: a million offers photographed daily are some 365 million
        rows a year, almost all of them repeating the row before.
        """
        latest = await self._latest(PriceEvent, offer.id)
        if latest is not None and latest.price == price and latest.currency_code == currency_code:
            return None

        event = PriceEvent(
            **self._context(offer),
            source_id=source_id,
            price=price,
            currency_code=currency_code,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def record_availability(
        self, offer: Offer, *, availability: str, source_id: int | None = None
    ) -> AvailabilityEvent | None:
        """A row only when the stock state has moved.

        Separate from the price because availability arrives through channels that carry no
        price — a stock ping, a webhook, a faster poll. Writing one of those as a price
        event would mean repeating the last known price and calling it an observation.
        """
        latest = await self._latest(AvailabilityEvent, offer.id)
        if latest is not None and latest.availability == availability:
            return None

        event = AvailabilityEvent(
            **self._context(offer), source_id=source_id, availability=availability
        )
        self.session.add(event)
        await self.session.flush()
        return event

    # --- reading ---

    async def price_history(
        self,
        pagination: Pagination,
        *,
        offer_id: int | None = None,
        variant_id: int | None = None,
        condition: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[PriceEventRead], int]:
        stmt = self._filtered(
            select(PriceEvent),
            PriceEvent,
            pagination=pagination,
            offer_id=offer_id,
            variant_id=variant_id,
            condition=condition,
            since=since,
            until=until,
        )
        rows, total = await paginated(self.session, stmt.order_by(PriceEvent.id.desc()), pagination)
        return [PriceEventRead.model_validate(row) for row in rows], total

    async def availability_history(
        self,
        pagination: Pagination,
        *,
        offer_id: int | None = None,
        variant_id: int | None = None,
        condition: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[AvailabilityEventRead], int]:
        stmt = self._filtered(
            select(AvailabilityEvent),
            AvailabilityEvent,
            pagination=pagination,
            offer_id=offer_id,
            variant_id=variant_id,
            condition=condition,
            since=since,
            until=until,
        )
        rows, total = await paginated(
            self.session, stmt.order_by(AvailabilityEvent.id.desc()), pagination
        )
        return [AvailabilityEventRead.model_validate(row) for row in rows], total

    # --- pieces ---

    @staticmethod
    def _context(offer: Offer) -> dict:
        """What a chart groups by, copied off the offer because none of it ever changes for
        a given listing — unlike the variant, which is an opinion and rides along as a
        hint."""
        return {
            "offer_id": offer.id,
            "seller_id": offer.seller_id,
            "market_code": offer.market_code,
            "condition": offer.condition,
            "variant_id": None,
        }

    @staticmethod
    def _filtered(
        stmt: Select,
        model: type[PriceEvent] | type[AvailabilityEvent],
        *,
        pagination: Pagination,
        offer_id: int | None,
        variant_id: int | None,
        condition: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> Select:
        if pagination.before_id is not None:
            stmt = stmt.where(model.id < pagination.before_id)
        if offer_id is not None:
            stmt = stmt.where(model.offer_id == offer_id)
        if variant_id is not None:
            stmt = stmt.where(model.variant_id == variant_id)
        if condition is not None:
            stmt = stmt.where(model.condition == condition)
        if since is not None:
            stmt = stmt.where(model.at >= since)
        if until is not None:
            stmt = stmt.where(model.at <= until)
        return stmt

    async def _latest(
        self, model: type[PriceEvent] | type[AvailabilityEvent], offer_id: int
    ) -> PriceEvent | AvailabilityEvent | None:
        return await self.session.scalar(
            select(model)
            .where(model.offer_id == offer_id)
            .order_by(model.at.desc(), model.id.desc())
            .limit(1)
        )

    async def require_offer(self, offer_id: int) -> Offer:
        offer = await self.session.get(Offer, offer_id)
        if offer is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        return offer

    async def series(
        self,
        *,
        variant_id: int | None = None,
        product_id: int | None = None,
        market_code: str = "LV",
        condition: str = "new",
        days: int = 90,
        with_out_of_stock: bool = False,
    ) -> PriceSeries:
        """A price chart's data for one entry or one family, day by day.

        The rows record changes, not days, so a listing's price on a day is its last change
        before the day ended, carried forward; and a listing counts only between its first
        and last sighting, so a card the shop took down stops pulling the band. Which
        listings is the catalogue's answer now — the ones currently matched — not the
        `variant_id` a row was written with, which is only a hint: a match corrected today
        moves that listing's whole history onto the right chart.
        """
        if (variant_id is None) == (product_id is None):
            raise ValidationError("Name a variant_id or a product_id", code="one_scope")
        if variant_id is not None and await self.session.get(Variant, variant_id) is None:
            raise NotFoundError(f"Variant {variant_id} not found")
        if product_id is not None and await self.session.get(Product, product_id) is None:
            raise NotFoundError(f"Product {product_id} not found")

        until = datetime.now(UTC).date()
        since = until - timedelta(days=days - 1)
        rows = (
            await self.session.execute(
                text(_SERIES),
                {
                    "variant_id": variant_id,
                    "product_id": product_id,
                    "market": market_code.upper(),
                    "condition": condition,
                    "since": since,
                    "until": until,
                    "with_out_of_stock": with_out_of_stock,
                },
            )
        ).all()

        by_day: dict[date, list[Decimal]] = defaultdict(list)
        by_shop: dict[tuple[int, str], dict[date, Decimal]] = defaultdict(dict)
        currencies: Counter[str] = Counter()
        for day, shop_id, shop_name, price, currency in rows:
            by_day[day].append(price)
            line = by_shop[(shop_id, shop_name)]
            line[day] = min(price, line.get(day, price))
            currencies[currency] += 1
        return PriceSeries(
            variant_id=variant_id,
            product_id=product_id,
            market_code=market_code.upper(),
            condition=condition,
            currency_code=currencies.most_common(1)[0][0] if currencies else None,
            since=since,
            until=until,
            days=[
                DayPrice(
                    day=day,
                    min=min(prices),
                    median=Decimal(str(median(prices))).quantize(Decimal("0.01")),
                    max=max(prices),
                    listings=len(prices),
                )
                for day, prices in sorted(by_day.items())
            ],
            shops=[
                ShopSeries(
                    shop_id=shop_id,
                    shop_name=shop_name,
                    points=[ShopPoint(day=day, price=price) for day, price in sorted(line.items())],
                )
                for (shop_id, shop_name), line in sorted(by_shop.items(), key=lambda i: i[0][1])
            ],
        )


# Every listing now matched into the scope, crossed with every day of the window; for each,
# its last price and last stock state before the day ended. Both lookups walk an
# (offer_id, at) index. A listing counts from the day it was first seen to the day it was
# last seen.
_SERIES = """
with listing as (
    select o.id as offer_id, sh.id as shop_id, sh.name as shop_name,
           o.first_seen_at, o.last_seen_at
    from offer_matches m
    join offers o on o.id = m.offer_id
    join sellers se on se.id = o.seller_id
    join shops sh on sh.id = se.shop_id
    join variants v on v.id = m.variant_id
    where m.superseded_at is null
      and (v.id = :variant_id or v.product_id = :product_id)
      and o.market_code = :market
      and o.condition = :condition
),
day as (
    select d::date as day, d + interval '1 day' as day_end
    from generate_series(cast(:since as date), cast(:until as date), interval '1 day') as d
)
select day.day, l.shop_id, l.shop_name, p.price, p.currency_code
from day
cross join listing l
cross join lateral (
    select pe.price, pe.currency_code from price_events pe
    where pe.offer_id = l.offer_id and pe.at < day.day_end
    order by pe.at desc limit 1
) p
left join lateral (
    select ae.availability from availability_events ae
    where ae.offer_id = l.offer_id and ae.at < day.day_end
    order by ae.at desc limit 1
) a on true
where l.first_seen_at < day.day_end
  and l.last_seen_at >= day.day
  and p.price is not null
  and (:with_out_of_stock or coalesce(a.availability, 'unknown') <> 'out_of_stock')
"""
