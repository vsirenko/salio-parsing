"""The canonical attribute registry, its aliases, and what a category makes of it."""

from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Attribute,
    AttributeAlias,
    AttributeValue,
    AttributeValueAlias,
    AttributeValueDismissal,
    Category,
    CategoryAttribute,
    User,
    VariantAttribute,
)
from app.db.query import ordered, paginated_rows
from app.features.attributes.normalization import normalize_attribute_name
from app.features.attributes.schemas import (
    AliasCreate,
    AliasRead,
    AttributeCategoryRead,
    AttributeCreate,
    AttributeRead,
    AttributeRef,
    AttributeRow,
    AttributeUpdate,
    CategoryAttributeCreate,
    CategoryAttributeRead,
    CategoryAttributeUpdate,
    DismissalCreate,
    DismissalRead,
    ValueAliasRead,
    ValueCreate,
    ValueRead,
    ValueResolution,
    ValueType,
    ValueUpdate,
)
from app.schemas.pagination import Pagination


class AttributeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- the registry ---

    async def list_attributes(
        self,
        pagination: Pagination,
        *,
        value_type: ValueType | None = None,
        search: str | None = None,
        ids: list[int] | None = None,
    ) -> tuple[list[AttributeRow], int]:
        stmt = _attribute_rows()
        if value_type is not None:
            stmt = stmt.where(Attribute.value_type == value_type.value)
        if ids:
            stmt = stmt.where(Attribute.id.in_(ids))
        if search and search.strip():
            stmt = stmt.where(_attribute_search(search.strip()))

        columns = {c.name: c for c in stmt.selected_columns}
        stmt = ordered(
            stmt,
            pagination,
            {**columns, "id": Attribute.id, "key": Attribute.key, "name": Attribute.name},
            Attribute.id,
        )
        rows, total = await paginated_rows(self.session, stmt, pagination)
        return [_attribute_row(row) for row in rows], total

    async def get_attribute(self, attribute_id: int) -> AttributeRow:
        return await self._read(attribute_id)

    async def create_attribute(self, payload: AttributeCreate) -> AttributeRow:
        attribute = Attribute(**payload.model_dump(mode="json"))
        self.session.add(attribute)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The attribute key '{payload.key}' is taken") from exc

        audit.set_target("attribute", attribute.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return await self._read(attribute.id)

    async def update_attribute(self, attribute_id: int, payload: AttributeUpdate) -> AttributeRow:
        attribute = await self._attribute(attribute_id)
        audit.set_target("attribute", attribute_id)
        sent = payload.model_dump(exclude_unset=True, mode="json")

        if {"unit_dimension", "scale"} & set(sent):
            if attribute.value_type != ValueType.NUMBER.value:
                raise ValidationError(
                    "unit_dimension and scale only apply to a number attribute",
                    code="not_a_number",
                )
            stored = await self.session.scalar(
                select(func.count())
                .select_from(VariantAttribute)
                .where(VariantAttribute.attribute_id == attribute_id)
            )
            if stored:
                raise ConflictError(
                    f"{stored} entries hold a value of '{attribute.key}' in"
                    f" {attribute.unit_dimension or 'no unit'}; changing the unit would make"
                    " each of them a different amount",
                    code="values_stored",
                )
            if "unit_dimension" in sent:
                attribute.unit_dimension = payload.unit_dimension
            if "scale" in sent:
                attribute.scale = payload.scale
        if payload.name is not None:
            attribute.name = payload.name
        if payload.labels is not None:
            attribute.labels = payload.labels

        await self.session.flush()
        audit.record_changes(**sent)
        return await self._read(attribute_id)

    async def list_categories(self, attribute_id: int) -> list[AttributeCategoryRead]:
        await self._attribute(attribute_id)
        rows = await self.session.execute(
            select(CategoryAttribute, Category)
            .join(Category, Category.id == CategoryAttribute.category_id)
            .where(CategoryAttribute.attribute_id == attribute_id)
            .order_by(Category.name)
        )
        return [
            AttributeCategoryRead(
                category_id=category.id,
                category_name=category.name,
                category_slug=category.slug,
                identity_bearing=link.identity_bearing,
                position=link.position,
                label_override=link.label_override,
                display_unit=link.display_unit,
            )
            for link, category in rows.all()
        ]

    async def resolve(self, attribute_id: int, query: str) -> ValueResolution:
        """What the registry makes of a string, exactly as a reading would.

        A value's words are compared in the normalized form they are stored in, the way
        `Vocabulary.value_of` looks them up; a colour, whose readings also try phrases of a
        title, is resolved the same way here only for the string as given.
        """
        await self._attribute(attribute_id)
        try:
            normalized = normalize_attribute_name(query)
        except ValueError:
            normalized = ""
        named = bool(
            normalized
            and await self.session.scalar(
                select(func.count())
                .select_from(AttributeAlias)
                .where(
                    AttributeAlias.attribute_id == attribute_id,
                    AttributeAlias.alias_normalized == normalized,
                )
            )
        )
        value = await self.session.scalar(
            select(AttributeValue).where(
                AttributeValue.attribute_id == attribute_id,
                func.lower(AttributeValue.canonical) == query.strip().lower(),
            )
        )
        via = "canonical" if value is not None else None
        if value is None and normalized:
            value = await self.session.scalar(
                select(AttributeValue)
                .join(
                    AttributeValueAlias, AttributeValueAlias.attribute_value_id == AttributeValue.id
                )
                .where(
                    AttributeValueAlias.attribute_id == attribute_id,
                    AttributeValueAlias.alias_normalized == normalized,
                )
            )
            via = "alias" if value is not None else None
        return ValueResolution(
            query=query,
            normalized=normalized,
            is_attribute_name=named,
            value=(await self._values(attribute_id, [value.id]))[0] if value else None,
            via=via,
        )

    # --- aliases: what the sources call it ---

    async def list_aliases(self, attribute_id: int) -> list[AliasRead]:
        await self._attribute(attribute_id)
        rows = await self.session.scalars(
            select(AttributeAlias)
            .where(AttributeAlias.attribute_id == attribute_id)
            .order_by(AttributeAlias.alias_normalized)
        )
        return [AliasRead.model_validate(row) for row in rows]

    async def add_alias(self, attribute_id: int, payload: AliasCreate) -> AliasRead:
        await self._attribute(attribute_id)
        audit.set_target("attribute", attribute_id)

        alias = AttributeAlias(
            attribute_id=attribute_id,
            alias_normalized=payload.alias,
            language=payload.language,
            origin=payload.origin.value,
        )
        self.session.add(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"'{payload.alias}' is already an alias of this attribute") from exc

        await self.session.refresh(alias)
        audit.record_changes(added_alias=payload.alias)
        return AliasRead.model_validate(alias)

    async def remove_alias(self, attribute_id: int, alias_id: int) -> None:
        await self._attribute(attribute_id)
        alias = await self.session.get(AttributeAlias, alias_id)
        if alias is None or alias.attribute_id != attribute_id:
            raise NotFoundError(f"Alias {alias_id} is not on attribute {attribute_id}")
        audit.set_target("attribute", attribute_id)
        audit.record_changes(removed_alias=alias.alias_normalized)
        await self.session.execute(delete(AttributeAlias).where(AttributeAlias.id == alias_id))

    # --- enum values, and what the sources call those ---

    async def list_values(self, attribute_id: int) -> list[ValueRead]:
        await self._attribute(attribute_id)
        return await self._values(attribute_id)

    async def update_value(self, value_id: int, payload: ValueUpdate) -> ValueRead:
        value = await self._value(value_id)
        audit.set_target("attribute", value.attribute_id)
        sent = payload.model_dump(exclude_unset=True, mode="json")
        if payload.position is not None:
            value.position = payload.position
        if payload.labels is not None:
            value.labels = payload.labels
        if payload.in_title is not None:
            # The titles already written keep what they said until their entries are next
            # regenerated; a value's place in names is decided when it is made.
            value.in_title = payload.in_title
        await self.session.flush()
        audit.record_changes(value=value.canonical, **sent)
        return (await self._values(value.attribute_id, [value.id]))[0]

    async def remove_value(self, value_id: int) -> None:
        """Only a value no entry carries. One that is carried is part of those entries'
        identity keys; folding it into another is a merge of entries, not an edit here."""
        value = await self._value(value_id)
        audit.set_target("attribute", value.attribute_id)
        carried = await self.session.scalar(
            select(func.count())
            .select_from(VariantAttribute)
            .where(VariantAttribute.value_id == value_id)
        )
        if carried:
            raise ConflictError(
                f"{carried} entries carry '{value.canonical}'",
                code="value_in_use",
                details={"variants_count": carried},
            )
        audit.record_changes(removed_value=value.canonical)
        await self.session.execute(delete(AttributeValue).where(AttributeValue.id == value_id))

    async def remove_value_alias(self, value_id: int, alias_id: int) -> None:
        value = await self._value(value_id)
        alias = await self.session.get(AttributeValueAlias, alias_id)
        if alias is None or alias.attribute_value_id != value_id:
            raise NotFoundError(f"Alias {alias_id} is not on value {value_id}")
        audit.set_target("attribute", value.attribute_id)
        audit.record_changes(removed_value_alias=alias.alias_normalized, value=value.canonical)
        await self.session.execute(
            delete(AttributeValueAlias).where(AttributeValueAlias.id == alias_id)
        )

    async def add_value(self, attribute_id: int, payload: ValueCreate) -> ValueRead:
        attribute = await self._attribute(attribute_id)
        if attribute.value_type != ValueType.ENUM.value:
            raise ValidationError(
                f"'{attribute.key}' is a {attribute.value_type} attribute; only an enum has"
                " canonical values. A number is parsed, not looked up.",
                code="not_an_enum",
            )

        audit.set_target("attribute", attribute_id)
        value = AttributeValue(attribute_id=attribute_id, **payload.model_dump())
        self.session.add(value)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"'{payload.canonical}' is already a value here") from exc

        audit.record_changes(added_value=payload.canonical)
        return (await self._values(attribute_id, [value.id]))[0]

    async def add_value_alias(self, value_id: int, payload: AliasCreate) -> ValueAliasRead:
        value = await self.session.get(AttributeValue, value_id)
        if value is None:
            raise NotFoundError(f"Attribute value {value_id} not found")

        audit.set_target("attribute", value.attribute_id)
        alias = AttributeValueAlias(
            attribute_value_id=value.id,
            # Repeated from the value so the unique constraint can span the attribute:
            # one spelling must not resolve to two of its values.
            attribute_id=value.attribute_id,
            alias_normalized=payload.alias,
            language=payload.language,
            origin=payload.origin.value,
        )
        self.session.add(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                f"'{payload.alias}' already resolves to a value of this attribute"
            ) from exc

        await self.session.refresh(alias)
        audit.record_changes(added_value_alias=payload.alias, value=value.canonical)
        return ValueAliasRead.model_validate(alias)

    # --- what a category makes of an attribute ---

    # --- what a shop writes that is none of the values ---

    async def list_dismissals(self, attribute_id: int) -> list[DismissalRead]:
        await self._attribute(attribute_id)
        rows = await self.session.execute(
            select(AttributeValueDismissal, User.email)
            .outerjoin(User, User.id == AttributeValueDismissal.dismissed_by)
            .where(AttributeValueDismissal.attribute_id == attribute_id)
            .order_by(AttributeValueDismissal.value_normalized)
        )
        return [_dismissal_read(row, email) for row, email in rows.all()]

    async def dismiss(
        self, attribute_id: int, payload: DismissalCreate, *, by: int
    ) -> DismissalRead:
        """Mark a word as none of this attribute's values — `melna, pelēka` in a colour
        field is two colours — so the list of what the registry does not know stops
        showing it. Marking it again replaces the note."""
        await self._attribute(attribute_id)
        audit.set_target("attribute", attribute_id)
        key = AttributeValueDismissal.key(payload.value)
        row = await self.session.get(AttributeValueDismissal, (attribute_id, key))
        if row is None:
            row = AttributeValueDismissal(attribute_id=attribute_id, value_normalized=key)
            self.session.add(row)
        row.note = payload.note
        row.dismissed_by = by
        await self.session.flush()
        await self.session.refresh(row)
        audit.record_changes(dismissed=key, note=payload.note)
        email = await self.session.scalar(select(User.email).where(User.id == by))
        return _dismissal_read(row, email)

    async def undismiss(self, attribute_id: int, value: str) -> None:
        await self._attribute(attribute_id)
        audit.set_target("attribute", attribute_id)
        key = AttributeValueDismissal.key(value)
        row = await self.session.get(AttributeValueDismissal, (attribute_id, key))
        if row is None:
            raise NotFoundError(f"'{key}' is not marked on attribute {attribute_id}")
        await self.session.delete(row)
        await self.session.flush()
        audit.record_changes(undismissed=key)

    async def list_for_category(self, category_id: int) -> list[CategoryAttributeRead]:
        await self._category(category_id)
        rows = await self.session.execute(
            select(CategoryAttribute, Attribute)
            .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
            .where(CategoryAttribute.category_id == category_id)
            .order_by(CategoryAttribute.position, CategoryAttribute.attribute_id)
        )
        return [_link_read(link, attribute) for link, attribute in rows.all()]

    async def attach(
        self, category_id: int, payload: CategoryAttributeCreate
    ) -> CategoryAttributeRead:
        await self._category(category_id)
        attribute = await self._attribute(payload.attribute_id)
        audit.set_target("category", category_id)
        self._refuse_text_identity(attribute, payload.identity_bearing)

        # Read off the row before the flush: a rollback expires the object, and touching
        # it afterwards would try to reload it in the middle of handling the failure.
        key = attribute.key

        link = CategoryAttribute(category_id=category_id, **payload.model_dump())
        self.session.add(link)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"'{key}' is already on this category") from exc

        await self.session.refresh(link)
        audit.record_changes(attached_attribute=key, **payload.model_dump(mode="json"))
        return _link_read(link, attribute)

    async def update_link(
        self, category_id: int, attribute_id: int, payload: CategoryAttributeUpdate
    ) -> CategoryAttributeRead:
        link = await self._link(category_id, attribute_id)
        audit.set_target("category", category_id)

        sent = payload.model_dump(exclude_unset=True, mode="json")
        if payload.identity_bearing is not None:
            self._refuse_text_identity(
                await self._attribute(attribute_id), payload.identity_bearing
            )
            link.identity_bearing = payload.identity_bearing
        if payload.position is not None:
            link.position = payload.position
        if "label_override" in sent:
            link.label_override = payload.label_override
        if "display_unit" in sent:
            link.display_unit = payload.display_unit

        await self.session.flush()
        await self.session.refresh(link)
        audit.record_changes(attribute_id=attribute_id, **sent)
        return _link_read(link, await self._attribute(attribute_id))

    async def detach(self, category_id: int, attribute_id: int) -> None:
        await self._link(category_id, attribute_id)
        audit.set_target("category", category_id)
        await self.session.execute(
            delete(CategoryAttribute).where(
                CategoryAttribute.category_id == category_id,
                CategoryAttribute.attribute_id == attribute_id,
            )
        )
        audit.record_changes(detached_attribute_id=attribute_id)

    # --- helpers ---

    @staticmethod
    def _refuse_text_identity(attribute: Attribute, identity_bearing: bool) -> None:
        """The one rule the database cannot hold.

        `value_type` sits on the attribute and `identity_bearing` on the pairing, so no
        table constraint spans them. It matters: free text does not compare — "Black matte"
        and "black, matte" are one product and two identity keys — and an unstable key is
        worse than none, because it confidently separates things that are the same.
        """
        if identity_bearing and attribute.value_type == ValueType.TEXT.value:
            raise ValidationError(
                f"'{attribute.key}' is free text, which cannot carry identity: two spellings"
                " of one value would split a variant in two.",
                code="text_cannot_bear_identity",
            )

    async def _read(self, attribute_id: int) -> AttributeRow:
        row = (
            await self.session.execute(_attribute_rows().where(Attribute.id == attribute_id))
        ).first()
        if row is None:
            raise NotFoundError(f"Attribute {attribute_id} not found")
        return _attribute_row(row)

    async def _value(self, value_id: int) -> AttributeValue:
        value = await self.session.get(AttributeValue, value_id)
        if value is None:
            raise NotFoundError(f"Attribute value {value_id} not found")
        return value

    async def _values(self, attribute_id: int, ids: list[int] | None = None) -> list[ValueRead]:
        """The values, each with its aliases and how many entries carry it."""
        carried = (
            select(func.count())
            .select_from(VariantAttribute)
            .where(VariantAttribute.value_id == AttributeValue.id)
            .correlate(AttributeValue)
            .scalar_subquery()
        )
        stmt = (
            select(AttributeValue, carried.label("variants_count"))
            .where(AttributeValue.attribute_id == attribute_id)
            .order_by(AttributeValue.position, AttributeValue.canonical)
        )
        if ids is not None:
            stmt = stmt.where(AttributeValue.id.in_(ids))
        rows = (await self.session.execute(stmt)).all()
        aliases: dict[int, list[ValueAliasRead]] = {}
        if rows:
            found = await self.session.scalars(
                select(AttributeValueAlias)
                .where(AttributeValueAlias.attribute_value_id.in_([v.id for v, _ in rows]))
                .order_by(AttributeValueAlias.alias_normalized)
            )
            for alias in found:
                aliases.setdefault(alias.attribute_value_id, []).append(
                    ValueAliasRead.model_validate(alias)
                )
        return [
            ValueRead(
                id=value.id,
                attribute_id=value.attribute_id,
                canonical=value.canonical,
                position=value.position,
                labels=value.labels or {},
                in_title=value.in_title,
                aliases=aliases.get(value.id, []),
                variants_count=count,
            )
            for value, count in rows
        ]

    async def _attribute(self, attribute_id: int) -> Attribute:
        attribute = await self.session.get(Attribute, attribute_id)
        if attribute is None:
            raise NotFoundError(f"Attribute {attribute_id} not found")
        return attribute

    async def _category(self, category_id: int) -> Category:
        category = await self.session.get(Category, category_id)
        if category is None:
            raise NotFoundError(f"Category {category_id} not found")
        return category

    async def _link(self, category_id: int, attribute_id: int) -> CategoryAttribute:
        link = await self.session.get(CategoryAttribute, (category_id, attribute_id))
        if link is None:
            raise NotFoundError(f"Attribute {attribute_id} is not on category {category_id}")
        return link


