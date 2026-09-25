"""Catalogue entries and families that look like one thing filed twice.

Every one of these was found by eye on 25.09.2026 — `Plus 16` beside `16 Plus`, a MacBook Air
at 13.0 and at 13.6, one part number on three entries — and each was the same few shapes.
This finds the shapes, so a person reads a queue with the evidence beside each item instead
of scrolling a list of families looking for them. It changes nothing: what to do about a
suspect is a registry row, a merge or a reading rule, and saying which is the person's call.
"""

import re
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Attribute,
    AttributeValue,
    Brand,
    Category,
    CategoryAttribute,
    OfferMatch,
    Product,
    Variant,
    VariantAttribute,
    VariantMpn,
)
from app.features.matching.schemas import (
    Suspect,
    SuspectEntry,
    SuspectKind,
    SuspectReport,
)

# Two readings of one number, not two products: a screen at 13.0 and 13.6, a disk at 1000 GB
# and 1 TB (1024000 and 1048576 MB, 2.3% apart). Two capacities or two screens that are
# really different are further apart than this — 256 and 512, 14 and 16.
NEAR = Decimal("0.05")
_WORD = re.compile(r"[0-9a-z]+")


async def find_suspects(
    session: AsyncSession,
    *,
    category_id: int | None = None,
    brand_id: int | None = None,
    kinds: list[SuspectKind] | None = None,
    limit: int = 100,
) -> SuspectReport:
    wanted = set(kinds or list(SuspectKind))
    entries = await _entries(session, category_id=category_id, brand_id=brand_id)
    found: list[Suspect] = []
    if SuspectKind.PART_NUMBER in wanted:
        found += await _one_part_number(session, entries)
    if SuspectKind.NEAR_VALUE in wanted:
        found += _near_values(entries)
    if SuspectKind.WORD_ORDER in wanted:
        found += await _word_order(session, category_id=category_id, brand_id=brand_id)
    counts: dict[str, int] = defaultdict(int)
    for suspect in found:
        counts[suspect.kind.value] += 1
    # The ones holding the most listings first: that is what a wrong split costs.
    found.sort(key=lambda s: -sum(e.offers_count for e in s.entries))
    return SuspectReport(total=len(found), by_kind=dict(counts), items=found[:limit])


async def _entries(
    session: AsyncSession, *, category_id: int | None, brand_id: int | None
) -> dict[int, dict[str, Any]]:
    """Every visible entry in scope, with its identity axes and how many listings it holds."""
    placed = (
        select(func.count())
        .select_from(OfferMatch)
        .where(OfferMatch.variant_id == Variant.id, OfferMatch.superseded_at.is_(None))
        .correlate(Variant)
        .scalar_subquery()
    )
    stmt = (
        select(Variant, Brand.canonical_name, Category.slug, placed.label("placed"))
        .join(Brand, Brand.id == Variant.brand_id)
        .join(Category, Category.id == Variant.category_id)
        .where(Variant.is_visible.is_(True))
    )
    if category_id is not None:
        stmt = stmt.where(Variant.category_id == category_id)
    if brand_id is not None:
        stmt = stmt.where(Variant.brand_id == brand_id)
    entries: dict[int, dict[str, Any]] = {}
    for variant, brand, category, count in (await session.execute(stmt)).all():
        entries[variant.id] = {
            "variant": variant,
            "brand": brand,
            "category": category,
            "offers": count or 0,
            "axes": {},
        }
    if not entries:
        return entries
    rows = await session.execute(
        select(
            VariantAttribute.variant_id,
            Attribute.key,
            VariantAttribute.value_num,
            AttributeValue.canonical,
        )
        .join(Attribute, Attribute.id == VariantAttribute.attribute_id)
        .join(Variant, Variant.id == VariantAttribute.variant_id)
        .join(
            CategoryAttribute,
            (CategoryAttribute.category_id == Variant.category_id)
            & (CategoryAttribute.attribute_id == Attribute.id)
            & CategoryAttribute.identity_bearing.is_(True),
        )
        .outerjoin(AttributeValue, AttributeValue.id == VariantAttribute.value_id)
        .where(VariantAttribute.variant_id.in_(list(entries)))
    )
    for variant_id, key, number, canonical in rows.all():
        value = number if number is not None else canonical
        if value is not None:
            entries[variant_id]["axes"][key] = value
    return entries


def _entry(entry: dict[str, Any]) -> SuspectEntry:
    variant = entry["variant"]
    return SuspectEntry(
        id=variant.id,
        product_id=variant.product_id,
        title=variant.title_override or variant.title,
        model=variant.model,
        offers_count=entry["offers"],
        axes={key: _shown(value) for key, value in sorted(entry["axes"].items())},
    )


def _shown(value: Any) -> str:
    return format(value.normalize(), "f") if isinstance(value, Decimal) else str(value)


def _differ(one: dict[str, Any], other: dict[str, Any]) -> list[str]:
    """The axes both hold and disagree on."""
    return sorted(key for key in one.keys() & other.keys() if one[key] != other[key])


