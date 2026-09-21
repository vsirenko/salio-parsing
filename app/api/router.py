"""Aggregates the client-facing /api routes. Add new resource routers here."""

from fastapi import APIRouter

from app.api.routes import auth, products

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(products.router)
