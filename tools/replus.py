"""Repair the catalogue after `normalize_model` learned that `+` is part of a model.

    .venv/bin/python -m tools.replus --dry-run
    .venv/bin/python -m tools.replus

The form used to drop the `+`, so `Galaxy S26+` and `Galaxy S26` were one `model_normalized`.
Two things followed, and this undoes both, in this order:

1. **Every stored form is recomputed**, `variants.model_normalized` and
   `variant_mpns.mpn_normalized`, and with them the identity keys. `Galaxy S25+` now reads
   as `Galaxy S25 Plus` does, so where the catalogue held both at the same capacity and
   colour, the recomputed key is taken and the two are merged — the `+` entry into the one
   already holding the key, which is the one spelled out.

2. **Listings filed under the other phone are moved.** The model rung matched a `Galaxy
   S26+` listing to a `Galaxy S26` entry, the entry learned the listing's barcode, and from
   then on every listing carrying that barcode found the entry by the strongest signal
   there is. Measured on 22.09.2026: 111 live matches on 40 entries disagreed with their
   entry about the plus and about nothing else, 70 of them held by a barcode.

   The entry's own name does not decide who is right. Several entries are named after the
   minority of their listings — `v25224 Galaxy S26` holds ten listings reading `Galaxy
   S26+` and three reading `Galaxy S26` — because the name came from whichever listing
   arrived first. What decides is each identifier: a barcode names one phone, and the
   listings carrying it vote on which. An identifier whose voters mostly name the other
   phone is taken off the entry, whatever its origin, and each disagreeing listing is
   matched again from scratch. One that finds nothing is promoted into an entry of its own,
   exactly as the queue would do it.

   A listing whose identifier votes for its entry stays, even when its own model disagrees:
   the barcode says what the thing is, and the shop's name is the minority.

`--dry-run` does all of it inside one transaction and rolls it back, so the report is what a
real run would do rather than an estimate of it. Matches a person or the judge decided are
left alone and listed.
"""

import argparse
import asyncio
from collections import Counter, defaultdict

from sqlalchemy import delete, select, text

from app.core.exceptions import AppError, ConflictError
from app.db.models import Offer, Variant, VariantGtin, VariantMpn
from app.db.session import session_factory
from app.features.catalog.identity import normalize_model
from app.features.catalog.schemas import ProductUpdate, VariantUpdate
from app.features.catalog.service import CatalogService
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService
from app.features.offers.normalization import naming

# Every live match with the newest reading of its listing from a pass that carried the
# catalogue — the rule `MatchingService._reading` applies, repeated here for the whole
# table at once.
LIVE = """
    select m.offer_id, m.variant_id, m.decided_by, v.model as entry_model,
           b.canonical_name as brand, n.model, n.gtin, n.mpn
    from offer_matches m
    join variants v on v.id = m.variant_id
    join brands b on b.id = v.brand_id
    join lateral (
        select n.model, n.gtin, n.mpn
        from raw_offers r
        join normalized_offers n on n.raw_offer_id = r.id
        left join runs ru on ru.id = r.run_id
        where r.offer_id = m.offer_id and (ru.kind is null or ru.kind <> 'quick')
        order by r.fetched_at desc, n.id desc
        limit 1
    ) n on true
    where m.superseded_at is null
"""


def form(model: str, brand: str) -> str:
    return normalize_model(naming.without_brand(model, brand))


def family(normalized: str) -> str:
    """What two forms share when they differ only by the plus — and by a `5G` suffix,
    which shops add and drop at will and which is not what this repairs."""
    return normalized.replace("plus", "").replace("5g", "")


def is_plus(normalized: str) -> bool:
    return "plus" in normalized


def plus_side(model: str, brand: str) -> tuple[str, bool]:
    """The line a model belongs to, and which side of the plus it is on."""
    normalized = form(model, brand)
    return family(normalized), is_plus(normalized)


async def rekey(session, catalog: CatalogService) -> Counter:
    report: Counter = Counter()

    # Part numbers first: nothing hangs off them, and the rung reads them by this form.
    for variant_id, stored, raw in (
        await session.execute(
            select(VariantMpn.variant_id, VariantMpn.mpn_normalized, VariantMpn.mpn_raw)
        )
    ).all():
        fresh = normalize_model(raw)
        if fresh == stored:
            continue
        held = await session.scalar(
            select(VariantMpn.variant_id).where(
                VariantMpn.variant_id == variant_id, VariantMpn.mpn_normalized == fresh
            )
        )
        if held is not None:
            # The entry already holds the spelled-out form: the two rows are one.
            await session.execute(
                delete(VariantMpn).where(
                    VariantMpn.variant_id == variant_id, VariantMpn.mpn_normalized == stored
                )
            )
            report["mpn duplicates dropped"] += 1
        else:
            await session.execute(
                text(
                    "update variant_mpns set mpn_normalized = :fresh"
                    " where variant_id = :v and mpn_normalized = :stored"
                ),
                {"fresh": fresh, "v": variant_id, "stored": stored},
            )
            report["mpns rekeyed"] += 1

    stale = [
        (variant_id, model)
        for variant_id, model, stored in (
            await session.execute(select(Variant.id, Variant.model, Variant.model_normalized))
        ).all()
        if normalize_model(model) != stored
    ]
    for variant_id, model in stale:
        try:
            async with session.begin_nested():
                # The same model: `update_variant` recomputes the form and the key from it.
                await catalog.update_variant(variant_id, VariantUpdate(model=model))
            report["entries rekeyed"] += 1
        except ConflictError as error:
            twin = (error.details or {}).get("variant_id")
            if twin is None:
                report[f"rekey refused: {error.code}"] += 1
                continue
            try:
                async with session.begin_nested():
                    survivor = await catalog.merge_variants(
                        variant_id,
                        twin,
                        reason=f"{model!r} keys as this entry does once a + reads as Plus",
                        decided_by="rule",
                    )
                report["entries merged into their spelled-out twin"] += 1
                print(f"  merge  v{variant_id} {model!r} -> v{twin} {survivor.model!r}")
            except AppError as failure:
                report[f"merge refused: {failure.code}"] += 1
    return report


