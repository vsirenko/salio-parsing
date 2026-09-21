"""The price history: recording a change, and reading the series back."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models import Offer, PriceEvent
from app.db.query import paginated
from app.features.prices.schemas import PriceEventRead
from app.schemas.pagination import Pagination


class PriceService:
    """Owns both sides on purpose.

    The rule for *when* a row is written is the same knowledge as what the table means, so
    it lives here rather than in whatever happens to be ingesting. Ingestion calls `record`;
    it does not decide.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        offer: Offer,
        *,
        price: Decimal | None,
        currency_code: str | None,
        availability: str,
    ) -> PriceEvent | None:
        """Write a row only if something a chart would show has moved.

        Changes, never snapshots: a million offers photographed daily are some 365 million
        rows a year, and almost all of them repeat the row before. Availability counts as a
        change because going out of stock is a gap that means as much as a number.
        """
        latest = await self._latest(offer.id)
        if (
            latest is not None
            and latest.price == price
            and latest.currency_code == currency_code
            and latest.availability == availability
        ):
            return None

        event = PriceEvent(
            offer_id=offer.id,
            seller_id=offer.seller_id,
            market_code=offer.market_code,
            condition=offer.condition,
            # Null until something matches this listing to a variant. Filled in then, and
            # rewritten if the match changes — which touches one listing's rows, not the
            # table.
            variant_id=None,
            price=price,
            currency_code=currency_code,
            availability=availability,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def history(
        self,
        pagination: Pagination,
        *,
        offer_id: int | None = None,
        variant_id: int | None = None,
        condition: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[PriceEventRead], int]:
        """Newest first, by cursor.

        An append-only feed read by offset repeats rows as new ones arrive, which is the
        same reason the audit trail is paged this way.
        """
        stmt = select(PriceEvent)
        if pagination.before_id is not None:
            stmt = stmt.where(PriceEvent.id < pagination.before_id)
        if offer_id is not None:
            stmt = stmt.where(PriceEvent.offer_id == offer_id)
        if variant_id is not None:
            stmt = stmt.where(PriceEvent.variant_id == variant_id)
        if condition is not None:
            stmt = stmt.where(PriceEvent.condition == condition)
        if since is not None:
            stmt = stmt.where(PriceEvent.at >= since)
        if until is not None:
            stmt = stmt.where(PriceEvent.at <= until)

        rows, total = await paginated(self.session, stmt.order_by(PriceEvent.id.desc()), pagination)
        return [PriceEventRead.model_validate(row) for row in rows], total

    async def offer_history(
        self, offer_id: int, pagination: Pagination
    ) -> tuple[list[PriceEventRead], int]:
        if await self.session.get(Offer, offer_id) is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        return await self.history(pagination, offer_id=offer_id)

    async def _latest(self, offer_id: int) -> PriceEvent | None:
        return await self.session.scalar(
            select(PriceEvent)
            .where(PriceEvent.offer_id == offer_id)
            .order_by(PriceEvent.at.desc(), PriceEvent.id.desc())
            .limit(1)
        )
