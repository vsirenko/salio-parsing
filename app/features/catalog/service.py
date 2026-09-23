"""The catalogue: families, the things that are bought, and what is known about them."""

from decimal import Decimal

from sqlalchemy import delete, select, update
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
    OfferMatch,
    Product,
    Variant,
    VariantAttribute,
    VariantGtin,
    VariantMerge,
    VariantMpn,
)
from app.db.query import paginated
from app.features.catalog.identity import (
    compose_title,
    compute_identity_key,
    display_number,
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


def _placeholder(brand_id: int, model: str, *, limit: int) -> str:
    """A slug to hold the row down until it has an id and a real one.

    Cut to fit the column it is going into. A model can be two hundred characters — a shop
    title used as one, when nothing better was read — and `products.slug` holds a hundred
    and sixty, so the unbounded version failed the insert rather than the validation, which
    is the worst place to find out.
    """
    head = f"pending-{brand_id}-"
    return (head + normalize_model(model))[:limit]


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
            slug=_placeholder(payload.brand_id, payload.model, limit=160),
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
            slug=_placeholder(payload.brand_id, payload.model, limit=200),
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
        self, variant_id: int, payload: VariantAttributeSet, *, only_if_absent: bool = False
    ) -> VariantAttributeRead | None:
        """Set an axis, or — with `only_if_absent` — fill it in only where there is nothing.

        Filling a gap and overwriting an answer are different acts and only one of them is
        safe to do from a match. A shop that states 512 GB for a phone whose own title reads
        `4/128GB` exists in the collected data; letting the second listing to arrive replace
        the first one's value would make the catalogue's answer depend on crawl order.
        """
        variant = await self._variant(variant_id)
        attribute = await self._attribute(payload.attribute_id)
        audit.set_target("variant", variant_id)
        await self._check_value_matches_type(attribute, payload)

        row = await self.session.get(VariantAttribute, (variant_id, payload.attribute_id))
        if row is not None and only_if_absent:
            return None
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

        # The form every reading stores, so a barcode typed in from a box meets the one a shop
        # sent. The column's check holds the two to it.
        digits = payload.value.strip()
        if digits.isdigit() and 8 <= len(digits) <= 14:
            digits = digits.zfill(14)
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

    # --- two entries that turned out to be one ---

    async def merge_variants(
        self, from_id: int, into_id: int, *, reason: str, decided_by: str = "rule"
    ) -> VariantRead:
        """Fold one catalogue entry into another and leave a forwarding note.

        The catalogue splits a product in two whenever two shops write its model
        differently — `PHONE WAVE 7C` and `Wave 7C`, `Edge 70 Fusion` and
        `Motorola Edge 70 Fusion` — and neither entry is wrong, they are the same thing seen
        twice. The listings go over, the identifiers go over, and the axes the survivor was
        missing are filled from the one being folded in; an axis both of them hold is left
        alone, because disagreeing about a colour is not something a merge should silently
        settle.

        The row in `variant_merges` is the point of doing it this way rather than deleting:
        the old id keeps resolving, so a link that was handed out yesterday still arrives
        somewhere.
        """
        if from_id == into_id:
            raise ValidationError("A variant cannot be merged into itself", code="same_variant")

        loser = await self._variant(from_id)
        survivor = await self._variant(into_id)
        if loser.brand_id != survivor.brand_id or loser.category_id != survivor.category_id:
            raise ValidationError(
                "These are filed under different brands or categories, so they are not one"
                " thing written two ways",
                code="not_the_same_thing",
            )

        audit.set_target("variant", survivor.id)

        # The listings first: an offer holds at most one live match, so this is a move and
        # never a collision.
        moved = await self.session.execute(
            update(OfferMatch)
            .where(OfferMatch.variant_id == from_id, OfferMatch.superseded_at.is_(None))
            .values(variant_id=into_id)
        )
        await self.session.execute(
            update(OfferMatch).where(OfferMatch.variant_id == from_id).values(variant_id=into_id)
        )

        carried = await self._carry_identifiers(from_id, into_id)
        filled = await self._carry_axes(from_id, into_id)

        # The loser's key goes before the survivor's is recomputed: they are about to be
        # the same string, and the column is unique.
        loser.identity_key = None
        await self.session.flush()

        self.session.add(
            VariantMerge(
                from_id=from_id,
                into_id=into_id,
                reason=reason[:500],
                decided_by=decided_by,
            )
        )
        await self.session.delete(loser)
        await self.session.flush()

        await self._regenerate(survivor)
        await self.session.refresh(survivor)
        audit.record_changes(
            merged_from=from_id,
            listings_moved=moved.rowcount or 0,
            identifiers_carried=carried,
            axes_filled=filled,
            reason=reason,
        )
        return VariantRead.model_validate(survivor)

    async def _carry_identifiers(self, from_id: int, into_id: int) -> int:
        """Every barcode and part number the survivor does not already hold."""
        carried = 0
        pairs = ((VariantGtin, VariantGtin.gtin), (VariantMpn, VariantMpn.mpn_normalized))
        for table, column in pairs:
            held = set(
                (
                    await self.session.scalars(select(column).where(table.variant_id == into_id))
                ).all()
            )
            rows = (
                await self.session.scalars(select(table).where(table.variant_id == from_id))
            ).all()
            for row in rows:
                value = getattr(row, column.key)
                if value in held:
                    await self.session.delete(row)
                    continue
                row.variant_id = into_id
                held.add(value)
                carried += 1
        await self.session.flush()
        return carried

    async def _carry_axes(self, from_id: int, into_id: int) -> int:
        """The axes the survivor has nothing for, and only those.

        An axis both entries hold is left as the survivor wrote it. Two entries that
        disagree about a colour are a question, and a merge that answered it quietly would
        be the confident wrong answer this project keeps refusing to give.
        """
        held = set(
            (
                await self.session.scalars(
                    select(VariantAttribute.attribute_id).where(
                        VariantAttribute.variant_id == into_id
                    )
                )
            ).all()
        )
        filled = 0
        rows = (
            await self.session.scalars(
                select(VariantAttribute).where(VariantAttribute.variant_id == from_id)
            )
        ).all()
        for row in rows:
            if row.attribute_id in held:
                await self.session.delete(row)
                continue
            row.variant_id = into_id
            filled += 1
        await self.session.flush()
        return filled

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
        # Asked before it is written, not discovered afterwards. A failed flush leaves the
        # session needing a rollback, and a rollback here empties the caller's whole
        # transaction — a pass that meant to skip one listing would lose every listing
        # before it, and the answer to this conflict is itself a query the broken session
        # can no longer serve.
        taken = (
            None
            if key is None
            else await self.session.scalar(
                select(Variant.id).where(Variant.identity_key == key, Variant.id != variant.id)
            )
        )
        if taken is not None:
            raise ConflictError(
                f"Variant {taken} already has this identity: the two describe the same"
                " thing, and one should be merged into the other",
                code="identity_taken",
                details={"variant_id": taken},
            )

        variant.identity_key = key
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # Two writers reached the same key between the question and the answer. Rare,
            # and there is nothing to look up any more — the session is spent either way.
            raise ConflictError(
                "Another variant took this identity while this one was being written",
                code="identity_taken",
            ) from exc

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
                found[attribute.key] = _Value(
                    raw=row.value_num,
                    display=display_number(row.value_num, attribute.unit_dimension),
                )
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