async def untangle(session, matching: MatchingService, side=plus_side) -> Counter:
    """Move the listings whose entry is another phone of the same line.

    `side` says what a line and a phone are: it maps a model to the line it belongs to and
    to what tells phones of that line apart — here the plus, in `tools.resibling` any
    variant word. Two models disagree when their line is the same and that is not.
    """
    report: Counter = Counter()
    rows = (await session.execute(text(LIVE))).mappings().all()

    on_entry: dict[int, list] = defaultdict(list)
    carrying_gtin: dict[str, list] = defaultdict(list)
    carrying_mpn: dict[str, list] = defaultdict(list)
    for row in rows:
        on_entry[row["variant_id"]].append(row)
        if row["gtin"]:
            carrying_gtin[row["gtin"]].append(row)
        if row["mpn"]:
            carrying_mpn[normalize_model(row["mpn"])].append(row)

    def disagrees(row, entry: tuple) -> bool:
        if not row["model"]:
            return False
        line, phone = side(row["model"], row["brand"])
        return line == entry[0] and phone != entry[1]

    def votes_against(carriers: list, entry: tuple) -> bool:
        """Whether the listings carrying an identifier mostly name the other phone."""
        sides = [side(row["model"], row["brand"]) for row in carriers if row["model"]]
        tally = Counter(phone == entry[1] for line, phone in sides if line == entry[0])
        return tally[False] > tally[True]

    to_redecide: list[tuple[int, int]] = []
    for variant_id, listings in on_entry.items():
        entry_form = side(listings[0]["entry_model"], listings[0]["brand"])
        wrong = [row for row in listings if disagrees(row, entry_form)]
        if not wrong:
            continue
        report["entries holding the other phone"] += 1

        for gtin in (
            await session.scalars(
                select(VariantGtin.gtin).where(VariantGtin.variant_id == variant_id)
            )
        ).all():
            if votes_against(carrying_gtin.get(gtin, []), entry_form):
                await session.execute(
                    delete(VariantGtin).where(
                        VariantGtin.variant_id == variant_id, VariantGtin.gtin == gtin
                    )
                )
                report["barcodes taken off"] += 1
        for mpn in (
            await session.scalars(
                select(VariantMpn.mpn_normalized).where(VariantMpn.variant_id == variant_id)
            )
        ).all():
            if votes_against(carrying_mpn.get(mpn, []), entry_form):
                await session.execute(
                    delete(VariantMpn).where(
                        VariantMpn.variant_id == variant_id, VariantMpn.mpn_normalized == mpn
                    )
                )
                report["part numbers taken off"] += 1

        for row in wrong:
            if row["decided_by"] != "rule":
                report[f"left alone: decided by {row['decided_by']}"] += 1
                print(f"  keep   offer {row['offer_id']} on v{variant_id}: {row['decided_by']}")
                continue
            to_redecide.append((row["offer_id"], variant_id))

    await session.flush()
    for offer_id, was in to_redecide:
        offer = await session.get(Offer, offer_id)
        reading = await matching._reading(offer_id)
        async with session.begin_nested():
            # The old match goes first. A decision that links replaces it anyway, but one
            # that queues does not, and the first real run left two listings standing on
            # the entry they had just been judged not to be.
            await matching._supersede(offer_id)
            await matching._carry_variant_into_history(offer_id, None)
            outcome = await matching._decide(offer, reading)
        if outcome.matched and outcome.variant_id == was:
            report["stayed: its identifier votes for the entry"] += 1
            print(
                f"  stay   offer {offer_id} on v{was} ({reading.model!r}) by {outcome.method.value}"
            )
            continue
        if outcome.matched:
            report["moved to another entry"] += 1
            print(f"  move   offer {offer_id} v{was} -> v{outcome.variant_id} ({reading.model!r})")
            continue
        refusal = await matching._why_not_promotable(offer, reading)
        if refusal is None:
            try:
                async with session.begin_nested():
                    outcome = await matching.promote(offer_id)
                report["promoted into an entry of its own"] += 1
                print(
                    f"  new    offer {offer_id} v{was} -> v{outcome.variant_id} ({reading.model!r})"
                )
                continue
            except AppError as error:
                refusal = error.code
        report[f"queued: {outcome.reason.value if outcome.reason else refusal}"] += 1
        print(f"  queue  offer {offer_id} off v{was} ({reading.model!r}): {refusal}")
    return report


async def main(*, dry_run: bool) -> None:
    async with session_factory() as session:
        catalog = CatalogService(session)
        matching = MatchingService(session, judge=JudgeService(session))

        print("rekey")
        rekeyed = await rekey(session, catalog)
        print("untangle")
        untangled = await untangle(session, matching)

        # Merges empty families, and an empty family is a name with no prices on the
        # storefront. The same clean-up the rebuild pass ends with.
        hidden = 0
        for product_id in await matching._empty_families(limit=10_000):
            await catalog.update_product(product_id, ProductUpdate(is_visible=False))
            hidden += 1

        for label, report in (("rekey", rekeyed), ("untangle", untangled)):
            print(f"\n{label}:")
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
