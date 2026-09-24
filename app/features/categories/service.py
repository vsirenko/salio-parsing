"""The category tree, and the visibility that cascades down it."""

from typing import Any

from sqlalchemy import Select, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Category,
    CategoryAlias,
    CategoryAttribute,
    Offer,
    OfferMatch,
    Product,
    Variant,
)
from app.db.query import offer_is_listed, ordered, paginated_rows
from app.features.categories.schemas import (
    CategoryAliasCreate,
    CategoryAliasRead,
    CategoryCreate,
    CategoryNode,
    CategoryRead,
    CategoryRow,
    CategoryUpdate,
)
from app.schemas.pagination import Pagination

# Recomputed for the whole tree rather than for the subtree that moved. There are few
# categories, the walk is instant, and "recompute everything" cannot leave a stale branch
# behind the way a clever partial update can.
RECOMPUTE_VISIBILITY = text("""
    with recursive tree as (
        select id, is_visible as effective
        from categories
        where parent_id is null
        union all
        select child.id, tree.effective and child.is_visible
        from categories child
        join tree on child.parent_id = tree.id
    )
    update categories
    set is_visible_effective = tree.effective
    from tree
    where categories.id = tree.id
      and categories.is_visible_effective is distinct from tree.effective
""")

# Walks up from a prospective parent. If the category itself appears, the move would
# close a loop and orphan everything under it from the root.
ANCESTORS = text("""
    with recursive up as (
        select id, parent_id from categories where id = :parent_id
        union all
        select parent.id, parent.parent_id
        from categories parent
        join up on parent.id = up.parent_id
    )
    select 1 from up where id = :category_id limit 1
""")


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_categories(
        self,
        pagination: Pagination,
        *,
        parent_id: int | None = None,
        roots_only: bool = False,
        is_visible_effective: bool | None = None,
        search: str | None = None,
        ids: list[int] | None = None,
    ) -> tuple[list[CategoryRow], int]:
        stmt = _category_rows()
        if roots_only:
            stmt = stmt.where(Category.parent_id.is_(None))
        elif parent_id is not None:
            stmt = stmt.where(Category.parent_id == parent_id)
        if is_visible_effective is not None:
            stmt = stmt.where(Category.is_visible_effective.is_(is_visible_effective))
        if ids:
            stmt = stmt.where(Category.id.in_(ids))
        if search and search.strip():
            stmt = stmt.where(_category_search(search.strip()))

        columns = {c.name: c for c in stmt.selected_columns}
        stmt = ordered(
            stmt,
            pagination,
            {**columns, "id": Category.id, "name": Category.name, "slug": Category.slug},
            Category.id,
        )
        rows, total = await paginated_rows(self.session, stmt, pagination)
        return [_category_row(row) for row in rows], total

    async def tree(self) -> list[CategoryNode]:
        """Every category at once, nested, with its branch's totals.

        There are few of them, and a front end paging through them a hundred at a time to
        build a tree or a filter was the alternative.
        """
        rows = (await self.session.execute(_category_rows().order_by(Category.name))).all()
        nodes = {row[0].id: _node(row) for row in rows}
        roots: list[CategoryNode] = []
        for node in nodes.values():
            parent = nodes.get(node.parent_id) if node.parent_id is not None else None
            (parent.children if parent else roots).append(node)
        for root in roots:
            _add_up(root)
        return roots

    async def get_category(self, category_id: int) -> CategoryRow:
        return await self._read(category_id)

    async def create_category(self, payload: CategoryCreate) -> CategoryRead:
        if payload.parent_id is not None:
            await self._row(payload.parent_id)

        category = Category(**payload.model_dump())
        self.session.add(category)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        await self._recompute_visibility()
        await self.session.refresh(category)
        audit.set_target("category", category.id)
        audit.record_changes(**payload.model_dump(mode="json"))
        return await self._read(category.id)

    async def update_category(self, category_id: int, payload: CategoryUpdate) -> CategoryRead:
        category = await self._row(category_id)

        # Named before the guards, so a refused edit is recorded against the category it
        # was aimed at rather than at nothing.
        audit.set_target("category", category.id)

        sent = payload.model_dump(exclude_unset=True, mode="json")
        # An explicit null means "make this a root", which is different from not sending
        # the field at all — so presence is what is checked, not the value.
        moving = "parent_id" in sent and payload.parent_id != category.parent_id
        if moving and payload.parent_id is not None:
            await self._require_no_cycle(category.id, payload.parent_id)
            category.parent_id = payload.parent_id
        elif moving:
            category.parent_id = None

        if payload.name is not None:
            category.name = payload.name
        if payload.slug is not None:
            category.slug = payload.slug
        if payload.is_visible is not None:
            category.is_visible = payload.is_visible
        if payload.identity_ready is not None:
            category.identity_ready = payload.identity_ready
        if payload.model_match_needs_full_identity is not None:
            category.model_match_needs_full_identity = payload.model_match_needs_full_identity

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"The slug '{payload.slug}' is already taken") from exc

        # Visibility and the shape of the tree are the two things it depends on.
        if moving or payload.is_visible is not None:
            await self._recompute_visibility()

        await self.session.refresh(category)
        audit.record_changes(**sent)
        return await self._read(category.id)

    # --- what shops call it ---

    async def remove_alias(self, category_id: int, alias_id: int) -> None:
        await self._row(category_id)
        alias = await self.session.get(CategoryAlias, alias_id)
        if alias is None or alias.category_id != category_id:
            raise NotFoundError(f"Alias {alias_id} is not on category {category_id}")

        audit.set_target("category", category_id)
        audit.record_changes(removed_alias=alias.alias_normalized)
        await self.session.execute(delete(CategoryAlias).where(CategoryAlias.id == alias_id))

    async def list_aliases(self, category_id: int) -> list[CategoryAliasRead]:
        await self._row(category_id)
        rows = await self.session.scalars(
            select(CategoryAlias)
            .where(CategoryAlias.category_id == category_id)
            .order_by(CategoryAlias.alias_normalized)
        )
        return [CategoryAliasRead.model_validate(row) for row in rows]

    async def add_alias(self, category_id: int, payload: CategoryAliasCreate) -> CategoryAliasRead:
        await self._row(category_id)
        audit.set_target("category", category_id)

        alias = CategoryAlias(
            category_id=category_id,
            alias_normalized=payload.alias,
            language=payload.language,
            origin=payload.origin.value,
        )
        self.session.add(alias)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"'{payload.alias}' already names this category") from exc

        await self.session.refresh(alias)
        audit.record_changes(added_alias=payload.alias, language=payload.language)
        return CategoryAliasRead.model_validate(alias)

    async def _read(self, category_id: int) -> CategoryRow:
        row = (
            await self.session.execute(_category_rows().where(Category.id == category_id))
        ).first()
        if row is None:
            raise NotFoundError(f"Category {category_id} not found")
        return _category_row(row)

    async def _row(self, category_id: int) -> Category:
        category = await self.session.get(Category, category_id)
        if category is None:
            raise NotFoundError(f"Category {category_id} not found")
        return category

    async def _require_no_cycle(self, category_id: int, parent_id: int) -> None:
        await self._row(parent_id)
        found = await self.session.scalar(
            ANCESTORS, {"parent_id": parent_id, "category_id": category_id}
        )
        if found:
            raise ValidationError(
                "That parent sits under this category, so the move would close a loop",
                code="category_cycle",
            )

    async def _recompute_visibility(self) -> None:
        await self.session.execute(RECOMPUTE_VISIBILITY)


