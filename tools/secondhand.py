"""Mark mdata's second-hand listings as what they are, and take them off new products.

    .venv/bin/python -m tools.secondhand --dry-run
    .venv/bin/python -m tools.secondhand

On 24.09.2026 mdata's channel was found to read the condition off the name, and the name did
not say it: all 20 tablets were `Stāvoklis: Renew (Atjaunots)` on their pages and 8
`Galaxy S23 FE` phones `Stāvoklis: Demo`. The channel refuses them now, but the listings it
had already handed over were still `new`, and 18 stood on catalogue entries.

This reads each of mdata's stored product pages with the channel's own `_condition`, writes
the condition — `Renew` is refurbished, `Demo` a used unit off the shop floor — takes each
one off its entry, out of the queue, and hides the families left with nothing in them. The
matcher places only new listings, so they stay off. `--dry-run` rolls it all back.
"""

import argparse
import asyncio

from sqlalchemy import delete, select

from app.db.models import MatchQueue, Offer, OfferMatch, Product, RawOffer, Source, Variant
from app.db.session import session_factory
from app.features.catalog.schemas import ProductUpdate, VariantUpdate
from app.features.catalog.service import CatalogService
from app.features.judge.service import JudgeService
from app.features.matching.service import MatchingService
from app.features.runs.channel import Snapshot
from app.features.runs.channels.mdata import _condition
from app.features.runs.snapshots import SnapshotStore

SOURCES = ("mdata-phones", "mdata-tablets")


def condition_of(stated: str) -> str | None:
    word = stated.casefold()
    if "renew" in word or "atjaunot" in word:
        return "refurbished"
    if "demo" in word:
        return "used"
    return None


async def main(*, dry_run: bool) -> None:
    store = SnapshotStore()
    async with session_factory() as session:
        matching = MatchingService(session, judge=JudgeService(session))
        catalog = CatalogService(session)
        rows = (
            await session.execute(
                select(Offer, Source.slug)
                .join(RawOffer, RawOffer.offer_id == Offer.id)
                .join(Source, Source.id == RawOffer.source_id)
                .where(Source.slug.in_(SOURCES))
                .distinct()
            )
        ).all()
        marked = unlinked = unqueued = 0
        left: set[int] = set()
        for offer, slug in rows:
            # A refused product's snapshot is kept among the failures.
            snapshot: Snapshot | None = store.load(slug, offer.external_id) or store.load(
                slug, offer.external_id, failed=True
            )
            page = snapshot.part("detail") if snapshot else None
            condition = condition_of(_condition(page.body)) if page else None
            if condition is None or offer.condition == condition:
                continue
            offer.condition = condition
            marked += 1
            active = await session.scalar(
                select(OfferMatch).where(
                    OfferMatch.offer_id == offer.id, OfferMatch.superseded_at.is_(None)
                )
            )
            if active is not None:
                await matching.unlink(offer.id)
                left.add(active.variant_id)
                unlinked += 1
            result = await session.execute(
                delete(MatchQueue).where(MatchQueue.offer_id == offer.id)
            )
            unqueued += result.rowcount or 0
            print(f"  {slug:14} {offer.external_id:>8}  offer {offer.id}  {condition}")
        await session.flush()
        # An entry these listings made and nothing else stands on is not a product anybody
        # sells new; it is hidden, and so is a family with no visible entry left in it.
        hidden = families = 0
        touched: set[int] = set()
        for variant_id in sorted(left):
            standing = await session.scalar(
                select(OfferMatch.id).where(
                    OfferMatch.variant_id == variant_id, OfferMatch.superseded_at.is_(None)
                )
            )
            if standing is None:
                entry = await catalog.update_variant(variant_id, VariantUpdate(is_visible=False))
                if entry.product_id is not None:
                    touched.add(entry.product_id)
                hidden += 1
        await session.flush()
        empty = await session.scalars(
            select(Product.id).where(
                Product.id.in_(touched),
                Product.is_visible.is_(True),
                ~select(Variant.id)
                .where(Variant.product_id == Product.id, Variant.is_visible.is_(True))
                .exists(),
            )
        )
        for product_id in list(empty):
            await catalog.update_product(product_id, ProductUpdate(is_visible=False))
            families += 1
        print(
            f"\n  {marked} marked, {unlinked} unlinked, {unqueued} left the queue,"
            f" {hidden} entries and {families} families hidden"
        )
        if dry_run:
            await session.rollback()
            print("dry run: rolled back")
        else:
            await session.commit()
            print("committed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(dry_run=parser.parse_args().dry_run))
