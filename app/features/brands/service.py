"""Brands and the strings that resolve to them."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import (
    Brand,
    BrandAlias,
    Category,
    ModelAlias,
    Offer,
    OfferMatch,
    Product,
    RereadRequest,
    Variant,
)
from app.db.query import offer_is_listed, ordered, paginated_rows
from app.features.brands.normalization import normalize_brand, normalize_model_name
from app.features.brands.schemas import (
    AliasKind,
    BrandAliasCreate,
    BrandAliasRead,
    BrandCreate,
    BrandMatch,
    BrandRead,
    BrandRow,
    BrandUpdate,
    ModelAliasCreate,
    ModelAliasRead,
    RereadRequestRead,
)
from app.schemas.pagination import Pagination


class BrandService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_brands(
        self,
        pagination: Pagination,
        *,
        search: str | None = None,
        ids: list[int] | None = None,
        has: dict[str, bool] | None = None,
    ) -> tuple[list[BrandRow], int]:
        stmt = _brand_rows()
        if search:
            stmt = stmt.where(Brand.canonical_name.ilike(f"%{search}%"))
        if ids:
            stmt = stmt.where(Brand.id.in_(ids))
        columns = {c.name: c for c in stmt.selected_columns}
        for count, wanted in (has or {}).items():
            stmt = stmt.where(columns[count] > 0 if wanted else columns[count] == 0)

        stmt = ordered(
            stmt,
            pagination,
            {"id": Brand.id, "name": Brand.canonical_name, **columns},
            Brand.id,
        )
        rows, total = await paginated_rows(self.session, stmt, pagination)
        return [_brand_row(row) for row in rows], total

    async def get_brand(self, brand_id: int) -> BrandRow:
        return await self._read_brand(brand_id)

    async def create_brand(self, payload: BrandCreate) -> BrandRow:
        brand = Brand(**payload.model_dump())
        self.session.add(brand)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        await self.session.refresh(brand)
        audit.set_target("brand", brand.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return await self._read_brand(brand.id)

    async def update_brand(self, brand_id: int, payload: BrandUpdate) -> BrandRow:
        brand = await self._brand(brand_id)
        audit.set_target("brand", brand.id)

        sent = payload.model_dump(exclude_unset=True, mode="json")
        if payload.canonical_name is not None:
            brand.canonical_name = payload.canonical_name
        if payload.slug is not None:
            brand.slug = payload.slug

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        audit.record_changes(**sent)
        return await self._read_brand(brand.id)

    # --- aliases ---

    async def list_aliases(self, brand_id: int) -> list[BrandAliasRead]:
        await self._brand(brand_id)
        rows = await self.session.scalars(
            select(BrandAlias)
            .where(BrandAlias.brand_id == brand_id)
            .order_by(BrandAlias.kind, BrandAlias.alias_normalized)
        )
        return [BrandAliasRead.model_validate(row) for row in rows]

    async def add_alias(self, brand_id: int, payload: BrandAliasCreate) -> BrandAliasRead:
        await self._brand(brand_id)
        audit.set_target("brand", brand_id)

        normalized = normalize_brand(payload.alias)
        alias = BrandAlias(
            brand_id=brand_id,
            alias_normalized=normalized,
            alias_raw=payload.alias,
            kind=payload.kind.value,
            origin=payload.origin.value,
        )
        self.session.add(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"'{normalized}' is already an alias of this brand") from exc

        await self.session.refresh(alias)
        audit.record_changes(added_alias=normalized, kind=payload.kind.value)
        return BrandAliasRead.model_validate(alias)

    async def remove_alias(self, brand_id: int, alias_id: int) -> None:
        await self._brand(brand_id)
        alias = await self.session.get(BrandAlias, alias_id)
        if alias is None or alias.brand_id != brand_id:
            raise NotFoundError(f"Alias {alias_id} is not on brand {brand_id}")

        audit.set_target("brand", brand_id)
        audit.record_changes(removed_alias=alias.alias_normalized)
        await self.session.execute(delete(BrandAlias).where(BrandAlias.id == alias_id))

    # --- the model registry: what this maker calls what it makes ---

    async def list_models(
        self, brand_id: int, *, category_id: int | None = None
    ) -> list[ModelAliasRead]:
        await self._brand(brand_id)
        stmt = select(ModelAlias).where(ModelAlias.brand_id == brand_id)
        if category_id is not None:
            stmt = stmt.where(ModelAlias.category_id == category_id)
        rows = await self.session.scalars(
            stmt.order_by(ModelAlias.category_id, ModelAlias.model, ModelAlias.alias_normalized)
        )
        return [ModelAliasRead.model_validate(row) for row in rows]

    async def add_model(self, brand_id: int, payload: ModelAliasCreate) -> ModelAliasRead:
        """One spelling a shop uses, and the name the catalogue gives it.

        Unique per category and brand on the normalized alias: one spelling must not read
        as two models of one kind. The reverse is the point — several spellings read as one
        model. The same spelling may name a phone and a tablet; each category reads its own.
        """
        await self._brand(brand_id)
        audit.set_target("brand", brand_id)
        if await self.session.get(Category, payload.category_id) is None:
            raise NotFoundError(f"Category {payload.category_id} not found")

        normalized = normalize_model_name(payload.alias)
        alias = ModelAlias(
            brand_id=brand_id,
            category_id=payload.category_id,
            alias_normalized=normalized,
            model=payload.model,
            origin=payload.origin.value,
        )
        self.session.add(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                f"'{normalized}' already names a model of this brand in this category"
            ) from exc

        await self.session.refresh(alias)
        audit.record_changes(
            added_model_alias=normalized, model=payload.model, category_id=payload.category_id
        )
        await self._ask_for_reread(brand_id, payload.category_id)
        return ModelAliasRead.model_validate(alias)

    async def remove_model(self, brand_id: int, alias_id: int) -> None:
        await self._brand(brand_id)
        alias = await self.session.get(ModelAlias, alias_id)
        if alias is None or alias.brand_id != brand_id:
            raise NotFoundError(f"Model alias {alias_id} is not on brand {brand_id}")

        audit.set_target("brand", brand_id)
        audit.record_changes(removed_model_alias=alias.alias_normalized, model=alias.model)
        await self.session.execute(delete(ModelAlias).where(ModelAlias.id == alias_id))
        await self._ask_for_reread(brand_id, alias.category_id)

    async def request_reread(self, brand_id: int, category_id: int) -> RereadRequestRead:
        """The same request a registry change leaves, asked for by hand."""
        await self._brand(brand_id)
        if await self.session.get(Category, category_id) is None:
            raise NotFoundError(f"Category {category_id} not found")
        audit.set_target("brand", brand_id)
        request = await self._ask_for_reread(brand_id, category_id)
        audit.record_changes(reread_requested=request.id, category_id=category_id)
        return RereadRequestRead.model_validate(request)

    async def list_rereads(self, brand_id: int) -> list[RereadRequestRead]:
        await self._brand(brand_id)
        rows = await self.session.scalars(
            select(RereadRequest)
            .where(RereadRequest.brand_id == brand_id)
            .order_by(RereadRequest.id.desc())
            .limit(50)
        )
        return [RereadRequestRead.model_validate(row) for row in rows]

    async def _ask_for_reread(self, brand_id: int, category_id: int) -> RereadRequest:
        """One open request per maker and category, moved to now by every change.

        A change to the registry reaches no stored reading by itself — the version covers the
        rules, not the words — so it leaves this for the scheduler. The time moves with each
        change because the scheduler waits for them to go quiet: 235 names entered in a row
        are one re-read, not 235. A change arriving while one is being read starts it over,
        since the pages already read were read with the words as they were.
        """
        now = datetime.now(UTC)
        statement = (
            insert(RereadRequest)
            .values(brand_id=brand_id, category_id=category_id, requested_at=now)
            .on_conflict_do_update(
                index_elements=[RereadRequest.brand_id, RereadRequest.category_id],
                index_where=RereadRequest.finished_at.is_(None),
                set_={"requested_at": now, "started_at": None, "after_offer_id": 0, "read": 0},
            )
            .returning(RereadRequest.id)
        )
        request_id = await self.session.scalar(statement)
        await self.session.flush()
        return await self.session.get(RereadRequest, request_id, populate_existing=True)

    # --- what the matcher will call ---

    async def resolve(self, value: str, *, titles_only: bool = False) -> list[BrandMatch]:
        """Every brand a string could mean.

        One result is a deterministic signal. More than one is evidence, not proof — the
        category an offer landed in is what settles it, from the brands that already have
        variants there. Zero means the string belongs in the candidate queue.

        `titles_only` drops `line` aliases, which are the ones that must never be read out
        of a title: "Spigen case for iPhone 15" is not an Apple product.
        """
        try:
            normalized = normalize_brand(value)
        except ValueError:
            return []

        stmt = (
            select(BrandAlias, Brand)
            .join(Brand, Brand.id == BrandAlias.brand_id)
            .where(BrandAlias.alias_normalized == normalized)
        )
        if titles_only:
            stmt = stmt.where(BrandAlias.kind == AliasKind.SPELLING.value)

        rows = await self.session.execute(stmt.order_by(Brand.id))
        return [
            BrandMatch(
                brand=BrandRead.model_validate(brand),
                matched_alias=alias.alias_normalized,
                kind=AliasKind(alias.kind),
            )
            for alias, brand in rows
        ]

    async def _read_brand(self, brand_id: int) -> BrandRow:
        row = (await self.session.execute(_brand_rows().where(Brand.id == brand_id))).first()
        if row is None:
            raise NotFoundError(f"Brand {brand_id} not found")
        return _brand_row(row)

    async def _brand(self, brand_id: int) -> Brand:
        brand = await self.session.get(Brand, brand_id)
        if brand is None:
            raise NotFoundError(f"Brand {brand_id} not found")
        return brand


def _brand_rows() -> Select[Any]:
    """Each brand with five counts, correlated so that a page costs only its own rows."""

    def count(column: Any, *where: Any) -> Any:
        return select(func.count(column)).where(*where).correlate(Brand).scalar_subquery()

    offers = (
        select(func.count(Offer.id))
        .select_from(Offer)
        .join(OfferMatch, (OfferMatch.offer_id == Offer.id) & OfferMatch.superseded_at.is_(None))
        .join(Variant, Variant.id == OfferMatch.variant_id)
        .where(Variant.brand_id == Brand.id, Offer.condition == "new", offer_is_listed())
        .correlate(Brand)
        .scalar_subquery()
    )
    return select(
        Brand,
        count(Product.id, Product.brand_id == Brand.id).label("products_count"),
        count(Variant.id, Variant.brand_id == Brand.id).label("variants_count"),
        offers.label("offers_count"),
        count(BrandAlias.id, BrandAlias.brand_id == Brand.id).label("aliases_count"),
        count(ModelAlias.id, ModelAlias.brand_id == Brand.id).label("models_count"),
    )


def _brand_row(row: Any) -> BrandRow:
    brand = row[0]
    return BrandRow(
        id=brand.id,
        slug=brand.slug,
        canonical_name=brand.canonical_name,
        products_count=row.products_count,
        variants_count=row.variants_count,
        offers_count=row.offers_count,
        aliases_count=row.aliases_count,
        models_count=row.models_count,
    )
