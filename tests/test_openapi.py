"""The committed schema is the code's schema."""

from tools.openapi import OUT, render


def test_the_committed_schema_matches_the_code():
    """A front end is built against `docs/openapi.json`. Regenerate it with
    `.venv/bin/python -m tools.openapi` in the same commit as the change."""
    assert OUT.read_text(encoding="utf-8") == render(), (
        "docs/openapi.json is out of date: run `.venv/bin/python -m tools.openapi`"
    )
