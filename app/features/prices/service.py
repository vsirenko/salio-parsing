"""The two histories: what a listing cost, and whether it could be bought."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import AvailabilityEvent, Offer, PriceEvent
from app.db.query import paginated
from app.features.prices.schemas import AvailabilityEventRead, PriceEventRead
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
