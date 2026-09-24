"""Admin API wiring.

Two routers on purpose:

- `admin_router` carries `Depends(get_current_admin)` at the router level, so anything
  mounted on it is protected without the author of a new route having to remember;
- `admin_public_router` is the single, explicitly named exception: the routes that mint
  a token, which cannot require one.

Wiring only: the routes live in `app/features/<name>/admin_router.py`.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin
from app.features.attributes.admin_router import category_router as category_attributes_router
from app.features.attributes.admin_router import router as attributes_router
from app.features.audit.router import router as audit_router
from app.features.brands.admin_router import router as brands_router
from app.features.catalog.admin_router import products_router, variants_router
from app.features.categories.admin_router import router as categories_router
from app.features.countries.admin_router import router as countries_router
from app.features.currencies.admin_router import router as currencies_router
from app.features.judge.admin_router import router as judge_router
from app.features.markets.admin_router import router as markets_router
from app.features.matching.admin_router import offers_router as match_offers_router
from app.features.matching.admin_router import queue_router as match_queue_router
from app.features.matching.admin_router import router as matching_router
from app.features.offers.admin_router import raw_router as raw_offers_router
from app.features.offers.admin_router import router as offers_router
from app.features.offers.admin_router import sources_router as source_offers_router
from app.features.pipeline.admin_router import router as pipeline_router
from app.features.prices.admin_router import availability_router
from app.features.prices.admin_router import router as prices_router
from app.features.runs.admin_router import router as runs_router
from app.features.runs.admin_router import scheduler_router
from app.features.runs.admin_router import sources_router as source_runs_router
from app.features.shops.admin_router import groups_router as shop_groups_router
from app.features.shops.admin_router import router as shops_router
from app.features.shops.admin_router import sources_router
from app.features.users.admin_router import auth_public_router, auth_router, users_router

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(get_current_admin)])
admin_router.include_router(users_router)
admin_router.include_router(auth_router)
admin_router.include_router(audit_router)
admin_router.include_router(currencies_router)
admin_router.include_router(countries_router)
admin_router.include_router(markets_router)
admin_router.include_router(categories_router)
admin_router.include_router(attributes_router)
admin_router.include_router(brands_router)
admin_router.include_router(products_router)
admin_router.include_router(variants_router)
admin_router.include_router(shop_groups_router)
admin_router.include_router(shops_router)
admin_router.include_router(sources_router)
admin_router.include_router(offers_router)
admin_router.include_router(source_offers_router)
admin_router.include_router(raw_offers_router)
admin_router.include_router(prices_router)
admin_router.include_router(availability_router)
admin_router.include_router(match_offers_router)
admin_router.include_router(matching_router)
admin_router.include_router(match_queue_router)
admin_router.include_router(judge_router)
admin_router.include_router(runs_router)
admin_router.include_router(source_runs_router)
admin_router.include_router(scheduler_router)
admin_router.include_router(pipeline_router)
admin_router.include_router(category_attributes_router)

# Sign-in cannot require a token. Keep this router to the routes that mint one.
admin_public_router = APIRouter(prefix="/admin")
admin_public_router.include_router(auth_public_router)
