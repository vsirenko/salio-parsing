"""The canonical attribute registry, its aliases, and what a category makes of it."""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Attribute,
    AttributeAlias,
    AttributeValue,
    AttributeValueAlias,
    Category,
    CategoryAttribute,
)
from app.db.query import paginated
from app.features.attributes.schemas import (
    AliasCreate,
    AliasRead,
    AttributeCreate,
    AttributeRead,
    CategoryAttributeCreate,
    CategoryAttributeRead,
    CategoryAttributeUpdate,
    ValueAliasRead,
    ValueCreate,
    ValueRead,
    ValueType,
)
from app.schemas.pagination import Pagination


class AttributeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- the registry ---

    async def list_attributes(
        self, pagination: Pagination, *, value_type: ValueType | None = None
    ) -> tuple[list[AttributeRead], int]:
        stmt = select(Attribute)
        if value_type is not None:
            stmt = stmt.where(Attribute.value_type == value_type.value)

        rows, total = await paginated(self.session, stmt.order_by(Attribute.key), pagination)
        return [AttributeRead.model_validate(row) for row in rows], total

    async def get_attribute(self, attribute_id: int) -> AttributeRead:
        return AttributeRead.model_validate(await self._attribute(attribute_id))

    async def create_attribute(self, payload: AttributeCreate) -> AttributeRead:
        attribute = Attribute(**payload.model_dump(mode="json"))
        self.session.add(attribute)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The attribute key '{payload.key}' is taken") from exc

        await self.session.refresh(attribute)
        audit.set_target("attribute", attribute.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return AttributeRead.model_validate(attribute)

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

    # --- enum values, and what the sources call those ---

    async def list_values(self, attribute_id: int) -> list[ValueRead]:
        await self._attribute(attribute_id)
        rows = await self.session.scalars(
            select(AttributeValue)
            .where(AttributeValue.attribute_id == attribute_id)
            .order_by(AttributeValue.position, AttributeValue.canonical)
        )
        return [ValueRead.model_validate(row) for row in rows]

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

        await self.session.refresh(value)
        audit.record_changes(added_value=payload.canonical)
        return ValueRead.model_validate(value)

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

    async def list_for_category(self, category_id: int) -> list[CategoryAttributeRead]:
        await self._category(category_id)
        rows = await self.session.scalars(
            select(CategoryAttribute)
            .where(CategoryAttribute.category_id == category_id)
            .order_by(CategoryAttribute.position, CategoryAttribute.attribute_id)
        )
        return [CategoryAttributeRead.model_validate(row) for row in rows]

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
        return CategoryAttributeRead.model_validate(link)

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
        return CategoryAttributeRead.model_validate(link)

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
