"""Product business logic.

Storage is an in-memory dict so the example runs with zero infrastructure.
Swap the bodies of these methods for real DB calls — the API layer stays untouched
because it only ever sees schemas and domain exceptions.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.pagination import Pagination
from app.schemas.product import ProductCreate, ProductRead


class ProductService:
    def __init__(self) -> None:
        self._items: dict[int, ProductRead] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._seed()

    def _seed(self) -> None:
        for name, price, tags in (
            ("Espresso machine", Decimal("499.99"), ["kitchen", "coffee"]),
            ("Ceramic mug", Decimal("14.50"), ["kitchen"]),
            ("Coffee beans 1kg", Decimal("24.00"), ["coffee", "consumable"]),
        ):
            product = ProductRead(
                id=self._next_id,
                name=name,
                description=None,
                price=price,
                currency="EUR",
                in_stock=True,
                tags=tags,
                created_at=datetime.now(UTC),
            )
            self._items[product.id] = product
            self._next_id += 1

    async def list_products(
        self,
        pagination: Pagination,
        *,
        search: str | None = None,
        in_stock: bool | None = None,
    ) -> tuple[list[ProductRead], int]:
        """Return a page of products and the total number of matches."""
        items = list(self._items.values())

        if search:
            needle = search.lower()
            items = [p for p in items if needle in p.name.lower()]
        if in_stock is not None:
            items = [p for p in items if p.in_stock is in_stock]

        items.sort(key=lambda p: p.id)
        return pagination.slice(items), len(items)

    async def get_product(self, product_id: int) -> ProductRead:
        product = self._items.get(product_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found")
        return product

    async def create_product(self, payload: ProductCreate) -> ProductRead:
        async with self._lock:
            if any(p.name.lower() == payload.name.lower() for p in self._items.values()):
                raise ConflictError(f"Product '{payload.name}' already exists")

            product = ProductRead(
                id=self._next_id,
                created_at=datetime.now(UTC),
                **payload.model_dump(),
            )
            self._items[product.id] = product
            self._next_id += 1
            return product


# One instance for the process lifetime; injected via app.api.deps.get_product_service.
product_service = ProductService()
