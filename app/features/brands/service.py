"""Brands and the strings that resolve to them."""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Brand, BrandAlias, Category, ModelAlias
from app.db.query import paginated
from app.features.brands.normalization import normalize_brand, normalize_model_name
from app.features.brands.schemas import (
    AliasKind,
    BrandAliasCreate,
    BrandAliasRead,
    BrandCreate,
    BrandMatch,
    BrandRead,
    BrandUpdate,
    ModelAliasCreate,
    ModelAliasRead,
)
from app.schemas.pagination import Pagination


class BrandService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_brands(
        self, pagination: Pagination, *, search: str | None = None, ids: list[int] | None = None
    ) -> tuple[list[BrandRead], int]:
        stmt = select(Brand)
        if search:
            stmt = stmt.where(Brand.canonical_name.ilike(f"%{search}%"))
        if ids:
            stmt = stmt.where(Brand.id.in_(ids))

        rows, total = await paginated(
            self.session, stmt.order_by(Brand.canonical_name, Brand.id), pagination
        )
        return [BrandRead.model_validate(row) for row in rows], total

    async def get_brand(self, brand_id: int) -> BrandRead:
        return BrandRead.model_validate(await self._brand(brand_id))

    async def create_brand(self, payload: BrandCreate) -> BrandRead:
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
        return BrandRead.model_validate(brand)

    async def update_brand(self, brand_id: int, payload: BrandUpdate) -> BrandRead:
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

        await self.session.refresh(brand)
        audit.record_changes(**sent)
        return BrandRead.model_validate(brand)

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
        return ModelAliasRead.model_validate(alias)

    async def remove_model(self, brand_id: int, alias_id: int) -> None:
        await self._brand(brand_id)
        alias = await self.session.get(ModelAlias, alias_id)
        if alias is None or alias.brand_id != brand_id:
            raise NotFoundError(f"Model alias {alias_id} is not on brand {brand_id}")

        audit.set_target("brand", brand_id)
        audit.record_changes(removed_model_alias=alias.alias_normalized, model=alias.model)
        await self.session.execute(delete(ModelAlias).where(ModelAlias.id == alias_id))

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

    async def _brand(self, brand_id: int) -> Brand:
        brand = await self.session.get(Brand, brand_id)
        if brand is None:
            raise NotFoundError(f"Brand {brand_id} not found")
        return brand
