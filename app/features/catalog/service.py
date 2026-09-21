"""The catalogue: families, the things that are bought, and what is known about them."""

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Attribute,
    AttributeValue,
    Brand,
    Category,
    CategoryAttribute,
    Product,
    Variant,
    VariantAttribute,
    VariantGtin,
    VariantMpn,
)
from app.db.query import paginated
from app.features.catalog.identity import (
    compose_title,
    compute_identity_key,
    normalize_model,
    slugify,
)
from app.features.catalog.schemas import (
    IdentifierCreate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    VariantAttributeRead,
    VariantAttributeSet,
    VariantCreate,
    VariantGtinRead,
    VariantMpnRead,
    VariantRead,
    VariantUpdate,
)
from app.schemas.pagination import Pagination


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- products ---

    async def list_products(
        self,
        pagination: Pagination,
        *,
        brand_id: int | None = None,
        category_id: int | None = None,
        search: str | None = None,
    ) -> tuple[list[ProductRead], int]:
        stmt = select(Product)
        if brand_id is not None:
            stmt = stmt.where(Product.brand_id == brand_id)
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if search:
            stmt = stmt.where(Product.title.ilike(f"%{search}%"))

        rows, total = await paginated(self.session, stmt.order_by(Product.id), pagination)
        return [ProductRead.model_validate(row) for row in rows], total

    async def get_product(self, product_id: int) -> ProductRead:
        return ProductRead.model_validate(await self._product(product_id))

    async def create_product(self, payload: ProductCreate) -> ProductRead:
        brand = await self._brand(payload.brand_id)
        await self._category(payload.category_id)

        product = Product(
            **payload.model_dump(),
            title=compose_title(brand.canonical_name, payload.model, []),
            # A placeholder until the row has an id, which the slug needs. Unique because
            # nothing else can be generating this string at the same moment.
            slug=f"pending-{payload.brand_id}-{normalize_model(payload.model)}",
        )
        self.session.add(product)
        await self._flush_new(product, what="product")

        product.slug = slugify(product.title, entity_id=product.id)
        await self.session.flush()
        await self.session.refresh(product)

        audit.set_target("product", product.id)
        audit.record_changes(**payload.model_dump(mode="json"), title=product.title)
        return ProductRead.model_validate(product)

    async def update_product(self, product_id: int, payload: ProductUpdate) -> ProductRead:
        product = await self._product(product_id)
        audit.set_target("product", product.id)
        sent = payload.model_dump(exclude_unset=True, mode="json")

        if payload.category_id is not None:
            await self._category(payload.category_id)
            product.category_id = payload.category_id
        if payload.model is not None:
            product.model = payload.model
        if "title_override" in sent:
            product.title_override = payload.title_override
        if "description" in sent:
            product.description = payload.description
        if "manufacturer_url" in sent:
            product.manufacturer_url = payload.manufacturer_url
        if payload.is_visible is not None:
            product.is_visible = payload.is_visible

        if payload.model is not None:
            brand = await self._brand(product.brand_id)
            product.title = compose_title(brand.canonical_name, product.model, [])
            product.slug = slugify(product.title, entity_id=product.id)

        await self.session.flush()
        await self.session.refresh(product)
        audit.record_changes(**sent)
        return ProductRead.model_validate(product)

    # --- variants ---

    async def list_variants(
        self,
        pagination: Pagination,
        *,
        product_id: int | None = None,
        category_id: int | None = None,
        brand_id: int | None = None,
        identified: bool | None = None,
    ) -> tuple[list[VariantRead], int]:
        stmt = select(Variant)
        if product_id is not None:
            stmt = stmt.where(Variant.product_id == product_id)
        if category_id is not None:
            stmt = stmt.where(Variant.category_id == category_id)
        if brand_id is not None:
            stmt = stmt.where(Variant.brand_id == brand_id)
        if identified is not None:
            stmt = stmt.where(
                Variant.identity_key.is_not(None) if identified else Variant.identity_key.is_(None)
            )

        rows, total = await paginated(self.session, stmt.order_by(Variant.id), pagination)
        return [VariantRead.model_validate(row) for row in rows], total

    async def get_variant(self, variant_id: int) -> VariantRead:
        return VariantRead.model_validate(await self._variant(variant_id))

    async def create_variant(self, payload: VariantCreate) -> VariantRead:
        await self._brand(payload.brand_id)
        await self._category(payload.category_id)
        if payload.product_id is not None:
            await self._product(payload.product_id)

        variant = Variant(
            **payload.model_dump(),
            model_normalized=normalize_model(payload.model),
            title="",
            slug=f"pending-{payload.brand_id}-{normalize_model(payload.model)}",
        )
        self.session.add(variant)
        await self._flush_new(variant, what="variant")

        await self._regenerate(variant)
        await self.session.refresh(variant)

        audit.set_target("variant", variant.id)
        audit.record_changes(**payload.model_dump(mode="json"), title=variant.title)
        return VariantRead.model_validate(variant)

    async def update_variant(self, variant_id: int, payload: VariantUpdate) -> VariantRead:
        variant = await self._variant(variant_id)
        audit.set_target("variant", variant.id)
        sent = payload.model_dump(exclude_unset=True, mode="json")

        if "product_id" in sent:
            if payload.product_id is not None:
                await self._product(payload.product_id)
            variant.product_id = payload.product_id
        if payload.category_id is not None:
            await self._category(payload.category_id)
            variant.category_id = payload.category_id
        if payload.model is not None:
            variant.model = payload.model
            variant.model_normalized = normalize_model(payload.model)
        if payload.kind is not None:
            variant.kind = payload.kind.value
        if payload.unit_count is not None:
            variant.unit_count = payload.unit_count
        if "title_override" in sent:
            variant.title_override = payload.title_override
        if "description" in sent:
            variant.description = payload.description
        if "image_url_override" in sent:
            variant.image_url_override = payload.image_url_override
        if payload.is_visible is not None:
            variant.is_visible = payload.is_visible

        # The category decides which attributes carry identity, the model and the kind are
        # in the key, and the title is built from all of them — so any of these means both
        # are stale.
        await self._regenerate(variant)
        await self.session.refresh(variant)
        audit.record_changes(**sent, identity_key=variant.identity_key)
        return VariantRead.model_validate(variant)

    # --- what is known about a variant ---

    async def list_variant_attributes(self, variant_id: int) -> list[VariantAttributeRead]:
        await self._variant(variant_id)
        rows = await self.session.scalars(
            select(VariantAttribute)
            .where(VariantAttribute.variant_id == variant_id)
            .order_by(VariantAttribute.attribute_id)
        )
        return [VariantAttributeRead.model_validate(row) for row in rows]

    async def set_variant_attribute(
        self, variant_id: int, payload: VariantAttributeSet
    ) -> VariantAttributeRead:
        variant = await self._variant(variant_id)
        attribute = await self._attribute(payload.attribute_id)
        audit.set_target("variant", variant_id)
        await self._check_value_matches_type(attribute, payload)

        row = await self.session.get(VariantAttribute, (variant_id, payload.attribute_id))
        if row is None:
            row = VariantAttribute(variant_id=variant_id, **payload.model_dump(mode="python"))
            self.session.add(row)
        else:
            for field, value in payload.model_dump(exclude={"attribute_id"}).items():
                setattr(row, field, value)

        await self.session.flush()
        await self._regenerate(variant)
        await self.session.refresh(row)
        audit.record_changes(attribute_id=payload.attribute_id, identity_key=variant.identity_key)
        return VariantAttributeRead.model_validate(row)

    async def clear_variant_attribute(self, variant_id: int, attribute_id: int) -> None:
        variant = await self._variant(variant_id)
        if await self.session.get(VariantAttribute, (variant_id, attribute_id)) is None:
            raise NotFoundError(f"Attribute {attribute_id} is not set on variant {variant_id}")

        audit.set_target("variant", variant_id)
        await self.session.execute(
            delete(VariantAttribute).where(
                VariantAttribute.variant_id == variant_id,
                VariantAttribute.attribute_id == attribute_id,
            )
        )
        await self.session.flush()
        await self._regenerate(variant)
        audit.record_changes(cleared_attribute_id=attribute_id, identity_key=variant.identity_key)

    async def list_gtins(self, variant_id: int) -> list[VariantGtinRead]:
        await self._variant(variant_id)
        rows = await self.session.scalars(
            select(VariantGtin)
            .where(VariantGtin.variant_id == variant_id)
            .order_by(VariantGtin.gtin)
        )
        return [VariantGtinRead.model_validate(row) for row in rows]

    async def add_gtin(self, variant_id: int, payload: IdentifierCreate) -> VariantGtinRead:
        await self._variant(variant_id)
        audit.set_target("variant", variant_id)

        digits = payload.value.strip()
        row = VariantGtin(variant_id=variant_id, gtin=digits, origin=payload.origin.value)
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                f"'{digits}' is already on this variant, or is not a barcode"
            ) from exc

        await self.session.refresh(row)
        audit.record_changes(added_gtin=digits)
        return VariantGtinRead.model_validate(row)

    async def list_mpns(self, variant_id: int) -> list[VariantMpnRead]:
        await self._variant(variant_id)
        rows = await self.session.scalars(
            select(VariantMpn)
            .where(VariantMpn.variant_id == variant_id)
            .order_by(VariantMpn.mpn_normalized)
        )
        return [VariantMpnRead.model_validate(row) for row in rows]

    async def add_mpn(self, variant_id: int, payload: IdentifierCreate) -> VariantMpnRead:
        variant = await self._variant(variant_id)
        audit.set_target("variant", variant_id)

        row = VariantMpn(
            variant_id=variant_id,
            # Copied from the variant so the blocking index can span the pair: two makers
            # reuse the same part number string freely.
            brand_id=variant.brand_id,
            mpn_raw=payload.value,
            mpn_normalized=normalize_model(payload.value),
            origin=payload.origin.value,
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"'{payload.value}' is already on this variant") from exc

        await self.session.refresh(row)
        audit.record_changes(added_mpn=row.mpn_normalized)
        return VariantMpnRead.model_validate(row)

    # --- derivation ---

    async def _regenerate(self, variant: Variant) -> None:
        """Rebuild the title, the slug and the identity key from what is known now.

        Called after anything they are built from changes. Recomputing all three together
        is what keeps them from disagreeing with each other.
        """
        brand = await self._brand(variant.brand_id)
        axes = await self._identity_axes(variant.category_id)
        values = await self._attribute_values(variant.id)

        ordered = [
            values[key].display
            for key in [axis.key for axis in axes]
            if key in values and values[key].display
        ]
        variant.title = compose_title(brand.canonical_name, variant.model, ordered)
        variant.slug = slugify(variant.title, entity_id=variant.id)
        key = compute_identity_key(
            brand_id=variant.brand_id,
            category_id=variant.category_id,
            model_normalized=variant.model_normalized,
            kind=variant.kind,
            unit_count=variant.unit_count,
            identity_values={key: value.raw for key, value in values.items()},
            expected_keys={axis.key for axis in axes},
        )
        variant.identity_key = key

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise await self._identity_taken(key) from exc

    async def _identity_taken(self, key: str | None) -> ConflictError:
        """Filling in the last axis is exactly when a duplicate surfaces.

        Two variants that arrive at the same key are the same thing, so this is the design
        working rather than failing — but it has to say so, and say which row to merge
        into. A bare integrity error would reach the caller as a 500 and tell them nothing.
        """
        other = await self.session.scalar(select(Variant.id).where(Variant.identity_key == key))
        return ConflictError(
            f"Variant {other} already has this identity: the two describe the same thing,"
            " and one should be merged into the other",
            code="identity_taken",
            details={"variant_id": other},
        )

    async def _identity_axes(self, category_id: int) -> list[Attribute]:
        """The category's identity-bearing attributes, in its own display order."""
        rows = await self.session.execute(
            select(Attribute)
            .join(CategoryAttribute, CategoryAttribute.attribute_id == Attribute.id)
            .where(
                CategoryAttribute.category_id == category_id,
                CategoryAttribute.identity_bearing.is_(True),
            )
            .order_by(CategoryAttribute.position, Attribute.id)
        )
        return list(rows.scalars())

    async def _attribute_values(self, variant_id: int) -> dict[str, "_Value"]:
        rows = await self.session.execute(
            select(VariantAttribute, Attribute, AttributeValue)
            .join(Attribute, Attribute.id == VariantAttribute.attribute_id)
            .outerjoin(AttributeValue, AttributeValue.id == VariantAttribute.value_id)
            .where(VariantAttribute.variant_id == variant_id)
        )
        found: dict[str, _Value] = {}
        for row, attribute, enum_value in rows:
            if enum_value is not None:
                found[attribute.key] = _Value(
                    raw=enum_value.canonical, display=enum_value.canonical
                )
            elif row.value_num is not None:
                found[attribute.key] = _Value(raw=row.value_num, display=_plain(row.value_num))
            elif row.value_bool is not None:
                found[attribute.key] = _Value(raw=row.value_bool, display="")
            else:
                # Text never bears identity, so it takes no part in the key or the title.
                found[attribute.key] = _Value(raw=None, display="")
        return found

    async def _check_value_matches_type(
        self, attribute: Attribute, payload: VariantAttributeSet
    ) -> None:
        """The type lives on the attribute and the value on the variant, so no constraint
        spans them. A number stored in the text column would be invisible to every range
        filter and would quietly drop out of the identity key."""
        expected = {
            "enum": payload.value_id,
            "number": payload.value_num,
            "bool": payload.value_bool,
            "text": payload.value_text,
        }[attribute.value_type]
        if expected is None:
            raise ValidationError(
                f"'{attribute.key}' is a {attribute.value_type} attribute; give a matching value",
                code="value_type_mismatch",
            )
        if payload.value_id is not None:
            value = await self.session.get(AttributeValue, payload.value_id)
            if value is None or value.attribute_id != attribute.id:
                raise ValidationError(
                    f"Value {payload.value_id} is not a value of '{attribute.key}'",
                    code="value_not_of_attribute",
                )

    # --- lookups ---

    async def _flush_new(self, row: object, *, what: str) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"That {what} already exists") from exc

    async def _product(self, product_id: int) -> Product:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found")
        return product

    async def _variant(self, variant_id: int) -> Variant:
        variant = await self.session.get(Variant, variant_id)
        if variant is None:
            raise NotFoundError(f"Variant {variant_id} not found")
        return variant

    async def _brand(self, brand_id: int) -> Brand:
        brand = await self.session.get(Brand, brand_id)
        if brand is None:
            raise NotFoundError(f"Brand {brand_id} not found")
        return brand

    async def _category(self, category_id: int) -> Category:
        category = await self.session.get(Category, category_id)
        if category is None:
            raise NotFoundError(f"Category {category_id} not found")
        return category

    async def _attribute(self, attribute_id: int) -> Attribute:
        attribute = await self.session.get(Attribute, attribute_id)
        if attribute is None:
            raise NotFoundError(f"Attribute {attribute_id} not found")
        return attribute


class _Value:
    """One attribute value in the two forms derivation needs: hashed, and written out."""

    __slots__ = ("raw", "display")

    def __init__(self, raw: str | Decimal | bool | None, display: str) -> None:
        self.raw = raw
        self.display = display


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")
