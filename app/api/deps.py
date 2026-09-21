"""Shared FastAPI dependencies."""

from app.services.products import ProductService, product_service


def get_product_service() -> ProductService:
    """Indirection kept on purpose: tests override this to inject a fresh service."""
    return product_service
