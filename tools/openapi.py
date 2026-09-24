"""Write the API's OpenAPI schema to `docs/openapi.json`.

    .venv/bin/python -m tools.openapi

The schema is what a front end is built against, and the file is how a change to it shows
up in a review: `tests/test_openapi.py` fails while the file and the code disagree. The live
one is `/openapi.json` on a running api.
"""

import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(OUT)