def _link_read(link: CategoryAttribute, attribute: Attribute) -> CategoryAttributeRead:
    return CategoryAttributeRead(
        category_id=link.category_id,
        attribute_id=link.attribute_id,
        attribute=AttributeRef.model_validate(attribute),
        identity_bearing=link.identity_bearing,
        position=link.position,
        label_override=link.label_override,
        display_unit=link.display_unit,
    )


def _attribute_rows() -> Select[Any]:
    """Each attribute with four counts, correlated: a page costs its own rows."""

    def count(column: Any, *where: Any) -> Any:
        return select(func.count(column)).where(*where).correlate(Attribute).scalar_subquery()

    return select(
        Attribute,
        count(CategoryAttribute.category_id, CategoryAttribute.attribute_id == Attribute.id).label(
            "categories_count"
        ),
        count(AttributeValue.id, AttributeValue.attribute_id == Attribute.id).label("values_count"),
        count(AttributeAlias.id, AttributeAlias.attribute_id == Attribute.id).label(
            "aliases_count"
        ),
        count(
            func.distinct(VariantAttribute.variant_id),
            VariantAttribute.attribute_id == Attribute.id,
        ).label("variants_count"),
    )


def _attribute_search(text: str) -> Any:
    """The key, the name, or a name a shop gives it."""
    pattern = f"%{text}%"
    found = [Attribute.key.ilike(pattern), Attribute.name.ilike(pattern)]
    try:
        normalized = normalize_attribute_name(text)
    except ValueError:
        normalized = ""
    if normalized:
        found.append(
            Attribute.id.in_(
                select(AttributeAlias.attribute_id).where(
                    AttributeAlias.alias_normalized.ilike(f"%{normalized}%")
                )
            )
        )
    return or_(*found)


def _attribute_row(row: Any) -> AttributeRow:
    return AttributeRow(
        **AttributeRead.model_validate(row[0]).model_dump(),
        categories_count=row.categories_count,
        values_count=row.values_count,
        aliases_count=row.aliases_count,
        variants_count=row.variants_count,
    )


def _dismissal_read(row: AttributeValueDismissal, email: str | None) -> DismissalRead:
    return DismissalRead(
        attribute_id=row.attribute_id,
        value=row.value_normalized,
        note=row.note,
        dismissed_by=email,
        dismissed_at=row.dismissed_at,
    )
