"""Currency lookups. Read-only: ISO 4217 is not ours to edit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Currency
from app.db.query import paginated
from app.features.currencies.schemas import CurrencyRead
from app.schemas.pagination import Pagination


class CurrencyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_currencies(self, pagination: Pagination) -> tuple[list[CurrencyRead], int]:
        stmt = select(Currency).order_by(Currency.code)
        rows, total = await paginated(self.session, stmt, pagination)
        return [CurrencyRead.model_validate(row) for row in rows], total
