"""Aggregates the client-facing /api routes.

Wiring only: every route itself lives in `app/features/<name>/router.py`. A new feature
is mounted here and nowhere else.
"""

from fastapi import APIRouter

from app.features.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(users_router)
