"""Country lookups, and the one field on a country that genuinely moves."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import Country, Currency
from app.db.query import paginated
from app.features.countries.schemas import CountryCreate, CountryRead, CountryUpdate
from app.schemas.pagination import Pagination


class CountryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_countries(
        self, pagination: Pagination, *, is_eu: bool | None = None
    ) -> tuple[list[CountryRead], int]:
        stmt = select(Country)
        if is_eu is not None:
            stmt = stmt.where(Country.is_eu.is_(is_eu))

        rows, total = await paginated(self.session, stmt.order_by(Country.code), pagination)
        return [CountryRead.model_validate(row) for row in rows], total

    async def get_country(self, code: str) -> CountryRead:
        return CountryRead.model_validate(await self._row(code))

    async def create_country(self, payload: CountryCreate) -> CountryRead:
        await self._require_currency(payload.currency_code)

        country = Country(**payload.model_dump())
        self.session.add(country)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"Country '{payload.code}' already exists") from exc

        await self.session.refresh(country)
        audit.set_target("country", country.code)
        # Dumped in JSON mode: the audit store is JSONB, and a Decimal reaching it makes
        # the write fail. The middleware swallows that failure, so the only symptom is a
        # missing record.
        audit.record_changes(**payload.model_dump(mode="json"))
        return CountryRead.model_validate(country)

    async def update_country(self, code: str, payload: CountryUpdate) -> CountryRead:
        country = await self._row(code)

        # Named before the checks below, so a refused edit is recorded against the
        # country it was aimed at rather than at nothing.
        audit.set_target("country", country.code)

        # JSON mode, so the Decimal rate arrives at the JSONB audit column as a string
        # rather than failing the write silently.
        sent = payload.model_dump(exclude_unset=True, mode="json")
        if payload.currency_code is not None:
            await self._require_currency(payload.currency_code)
            country.currency_code = payload.currency_code
        if payload.name is not None:
            country.name = payload.name
        if payload.is_eu is not None:
            country.is_eu = payload.is_eu
        # The one field where an explicit null means something: the rate is unknown
        # again. Without that, a wrong rate can only ever be replaced by another guess.
        if "vat_standard_rate" in sent:
            country.vat_standard_rate = payload.vat_standard_rate

        await self.session.flush()
        await self.session.refresh(country)
        audit.record_changes(**sent)
        return CountryRead.model_validate(country)

    async def _row(self, code: str) -> Country:
        country = await self.session.get(Country, code.upper())
        if country is None:
            raise NotFoundError(f"Country '{code}' not found")
        return country

    async def _require_currency(self, code: str) -> None:
        """Checked here rather than left to the foreign key, so the caller is told which
        currency was wrong instead of reading a constraint name.

        The model comes from `app.db.models`, which every feature shares — this is not a
        reach into the currencies feature.
        """
        if await self.session.get(Currency, code) is None:
            raise ValidationError(f"Unknown currency '{code}'", code="unknown_currency")
