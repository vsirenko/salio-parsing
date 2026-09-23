"""Take the listings off an iPad entry that is another iPad of the same line.

    .venv/bin/python -m tools.retablet --dry-run
    .venv/bin/python -m tools.retablet

Before an iPad's model had to name its generation and its glass, the model rung filed
listings of one line under whichever entry of it came first. On 23.09.2026 the catalogue held
11 of bm's `iPad Air M4` part numbers and two of euronics' M4 barcodes on entries named
`iPad Air M3`, a 2022 `iPad 10th Gen` on the entry of the 2025 `iPad A16`, and rdveikals'
nano-texture iPad Pros on standard-glass entries. Every entry learned the listing's barcode,
and from then on every listing carrying it found the wrong iPad by the strongest signal there
is.

This is `tools.replus.untangle` with the line and the machine drawn for iPads: the line is
`iPad`, `iPad Air`, `iPad Pro` or `iPad mini`, the machine is the whole model. Each identifier
on an entry is judged by what the listings carrying it read, the ones voting for another iPad
come off, and each disagreeing listing is matched again from scratch. Nothing that is not an
iPad is touched: its line and its machine are the same string, so no two of them disagree.

Run it after the re-read, and after the rebuild pass has renamed the entries whose every
listing reads another name, so that what is left to untangle is a mixture and not a spelling.
`--dry-run` rolls it all back.
"""

import argparse
import asyncio
import re

from app.db.session import session_factory
from app.features.catalog.identity import normalize_model
from app.features.catalog.schemas import ProductUpdate
from app.features.catalog.service import CatalogService
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService
from tools.replus import untangle

_LINE = re.compile(r"^ipad\s*(air|pro|mini)?", re.IGNORECASE)


def ipad_side(model: str, brand: str) -> tuple[str, str]:
    """The line an iPad belongs to, and the machine; for anything else, the model twice."""
    form = normalize_model(model or "")
    found = _LINE.match((model or "").strip())
    if (brand or "").casefold() != "apple" or found is None:
        return form, form
    return "ipad" + (found.group(1) or "").lower(), form


async def main(*, dry_run: bool) -> None:
    async with session_factory() as session:
        catalog = CatalogService(session)
        matching = MatchingService(session, judge=JudgeService(session))
        report = await untangle(session, matching, side=ipad_side)
        hidden = 0
        for product_id in await matching._empty_families(limit=10_000):
            await catalog.update_product(product_id, ProductUpdate(is_visible=False))
            hidden += 1
        print()
        for reason, count in sorted(report.items()):
            print(f"  {count:>5}  {reason}")
        print(f"  {hidden:>5}  empty families hidden")
        if dry_run:
            await session.rollback()
            print("\ndry run: rolled back")
        else:
            await session.commit()
            print("\ncommitted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(dry_run=parser.parse_args().dry_run))
