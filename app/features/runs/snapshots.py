"""The bytes a shop served, kept on the worker's own disk.

Not in the database. The volume is wrong for it — a catalogue's worth of pages is
gigabytes of HTML that nothing queries — and the thing that needs them is the worker,
which is also the thing that can re-run a parser over them without a network.

Two areas, and the second is the one that gets used most:

- `<source>/<external_id>.json.gz` — the last snapshot of a product, overwritten each time.
  Only the last, because the question is always "what does the site serve now", not "what
  did it serve in March".
- `failed/<source>/<external_id>.json.gz` — snapshots whose parse raised. Kept apart so a
  parser can be fixed against the exact bytes that broke it, which is the difference
  between a five-minute fix and a re-crawl.
"""

import gzip
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.features.runs.channel import Part, Snapshot

log = logging.getLogger(__name__)

# Shop identifiers arrive from outside and end up in a path. Anything that is not plainly
# safe becomes an underscore, so `../../etc/passwd` is a filename and not a traversal.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


class SnapshotStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.snapshot_dir)

    def save(self, source_slug: str, snapshot: Snapshot, *, failed: bool = False) -> Path:
        path = self._path(source_slug, snapshot.external_id, failed=failed)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "external_id": snapshot.external_id,
            "fetched_at": snapshot.fetched_at.isoformat(),
            "parts": [
                {"role": p.role, "url": p.url, "status": p.status, "body": p.body}
                for p in snapshot.parts
            ],
        }
        path.write_bytes(gzip.compress(json.dumps(document).encode()))
        return path

    def load(self, source_slug: str, external_id: str, *, failed: bool = False) -> Snapshot | None:
        path = self._path(source_slug, external_id, failed=failed)
        if not path.exists():
            return None
        document = json.loads(gzip.decompress(path.read_bytes()))
        return Snapshot(
            external_id=document["external_id"],
            fetched_at=datetime.fromisoformat(document["fetched_at"]).astimezone(UTC),
            parts=[Part(**part) for part in document["parts"]],
        )

    def stored(self, source_slug: str, *, failed: bool = False) -> list[str]:
        """Which products this channel has bytes for — what a re-parse would work through."""
        directory = self._directory(source_slug, failed=failed)
        if not directory.exists():
            return []
        return sorted(p.name[: -len(".json.gz")] for p in directory.glob("*.json.gz"))

    def forget_failure(self, source_slug: str, external_id: str) -> None:
        """A product that parsed this time is no longer a broken example."""
        self._path(source_slug, external_id, failed=True).unlink(missing_ok=True)

    # --- paths ---

    def _directory(self, source_slug: str, *, failed: bool) -> Path:
        base = self.root / "failed" if failed else self.root
        return base / _safe(source_slug)

    def _path(self, source_slug: str, external_id: str, *, failed: bool) -> Path:
        return self._directory(source_slug, failed=failed) / f"{_safe(external_id)}.json.gz"


def _safe(value: str) -> str:
    cleaned = _UNSAFE.sub("_", value).strip("._") or "unnamed"
    # Long enough for any real identifier, short enough for every filesystem.
    return cleaned[:180]
