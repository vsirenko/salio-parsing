"""The category tree, and the visibility that cascades down it."""

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import Category
from app.db.query import paginated
from app.features.categories.schemas import CategoryCreate, CategoryRead, CategoryUpdate
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
    ) -> tuple[list[CategoryRead], int]:
        stmt = select(Category)
        if roots_only:
            stmt = stmt.where(Category.parent_id.is_(None))
        elif parent_id is not None:
            stmt = stmt.where(Category.parent_id == parent_id)
        if is_visible_effective is not None:
            stmt = stmt.where(Category.is_visible_effective.is_(is_visible_effective))

        rows, total = await paginated(self.session, stmt.order_by(Category.id), pagination)
        return [CategoryRead.model_validate(row) for row in rows], total

    async def get_category(self, category_id: int) -> CategoryRead:
        return CategoryRead.model_validate(await self._row(category_id))

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
        return CategoryRead.model_validate(category)

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
        return CategoryRead.model_validate(category)

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
