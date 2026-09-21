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
from app.features.audit.router import router as audit_router
from app.features.users.admin_router import auth_public_router, auth_router, users_router

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(get_current_admin)])
admin_router.include_router(users_router)
admin_router.include_router(auth_router)
admin_router.include_router(audit_router)

# Sign-in cannot require a token. Keep this router to the routes that mint one.
admin_public_router = APIRouter(prefix="/admin")
admin_public_router.include_router(auth_public_router)
