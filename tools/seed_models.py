"""Seed the model registry from the shops that read cleanly.

    .venv/bin/python -m tools.seed_models --dry-run
    .venv/bin/python -m tools.seed_models

The registry cannot be derived from the catalogue it is meant to clean: 211 of its 1524
entries are named after a spec sheet, and `Galaxy S26 S942 5G Dual Sim` sits in the title
too — as the longest known name it would win. So the seed is read off the readings of the
shops whose model rules leave nothing behind. Measured on 22.09.2026, the share of models
still carrying a spec token was 0 or 1 in a thousand on these eight, against 42% on bm and
14% on m79, and those two are exactly the shops the registry is for.

Every distinct spelling a clean shop reads becomes an alias of itself, `origin='rule'`, so
a row this wrote can be told from one a person entered and removed as a set. Nothing is
collapsed: `Galaxy S26 Ultra 5G` and `Galaxy S26 Ultra` stay two names here, because the
same suffix is a real difference one line over — Samsung sells a `Galaxy A16` and a
`Galaxy A16 5G` as separate phones. Making one an alias of the other is a decision, and a
decision is entered by hand.

Registry work moves no ruleset version. Follow this with a reparse.
"""

import argparse
import asyncio
import re
from collections import Counter, defaultdict

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.db.models import ModelAlias
from app.db.session import session_factory
from app.features.brands.normalization import (
    _NOT_MODEL_WORD,
    LONGEST_MODEL_NAME,
    normalize_brand,
    normalize_model_name,
)

# The eight whose model rules read cleanly. A source, not a shop: the rules are the
# source's, and a shop's other categories are other sources.
CLEAN = (
    "cec-phones",
    "dateks-phones",
    "euronics-phones",
    "ksenukai-phones",
    "mdata-phones",
    "onea-phones",
    "rdveikals-phones",
    "tet-phones",
)

# The newest reading of each listing from a pass that carried the catalogue — the same
# rule the matcher and the preview use. A cheap pass reads a price and no model. The
# newest *reading* of that pass, not any: a raw row keeps one reading per ruleset version,
# and the one from before a shop had a model rule reads none.
READINGS = """
    select n.brand_raw, n.model
    from offers o
    join lateral (
        select n.brand_raw, n.model
        from raw_offers r
        join normalized_offers n on n.raw_offer_id = r.id
        left join runs ru on ru.id = r.run_id
        join sources src on src.id = r.source_id
        where r.offer_id = o.id and (ru.kind is null or ru.kind <> 'quick')
          and src.slug = any(:sources)
        order by r.fetched_at desc, r.id desc, n.id desc
        limit 1
    ) n on true
    where n.model is not null and n.brand_raw is not null
"""

MAKERS = """
    select b.id, b.canonical_name, a.alias_normalized
    from brands b
    left join brand_aliases a on a.brand_id = b.id
"""

# Every one-word spelling of a colour the registry knows. A clean shop is clean about
# the model and not always about what follows it: tet leaves the colour on 24 of 316 and
# rdveikals on 31 of 1257 — `105 (2024) Black`. As an alias that spelling would be the
# longest known name in its own titles and keep that shop from meeting the others.
COLOURS = """
    select va.alias_normalized
    from attribute_value_aliases va
    join attributes a on a.id = va.attribute_id
    where a.key = 'color' and va.alias_normalized not like '% %'
"""

# Samsung's model code without its `SM-` — `A576B`, `F966B`, `S938B`. rdveikals writes it
# in front of the name on 221 of its 1257 phones, `A576B Galaxy A57`, and as an alias it
# would beat the `Galaxy A57` inside it. The code is a part number, and the reader has a
# place for those; it is not a name.
SAMSUNG_CODE = re.compile(r"^[a-z]\d{3}[a-z]{1,2}$")
# What a shop calls the kind of thing, left on the name: mdata on 25 of 98, dateks on 2.
KIND_WORDS = re.compile(r"^mobile phone\b|\bsmartphone$")


