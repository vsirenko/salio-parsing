"""Per-request audit context.

The middleware opens a context at the start of an admin request; dependencies and
services enrich it while the request runs; the middleware writes the finished record.
A ContextVar is used because services have no access to the request object and
threading an audit parameter through every call signature would be worse.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# Defence in depth: callers are expected to pass clean data, this makes sure a
# secret never reaches the audit store even if one slips through.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
    }
)
REDACTED = "[redacted]"


@dataclass
class AuditContext:
    request_id: str
    actor_id: int | None = None
    actor_email: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    changes: dict[str, Any] = field(default_factory=dict)


_audit_context: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """Replace sensitive values, recursing into nested dicts and lists."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            clean[key] = REDACTED
        elif isinstance(value, dict):
            clean[key] = redact(value)
        elif isinstance(value, list):
            clean[key] = [redact(v) if isinstance(v, dict) else v for v in value]
        else:
            clean[key] = value
    return clean


def open_context(request_id: str) -> AuditContext:
    """Called by the middleware only.

    Starlette runs the endpoint in a child task, which inherits a *copy* of the
    context mapping. That copy points at the same AuditContext object, so the helpers
    below mutate an object the middleware can still read afterwards. Re-binding the
    ContextVar downstream would not propagate back — which is why nothing except this
    function ever calls .set().
    """
    context = AuditContext(request_id=request_id)
    _audit_context.set(context)
    return context


def current_context() -> AuditContext | None:
    """None outside an audited request — every helper below is then a no-op."""
    return _audit_context.get()


def set_actor(*, actor_id: int | None = None, email: str | None = None) -> None:
    context = current_context()
    if context is None:
        return
    if actor_id is not None:
        context.actor_id = actor_id
    if email is not None:
        context.actor_email = email


def set_target(target_type: str, target_id: object) -> None:
    context = current_context()
    if context is None:
        return
    context.target_type = target_type
    context.target_id = str(target_id)


def record_changes(**changes: Any) -> None:
    context = current_context()
    if context is None:
        return
    context.changes.update(redact(changes))
