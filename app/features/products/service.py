"""Product business logic."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Product
from app.db.query import paginated
from app.features.products.schemas import ProductCreate, ProductRead
from app.schemas.pagination import Pagination


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_products(
        self,
        pagination: Pagination,
        *,
        search: str | None = None,
        in_stock: bool | None = None,
    ) -> tuple[list[ProductRead], int]:
        stmt = select(Product)
        if search:
            stmt = stmt.where(Product.name.ilike(f"%{search}%"))
        if in_stock is not None:
            stmt = stmt.where(Product.in_stock.is_(in_stock))

        rows, total = await paginated(self.session, stmt.order_by(Product.id), pagination)
        return [ProductRead.model_validate(row) for row in rows], total

    async def get_product(self, product_id: int) -> ProductRead:
        product = await self.session.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found")
        return ProductRead.model_validate(product)

    async def create_product(self, payload: ProductCreate) -> ProductRead:
        product = Product(**payload.model_dump())
        self.session.add(product)
        try:
            # Flush rather than commit: the request transaction owns the commit, but we
            # need the generated id and the unique violation now.
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"Product '{payload.name}' already exists") from exc

        await self.session.refresh(product)
        return ProductRead.model_validate(product)