async def _one_part_number(
    session: AsyncSession, entries: dict[int, dict[str, Any]]
) -> list[Suspect]:
    """A part number on several entries of one maker that agree on every axis they share."""
    if not entries:
        return []
    rows = await session.execute(
        select(
            VariantMpn.brand_id,
            func.min(VariantMpn.mpn_raw),
            func.array_agg(VariantMpn.variant_id),
        )
        .where(VariantMpn.variant_id.in_(list(entries)))
        .group_by(VariantMpn.brand_id, VariantMpn.mpn_normalized)
        .having(func.count(func.distinct(VariantMpn.variant_id)) > 1)
    )
    found: list[Suspect] = []
    for _, mpn, variant_ids in rows.all():
        held = [entries[v] for v in sorted(set(variant_ids)) if v in entries]
        if len(held) < 2:
            continue
        # A part number shared by entries that differ — two colours of one Samsung family —
        # is a family's number, not a product written twice.
        if any(_differ(a["axes"], b["axes"]) for a, b in combinations(held, 2)):
            continue
        found.append(
            Suspect(
                kind=SuspectKind.PART_NUMBER,
                action="merge",
                brand=held[0]["brand"],
                category=held[0]["category"],
                detail=f"{len(held)} entries hold {mpn} and agree on every axis they share",
                evidence=mpn,
                entries=[_entry(e) for e in held],
            )
        )
    return found


def _near_values(entries: dict[int, dict[str, Any]]) -> list[Suspect]:
    """Two entries of one model that differ in one number, and by very little."""
    groups: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in entries.values():
        variant = entry["variant"]
        groups[(variant.brand_id, variant.category_id, variant.model_normalized)].append(entry)
    found: list[Suspect] = []
    for group in groups.values():
        for a, b in combinations(group, 2):
            if a["axes"].keys() != b["axes"].keys():
                continue
            differ = _differ(a["axes"], b["axes"])
            if len(differ) != 1:
                continue
            key = differ[0]
            one, other = a["axes"][key], b["axes"][key]
            if not (isinstance(one, Decimal) and isinstance(other, Decimal)):
                continue
            if abs(one - other) > NEAR * max(abs(one), abs(other)):
                continue
            found.append(
                Suspect(
                    kind=SuspectKind.NEAR_VALUE,
                    action="axis",
                    brand=a["brand"],
                    category=a["category"],
                    detail=f"the same but for {key}: {_shown(one)} and {_shown(other)}",
                    evidence=key,
                    entries=[_entry(a), _entry(b)],
                )
            )
    return found


async def _word_order(
    session: AsyncSession, *, category_id: int | None, brand_id: int | None
) -> list[Suspect]:
    """Families of one maker whose names are the same words in another order or case."""
    held = (
        select(func.count())
        .select_from(Variant)
        .where(Variant.product_id == Product.id)
        .correlate(Product)
        .scalar_subquery()
    )
    placed = (
        select(func.count())
        .select_from(OfferMatch)
        .join(Variant, Variant.id == OfferMatch.variant_id)
        .where(Variant.product_id == Product.id, OfferMatch.superseded_at.is_(None))
        .correlate(Product)
        .scalar_subquery()
    )
    stmt = (
        select(Product, Brand.canonical_name, Category.slug, held.label("entries"), placed)
        .join(Brand, Brand.id == Product.brand_id)
        .join(Category, Category.id == Product.category_id)
        .where(Product.is_visible.is_(True))
    )
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if brand_id is not None:
        stmt = stmt.where(Product.brand_id == brand_id)
    groups: dict[tuple[int, int, str], list[tuple[Any, ...]]] = defaultdict(list)
    for product, brand, category, count, offers in (await session.execute(stmt)).all():
        # `+` is a word, as in `normalize_model`: `Galaxy S25+` is not `Galaxy S25`, and is
        # `Galaxy S25 Plus`. Dropped, the first 80 suspects began with those two phones.
        spelled = product.model.casefold().replace("+", " plus ")
        words = " ".join(sorted(_WORD.findall(spelled)))
        groups[(product.brand_id, product.category_id, words)].append(
            (product, brand, category, count or 0, offers or 0)
        )
    found: list[Suspect] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        # The spelling most entries already carry is the one to keep.
        group.sort(key=lambda row: -row[3])
        keep = group[0][0]
        found.append(
            Suspect(
                kind=SuspectKind.WORD_ORDER,
                action="registry",
                brand=group[0][1],
                category=group[0][2],
                detail=(
                    "one name in several orders or cases: "
                    + ", ".join(f"`{row[0].model}` ({row[3]})" for row in group)
                    + f"; enter the others as aliases of `{keep.model}`"
                ),
                evidence=keep.model,
                entries=[
                    SuspectEntry(
                        id=None,
                        product_id=row[0].id,
                        title=row[0].title_override or row[0].title,
                        model=row[0].model,
                        offers_count=row[4],
                        entries_count=row[3],
                    )
                    for row in group
                ],
            )
        )
    return found
