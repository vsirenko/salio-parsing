"""Collector API wiring.

The third audience. A worker signs in like anyone else and reaches a different set of
routes, because the audience is the boundary rather than the table — a worker token is
refused by the admin panel before any role check runs.

Two routers, for the same reason the admin side has two: signing in cannot require a
token. Wiring only; the routes live in `app/features/<name>/worker_router.py`.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_worker
from app.features.offers.worker_router import router as offers_router
from app.features.runs.worker_router import router as runs_router
from app.features.users.worker_router import auth_public_router

worker_router = APIRouter(prefix="/worker", dependencies=[Depends(get_current_worker)])
worker_router.include_router(runs_router)
worker_router.include_router(offers_router)

worker_public_router = APIRouter(prefix="/worker")
worker_public_router.include_router(auth_public_router)
