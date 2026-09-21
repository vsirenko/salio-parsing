"""Markets: the storefronts we run."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import Country, Market
from app.db.query import paginated
from app.features.markets.schemas import MarketCreate, MarketRead, MarketUpdate
from app.schemas.pagination import Pagination


class MarketService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_markets(
        self, pagination: Pagination, *, is_enabled: bool | None = None
    ) -> tuple[list[MarketRead], int]:
        stmt = select(Market)
        if is_enabled is not None:
            stmt = stmt.where(Market.is_enabled.is_(is_enabled))

        rows, total = await paginated(self.session, stmt.order_by(Market.code), pagination)
        return [MarketRead.model_validate(row) for row in rows], total

    async def get_market(self, code: str) -> MarketRead:
        return MarketRead.model_validate(await self._row(code))

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
        return MarketRead.model_validate(market)

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
        return MarketRead.model_validate(market)

    async def _row(self, code: str) -> Market:
        market = await self.session.get(Market, code.upper())
        if market is None:
            raise NotFoundError(f"Market '{code}' not found")
        return market
