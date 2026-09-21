## Audit trail
- Every `/api/admin` request is recorded by `AuditMiddleware`. Do not add per-route audit
  calls for the envelope — method, path, status, actor, address and duration are captured
  already.
- The envelope is not the meaning, and the meaning is not optional. Every service method
  behind an admin route that changes state — or refuses to — names what it acted on with
  `audit.set_target(...)` and what it changed with `audit.record_changes(...)` from
  `app/core/audit.py`. An admin action that leaves the trail reading only
  `PATCH /api/admin/users/4 → 409` is not finished.
- Call `set_target` as soon as the row is loaded, before the guards run. A refused
  attempt has to be recorded against the account it was aimed at, not at nothing.
- `record_changes` reports what was actually applied. A refusal applies nothing, so it
  records nothing — the status code already says it failed.
- Sign-in names the actor email before the password is checked. A failed admin sign-in
  is exactly what the trail is read for and it has no actor id to name.
- Everything handed to `record_changes` has to be JSON-safe — `model_dump(mode="json")`,
  not the plain dump. The column is JSONB, a `Decimal` makes the write fail, and the
  middleware swallows that failure: the only symptom is an action that returned 200 and
  left no record. This has already happened once.
- Never pass raw credentials in. `record_changes` redacts the keys in `SENSITIVE_KEYS`,
  but that is a safety net, not the contract; a new field that can carry a secret is
  added to that set as well.
- Only `open_context` may call `ContextVar.set`. Downstream code mutates the existing
  `AuditContext` object — re-binding the var inside the endpoint task would not propagate
  back to the middleware.
- The trail is append-only. Never add an endpoint or service method that updates or
  deletes an entry.
