"""Move listings filed under a sibling of the phone they are: `iPhone 16 Pro` on `iPhone 16`.

    .venv/bin/python -m tools.resibling --dry-run
    .venv/bin/python -m tools.resibling

`tools.replus` did this for the plus alone. The registry reader then turned out to do the
same with every variant word: it took the longest name it knew, so with `iphone 16 pro`
missing from the registry `Apple iPhone 16 Pro 1TB` read as `iPhone 16`, and the entry
learned the Pro's part number from it. `phones-10` stopped the reading; this moves what the
old reading had already filed.

Two models are siblings when, with the maker's variant words set aside — the ones
`models.VARIANT_WORDS` names, and a `+` read as `plus` — what is left is the same model, and
the variant words are not. `Pixel 9 Pro Fold` and `Pixel 9` are; `Galaxy Z Fold8` and
`Galaxy Fold8` are not (the `Z` is not a variant word, so the line differs and this leaves
them alone); `Galaxy S26 5G` and `Galaxy S26` are one phone, because `5G` is set aside too.

Everything after that is `tools.replus`: an identifier whose carriers mostly name the other
phone comes off the entry, each disagreeing listing is matched again from scratch, and one
that finds nothing is promoted. `--dry-run` runs it all and rolls it back.
"""

import argparse
import asyncio

from app.db.session import session_factory
from app.features.brands.normalization import normalize_model_name
from app.features.catalog.identity import normalize_model
from app.features.catalog.schemas import ProductUpdate
from app.features.catalog.service import CatalogService
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService
from app.features.offers.normalization import naming
from app.features.offers.normalization.models import VARIANT_WORDS
from tools.replus import untangle

# Shops add and drop these at will, and they tell no two phones apart here.
NOISE = frozenset({"5g", "4g", "lte", "dual", "sim", "ds"})


def sibling_side(model: str, brand: str) -> tuple[str, frozenset[str]]:
    """The line a model belongs to, and the variant words that make it one phone of it."""
    try:
        words = normalize_model_name(naming.without_brand(model, brand)).split()
    except ValueError:
        return model, frozenset()
    split: list[str] = []
    for word in words:
        # `s26+` is `s26` and a plus; `pro+` is `pro` and a plus.
        if word.endswith("+") and word != "+":
            split += [word.rstrip("+"), "plus"]
        else:
            split.append(word)
    variant = frozenset(word for word in split if word in VARIANT_WORDS)
    line = normalize_model(
        " ".join(word for word in split if word not in VARIANT_WORDS and word not in NOISE)
    )
    return line, variant


async def main(*, dry_run: bool) -> None:
    async with session_factory() as session:
        catalog = CatalogService(session)
        matching = MatchingService(session, judge=JudgeService(session))

        report = await untangle(session, matching, side=sibling_side)

        hidden = 0
        for product_id in await matching._empty_families(limit=10_000):
            await catalog.update_product(product_id, ProductUpdate(is_visible=False))
            hidden += 1

        print("\nuntangle:")
        for reason, count in sorted(report.items()):
            print(f"  {count:>5}  {reason}")
        print(f"\n  {hidden:>5}  empty families hidden")

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