async def main(*, dry_run: bool, sources: tuple[str, ...]) -> None:
    async with session_factory() as session:
        # Every spelling a maker is known by, to the maker. Two makers sharing a spelling
        # is a question the category settles, not this; such a listing is skipped.
        makers: dict[str, set[int]] = defaultdict(set)
        names: dict[int, str] = {}
        for brand_id, canonical, alias in (await session.execute(text(MAKERS))).all():
            names[brand_id] = canonical
            makers[normalize_brand(canonical)].add(brand_id)
            if alias:
                makers[alias].add(brand_id)

        colours = set((await session.scalars(text(COLOURS))).all())
        rows = (await session.execute(text(READINGS), {"sources": list(sources)})).all()

        # (maker, spelling as looked up) -> how often each raw spelling was read.
        spellings: dict[tuple[int, str], Counter[str]] = defaultdict(Counter)
        skipped: Counter[str] = Counter()
        repaired: Counter[str] = Counter()
        left_out: dict[str, set[str]] = defaultdict(set)
        for brand_raw, model in rows:
            try:
                found = makers.get(normalize_brand(brand_raw), set())
            except ValueError:
                found = set()
            if len(found) != 1:
                skipped["maker unknown or ambiguous"] += 1
                continue
            try:
                key = normalize_model_name(model)
            except ValueError:
                skipped["model normalizes to nothing"] += 1
                continue
            words, spelling, taken = _repaired(key.split(), model.strip(), colours)
            for reason in taken:
                repaired[reason] += 1
            reason = _not_a_name(words)
            if reason:
                skipped[reason] += 1
                left_out[reason].add(f"{names[next(iter(found))]} {model.strip()}")
                continue
            spellings[(next(iter(found)), " ".join(words))][spelling] += 1

        written = 0
        per_maker: Counter[str] = Counter()
        for (brand_id, key), seen in sorted(spellings.items()):
            # The most-read spelling is the catalogue's; ties go to the shorter, then
            # alphabetical, so the choice is the same on every run.
            by_use = sorted(seen.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
            canonical = by_use[0][0]
            per_maker[names[brand_id]] += 1
            if dry_run:
                print(f"{names[brand_id]:<14} {key:<40} -> {canonical}   ({sum(seen.values())})")
                continue
            result = await session.execute(
                insert(ModelAlias)
                .values(brand_id=brand_id, alias_normalized=key, model=canonical, origin="rule")
                .on_conflict_do_nothing(constraint="uq_model_alias_per_brand")
            )
            written += result.rowcount
        if not dry_run:
            await session.commit()

    print()
    print(f"readings: {len(rows)}   names: {len(spellings)}   written: {written}")
    for reason, count in repaired.most_common():
        print(f"repaired, {reason}: {count} readings")
    for reason, count in skipped.most_common():
        print(f"skipped, {reason}: {count} readings, {len(left_out[reason])} spellings")
        if dry_run:
            print("    " + ", ".join(sorted(left_out[reason])))
    print()
    for maker, count in per_maker.most_common():
        print(f"{maker:<14} {count}")


def _repaired(
    words: list[str], spelling: str, colours: set[str]
) -> tuple[list[str], str, list[str]]:
    """A clean shop's spelling with what is not the name taken off, and what was taken.

    Taken off rather than thrown away with the name inside it: `A576B Galaxy A57` holds
    the only `Galaxy A57` nine readings know, and skipping it whole left the dirty shops'
    `Galaxy A57 A576 5G Dual Sim` with nothing to be found in it. The raw spelling is cut
    the same way, token for token, so the catalogue's name keeps the shop's case.
    """
    raw = [token for token in spelling.split() if _NOT_MODEL_WORD.sub("", token.casefold())]
    taken: list[str] = []
    while True:
        if len(words) > 1 and SAMSUNG_CODE.match(words[0]):
            cut, reason = (1, None), "a part number in front of the name"
        elif len(words) > 2 and words[:2] == ["mobile", "phone"]:
            cut, reason = (2, None), "the kind of thing in front of the name"
        elif len(words) > 1 and words[-1] == "smartphone":
            cut, reason = (0, -1), "the kind of thing after the name"
        elif len(words) > 1 and words[-1] in colours:
            cut, reason = (0, -1), "a colour after the name"
        elif len(words) > 2 and words[-1].isdigit() and words[-2].isdigit():
            cut, reason = (0, -2), "a capacity pair after the name"
        else:
            break
        if len(raw) != len(words):
            # A raw token that normalizes to two words — `Dual-SIM` — breaks the alignment,
            # and a canonical spelling guessed at is worse than the spelling left as it is.
            break
        words, raw = words[cut[0] : cut[1]], raw[cut[0] : cut[1]]
        taken.append(reason)
    return words, (" ".join(raw) if len(raw) == len(words) else spelling), taken


def _not_a_name(words: list[str]) -> str | None:
    """Why a spelling, repaired or not, is still not a name to find in a title."""
    if len(words) > LONGEST_MODEL_NAME:
        return f"longer than {LONGEST_MODEL_NAME} words"
    # A one- or two-digit number alone is `Xiaomi 15` and also `Android 15`, and an alias
    # of one meets both; three digits and more — `Nokia 3210`, `Honor 600` — meet nothing
    # else a title carries. The short ones are entered by hand, with that in mind.
    if len(words) == 1 and words[0].isdigit() and len(words[0]) < 3:
        return "a number of one or two digits"
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print what would be written")
    parser.add_argument("--sources", nargs="*", default=CLEAN, help="source slugs to read from")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, sources=tuple(args.sources)))
