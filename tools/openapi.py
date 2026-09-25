"""Write the API's OpenAPI schema to `docs/openapi.json`.

    .venv/bin/python -m tools.openapi

The schema is what a front end is built against, and the file is how a change to it shows
up in a review: `tests/test_openapi.py` fails while the file and the code disagree. The live
one is `/openapi.json` on a running api.
"""

import json
from pathlib import Path

from app.core.config import Settings
from app.main import app

OUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def render() -> str:
    """The schema as the code states it, whatever `.env` the machine has.

    The title and the version come from the settings, and a laptop's `.env` named the app
    `Products API` where the code and CI say `salio-parsing`: the file generated on one
    failed the check on the other. The code's own defaults are what is committed —
    `app_version` is the one `cz bump` keeps in step with the release.
    """
    schema = app.openapi()
    schema["info"] = {
        **schema["info"],
        "title": Settings.model_fields["app_name"].default,
        "version": Settings.model_fields["app_version"].default,
    }
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(OUT)
