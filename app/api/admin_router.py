"""Admin API.

Two routers on purpose:

- `admin_router` carries `Depends(get_current_admin)` at the router level, so anything
  mounted on it is protected without the author of a new route having to remember;
- `admin_public_router` is the single, explicitly named exception for sign-in.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin
from app.api.routes.admin import audit as admin_audit
from app.api.routes.admin import auth as admin_auth
from app.api.routes.admin import users as admin_users

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(get_current_admin)])
admin_router.include_router(admin_users.router)
admin_router.include_router(admin_audit.router)

# Sign-in cannot require a token. Keep this router empty apart from /auth.
admin_public_router = APIRouter(prefix="/admin")
admin_public_router.include_router(admin_auth.router)
