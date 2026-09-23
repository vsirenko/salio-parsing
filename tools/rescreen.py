"""Move a tablet's screen out of its catalogue name and onto an axis.

    .venv/bin/python -m tools.rescreen --dry-run
    .venv/bin/python -m tools.rescreen

`tablets-4` wrote the screen onto the end of the model — `Galaxy Tab A11+ 11`, `iPad Air M4
13` — because two tablets that differ only in the screen are two products at two prices,
and nothing else kept them apart. The storefront then read `Samsung Galaxy Tab A11+ 11`,
which is a name no maker uses. `tablets-5` keeps the screen as an axis, `screen_inch`, in
whole inches, and the name is the maker's. A re-read moves the readings; this moves the
entries built from the old ones, in this order:

1. **`screen_inch` becomes identity-bearing for tablets**, so an entry's key carries it.
2. **Every tablet entry gets the axis before it loses the number.** Renaming first would
   make `iPad Air 11` and `iPad Air 13` one key and merge them. The value is what the
   entry's live listings now read, and where they disagree or say nothing, the number the
   old rule put at the end of the name — which is the same rounding of the same fields.
3. **The number comes off the name**, and an entry that becomes one that already exists —
   same model, same four axes — is merged into it, as the rebuild pass does.
4. **The entry moves to the family its new name makes**, and a family left empty is hidden.

`--dry-run` does it all in one transaction and rolls it back, so the report is what a real
run would do. Run it after the re-read, never before: it votes with the new readings.
"""

import argparse
import asyncio
from collections import Counter, defaultdict

from sqlalchemy import select, text

from app.core.exceptions import AppError, ConflictError
from app.db.models import Attribute, Category, Variant
from app.db.session import session_factory
from app.features.attributes.schemas import CategoryAttributeUpdate
from app.features.attributes.service import AttributeService
from app.features.catalog.schemas import ProductUpdate, VariantAttributeSet, VariantUpdate
from app.features.catalog.service import CatalogService
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService

CATEGORY = "tablets"
SCREEN = "screen_inch"

# What each live listing on a tablet entry now reads for the screen — the newest reading
# from a pass that carried the catalogue, the rule the matcher applies.
VOTES = """
    select m.variant_id, (n.identity ->> 'screen_inch')::int as inches
    from offer_matches m
    join variants v on v.id = m.variant_id
    join lateral (
        select n.identity
        from raw_offers r
        join normalized_offers n on n.raw_offer_id = r.id
        left join runs ru on ru.id = r.run_id
        where r.offer_id = m.offer_id and (ru.kind is null or ru.kind <> 'quick')
        order by r.fetched_at desc, n.id desc
        limit 1
    ) n on true
    where m.superseded_at is null and v.category_id = :category
      and n.identity ? 'screen_inch'
"""


def trailing_inches(model: str) -> int | None:
    last = model.rsplit(" ", 1)
    return int(last[1]) if len(last) == 2 and last[1].isdigit() else None


def without(model: str, inches: int) -> str:
    head, _, last = model.rpartition(" ")
    return head if head and last == str(inches) else model


async def main(*, dry_run: bool) -> None:
    async with session_factory() as session:
        catalog = CatalogService(session)
        matching = MatchingService(session, judge=JudgeService(session))
        report: Counter = Counter()

        category = await session.scalar(select(Category).where(Category.slug == CATEGORY))
        screen = await session.scalar(select(Attribute).where(Attribute.key == SCREEN))
        await AttributeService(session).update_link(
            category.id, screen.id, CategoryAttributeUpdate(identity_bearing=True)
        )

        votes: dict[int, Counter] = defaultdict(Counter)
        for variant_id, inches in (
            await session.execute(text(VOTES), {"category": category.id})
        ).all():
            votes[variant_id][inches] += 1

        entries = (
            await session.execute(
                select(Variant.id, Variant.model)
                .where(Variant.category_id == category.id)
                .order_by(Variant.id)
            )
        ).all()

        # 2. The axis first, on every entry, before any name changes.
        chosen: dict[int, int] = {}
        for variant_id, model in entries:
            said = votes.get(variant_id, Counter())
            named = trailing_inches(model)
            if len(said) == 1:
                inches = next(iter(said))
                report["axis from the listings"] += 1
                if named is not None and named != inches:
                    report["listings and the old name disagree; listings taken"] += 1
            elif named is not None and (not said or named in said):
                inches = named
                report["axis from the old name"] += 1
            else:
                report["no screen to give"] += 1
                continue
            try:
                async with session.begin_nested():
                    await catalog.set_variant_attribute(
                        variant_id, VariantAttributeSet(attribute_id=screen.id, value_num=inches)
                    )
                chosen[variant_id] = inches
            except ConflictError as error:
                # With its screen the entry is one that exists: the two were the same
                # tablet, kept apart only by an axis neither carried.
                twin = (error.details or {}).get("variant_id")
                if twin is None:
                    report[f"axis refused: {error.code}"] += 1
                    continue
                try:
                    async with session.begin_nested():
                        await catalog.merge_variants(
                            variant_id,
                            twin,
                            reason=f"the same tablet once its screen, {inches}, was an axis",
                            decided_by="rule",
                        )
                    report["merged once the axis was set"] += 1
                except AppError as failure:
                    report[f"merge refused: {failure.code}"] += 1
            except AppError as error:
                report[f"axis refused: {error.code}"] += 1

        # 3. The number off the name, merging where that makes an entry that exists.
        for variant_id, model in entries:
            inches = chosen.get(variant_id)
            if inches is None or await session.get(Variant, variant_id) is None:
                continue
            bare = without(model, inches)
            if bare == model:
                report["name had no number to take off"] += 1
                continue
            try:
                async with session.begin_nested():
                    await catalog.update_variant(variant_id, VariantUpdate(model=bare))
                report["renamed"] += 1
            except ConflictError as error:
                twin = (error.details or {}).get("variant_id")
                if twin is None:
                    report[f"rename refused: {error.code}"] += 1
                    continue
                try:
                    async with session.begin_nested():
                        await catalog.merge_variants(
                            variant_id,
                            twin,
                            reason=f"screen moved to an axis; {model!r} became {bare!r}",
                            decided_by="rule",
                        )
                    report["merged into an entry that existed"] += 1
                except AppError as failure:
                    report[f"merge refused: {failure.code}"] += 1

        # 4. Into the family the new name makes, and empty families out of sight.
        for (variant_id,) in (
            await session.execute(select(Variant.id).where(Variant.category_id == category.id))
        ).all():
            try:
                async with session.begin_nested():
                    report["moved to its family"] += await matching._rehome(catalog, variant_id)
            except AppError as error:
                report[f"move refused: {error.code}"] += 1
        for product_id in await matching._empty_families(limit=10_000):
            await catalog.update_product(product_id, ProductUpdate(is_visible=False))
            report["empty families hidden"] += 1

        for reason, count in sorted(report.items()):
            print(f"  {count:>5}  {reason}")
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