def _category_rows() -> Select[Any]:
    """Each category with six counts of its own, correlated: a page costs its own rows."""
    child = Category.__table__.alias("child")

    def count(column: Any, *where: Any) -> Any:
        return select(func.count(column)).where(*where).correlate(Category).scalar_subquery()

    offers = (
        select(func.count(Offer.id))
        .select_from(Offer)
        .join(OfferMatch, (OfferMatch.offer_id == Offer.id) & OfferMatch.superseded_at.is_(None))
        .join(Variant, Variant.id == OfferMatch.variant_id)
        .where(Variant.category_id == Category.id, Offer.condition == "new", offer_is_listed())
        .correlate(Category)
        .scalar_subquery()
    )
    return select(
        Category,
        count(Product.id, Product.category_id == Category.id).label("products_count"),
        count(Variant.id, Variant.category_id == Category.id).label("variants_count"),
        offers.label("offers_count"),
        count(child.c.id, child.c.parent_id == Category.id).label("children_count"),
        count(CategoryAlias.id, CategoryAlias.category_id == Category.id).label("aliases_count"),
        count(CategoryAttribute.attribute_id, CategoryAttribute.category_id == Category.id).label(
            "attributes_count"
        ),
    )


def _category_search(text: str) -> Any:
    """The name or slug, or a name a shop gives it."""
    pattern = f"%{text}%"
    return or_(
        Category.name.ilike(pattern),
        Category.slug.ilike(pattern),
        Category.id.in_(
            select(CategoryAlias.category_id).where(CategoryAlias.alias_normalized.ilike(pattern))
        ),
    )


def _counts(row: Any) -> dict[str, Any]:
    category = row[0]
    return {
        **CategoryRead.model_validate(category).model_dump(),
        "products_count": row.products_count,
        "variants_count": row.variants_count,
        "offers_count": row.offers_count,
        "children_count": row.children_count,
        "aliases_count": row.aliases_count,
        "attributes_count": row.attributes_count,
    }


def _category_row(row: Any) -> CategoryRow:
    return CategoryRow(**_counts(row))


def _node(row: Any) -> CategoryNode:
    counts = _counts(row)
    return CategoryNode(
        **counts,
        branch_products_count=counts["products_count"],
        branch_variants_count=counts["variants_count"],
        branch_offers_count=counts["offers_count"],
        children=[],
    )


def _add_up(node: CategoryNode) -> None:
    for child in node.children:
        _add_up(child)
        node.branch_products_count += child.branch_products_count
        node.branch_variants_count += child.branch_variants_count
        node.branch_offers_count += child.branch_offers_count
