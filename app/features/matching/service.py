"""Placing a listing in the catalogue, or saying exactly why it could not be placed."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import (
    AvailabilityEvent,
    Brand,
    BrandAlias,
    MatchQueue,
    NormalizedOffer,
    Offer,
    OfferMatch,
    PriceEvent,
    RawOffer,
    Variant,
    VariantGtin,
    VariantMpn,
)
from app.db.query import paginated
from app.features.brands.normalization import normalize_brand
from app.features.catalog.identity import normalize_model
from app.features.matching.schemas import (
    ManualMatch,
    MatchOutcome,
    MatchQueueRead,
    Method,
    OfferMatchRead,
    QueueSummary,
    Reason,
    RunReport,
)
from app.features.offers.normalization import RULESET_VERSION
from app.schemas.pagination import Pagination

# How much each rung is worth. A barcode is proof; a model string that agreed is a guess
# that landed, and the gap between them is what `method` exists to preserve.
CONFIDENCE = {
    Method.GTIN: Decimal("1.000"),
    Method.BRAND_MPN: Decimal("0.950"),
    Method.BRAND_MODEL: Decimal("0.800"),
    Method.HUMAN: Decimal("1.000"),
}


class MatchingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- running it ---

    async def match_offer(self, offer_id: int) -> MatchOutcome:
        offer = await self._offer(offer_id)
        reading = await self._reading(offer_id)
        if reading is None:
            raise ValidationError(
                f"Offer {offer_id} has no reading under ruleset '{RULESET_VERSION}'",
                code="nothing_to_match",
            )

        audit.set_target("offer", offer_id)
        outcome = await self._decide(offer, reading)
        audit.record_changes(
            matched=outcome.matched,
            method=outcome.method.value if outcome.method else None,
            reason=outcome.reason.value if outcome.reason else None,
        )
        return outcome

    async def run(self, *, limit: int = 100) -> RunReport:
        """Work through listings nothing has placed yet.

        Offers with a live match are skipped; a queued one is retried, because the
        catalogue it failed against changes underneath it.
        """
        active = select(OfferMatch.offer_id).where(OfferMatch.superseded_at.is_(None))
        pending = await self.session.scalars(
            select(Offer.id).where(Offer.id.not_in(active)).order_by(Offer.id).limit(limit)
        )

        matched = queued = 0
        for offer_id in list(pending):
            reading = await self._reading(offer_id)
            if reading is None:
                continue
            offer = await self._offer(offer_id)
            outcome = await self._decide(offer, reading)
            matched += outcome.matched
            queued += not outcome.matched

        return RunReport(attempted=matched + queued, matched=matched, queued=queued)

    # --- the ladder ---

    async def _decide(self, offer: Offer, reading: NormalizedOffer) -> MatchOutcome:
        # 1. A barcode is the strongest thing there is, and needs no brand to be resolved
        #    first — which is why it runs before anything else.
        if reading.gtin:
            found = await self._by_gtin(reading.gtin)
            if len(found) == 1:
                return await self._link(
                    offer, found[0], Method.GTIN, {"signal": "gtin", "value": reading.gtin}
                )
            if len(found) > 1:
                return await self._queue(offer, Reason.AMBIGUOUS, found, signal="gtin")

        brand, brand_state = await self._resolve_brand(reading.brand_raw)

        if brand is not None:
            # 2. A part number only means something beside its maker, which is why the
            #    brand has to be settled first.
            if reading.mpn:
                found = await self._by_mpn(brand.id, reading.mpn)
                if len(found) == 1:
                    return await self._link(
                        offer,
                        found[0],
                        Method.BRAND_MPN,
                        {"signal": "mpn", "brand_id": brand.id, "value": reading.mpn},
                    )
                if len(found) > 1:
                    return await self._queue(offer, Reason.AMBIGUOUS, found, signal="mpn")

            # 3. The model designation, normalized so that WW90T554DAX, ww90t554-dax and
            #    WW 90 T554 DAX are one string. Language-neutral, which matters when a
            #    title shares nothing across three languages but the brand and this.
            model = reading.model or reading.title
            if model:
                found = await self._by_model(brand.id, model)
                if len(found) == 1:
                    return await self._link(
                        offer,
                        found[0],
                        Method.BRAND_MODEL,
                        {"signal": "model", "brand_id": brand.id, "value": model},
                    )
                if len(found) > 1:
                    return await self._queue(offer, Reason.AMBIGUOUS, found, signal="model")

        return await self._queue(offer, self._why(reading, brand, brand_state), [])

    @staticmethod
    def _why(reading: NormalizedOffer, brand: Brand | None, brand_state: str) -> Reason:
        """Name the problem, because each one is a different kind of work.

        Order matters: an offer with nothing in it is not a brand problem, and a brand that
        would not resolve is not the catalogue missing a row.
        """
        has_any = any((reading.gtin, reading.mpn, reading.model, reading.brand_raw))
        if not has_any:
            return Reason.NO_SIGNALS
        if brand is None and brand_state != "none_given":
            return Reason.BRAND_UNRESOLVED
        return Reason.SIGNALS_UNMATCHED

    # --- the lookups, each an index hit rather than a scan ---

    async def _by_gtin(self, gtin: str) -> list[int]:
        rows = await self.session.scalars(
            select(VariantGtin.variant_id).where(VariantGtin.gtin == gtin)
        )
        return sorted(set(rows))

    async def _by_mpn(self, brand_id: int, mpn: str) -> list[int]:
        rows = await self.session.scalars(
            select(VariantMpn.variant_id).where(
                VariantMpn.brand_id == brand_id,
                VariantMpn.mpn_normalized == normalize_model(mpn),
            )
        )
        return sorted(set(rows))

    async def _by_model(self, brand_id: int, model: str) -> list[int]:
        normalized = normalize_model(model)
        if not normalized:
            return []
        rows = await self.session.scalars(
            select(Variant.id).where(
                Variant.brand_id == brand_id, Variant.model_normalized == normalized
            )
        )
        return sorted(set(rows))

    async def _resolve_brand(self, brand_raw: str | None) -> tuple[Brand | None, str]:
        """A brand string to a brand, or an honest nothing.

        A string that resolves to two brands is not a brand: Delta is taps and machine
        tools. Picking one would send the search into the wrong block, where it would find
        nothing and report the catalogue as incomplete.
        """
        if not brand_raw:
            return None, "none_given"
        try:
            normalized = normalize_brand(brand_raw)
        except ValueError:
            return None, "unreadable"

        rows = await self.session.execute(
            select(Brand)
            .join(BrandAlias, BrandAlias.brand_id == Brand.id)
            .where(BrandAlias.alias_normalized == normalized)
            .order_by(Brand.id)
        )
        brands = list(rows.scalars().unique())
        if len(brands) == 1:
            return brands[0], "resolved"
        return None, "ambiguous" if brands else "unknown"

    # --- writing the outcome ---

    async def _link(
        self, offer: Offer, variant_id: int, method: Method, evidence: dict
    ) -> MatchOutcome:
        await self._supersede(offer.id)
        match = OfferMatch(
            offer_id=offer.id,
            variant_id=variant_id,
            method=method.value,
            confidence=CONFIDENCE[method],
            evidence=evidence,
            decided_by="human" if method is Method.HUMAN else "rule",
        )
        self.session.add(match)
        await self.session.execute(
            MatchQueue.__table__.delete().where(MatchQueue.offer_id == offer.id)
        )
        await self._carry_variant_into_history(offer.id, variant_id)
        await self.session.flush()
        return MatchOutcome(
            offer_id=offer.id,
            matched=True,
            method=method,
            variant_id=variant_id,
            reason=None,
            candidates=[],
        )

    async def _queue(
        self, offer: Offer, reason: Reason, candidates: list[int], *, signal: str | None = None
    ) -> MatchOutcome:
        rows = [{"variant_id": v, "why": signal} for v in candidates]
        existing = await self.session.get(MatchQueue, offer.id)
        if existing is None:
            self.session.add(MatchQueue(offer_id=offer.id, reason=reason.value, candidates=rows))
        else:
            existing.reason = reason.value
            existing.candidates = rows
            existing.attempts += 1
            existing.last_attempt_at = datetime.now(UTC)

        await self.session.flush()
        return MatchOutcome(
            offer_id=offer.id,
            matched=False,
            method=None,
            variant_id=None,
            reason=reason,
            candidates=rows,
        )

    async def _supersede(self, offer_id: int) -> None:
        await self.session.execute(
            update(OfferMatch)
            .where(OfferMatch.offer_id == offer_id, OfferMatch.superseded_at.is_(None))
            .values(superseded_at=datetime.now(UTC))
        )

    async def _carry_variant_into_history(self, offer_id: int, variant_id: int | None) -> None:
        """Point this listing's recorded facts at the variant we now think it is.

        The cost of denormalizing the variant onto the series, and it is real: the number
        of rows rewritten grows with how long the listing has existed. Bounded to one
        listing, which is why it is affordable — but a re-match is heavier than it looks.
        """
        for model in (PriceEvent, AvailabilityEvent):
            await self.session.execute(
                update(model).where(model.offer_id == offer_id).values(variant_id=variant_id)
            )

    # --- a human deciding ---

    async def set_manually(self, offer_id: int, payload: ManualMatch) -> MatchOutcome:
        offer = await self._offer(offer_id)
        if await self.session.get(Variant, payload.variant_id) is None:
            raise NotFoundError(f"Variant {payload.variant_id} not found")

        audit.set_target("offer", offer_id)
        outcome = await self._link(
            offer,
            payload.variant_id,
            Method.HUMAN,
            {"signal": "human", "note": payload.note},
        )
        audit.record_changes(variant_id=payload.variant_id, method="human")
        return outcome

    async def unlink(self, offer_id: int) -> None:
        offer = await self._offer(offer_id)
        active = await self.session.scalar(
            select(OfferMatch).where(
                OfferMatch.offer_id == offer_id, OfferMatch.superseded_at.is_(None)
            )
        )
        if active is None:
            raise NotFoundError(f"Offer {offer_id} has no active match")

        audit.set_target("offer", offer_id)
        await self._supersede(offer_id)
        await self._carry_variant_into_history(offer_id, None)
        # Back to the queue it came from, as something a person set aside rather than
        # something the matcher failed at.
        await self._queue(offer, Reason.SIGNALS_UNMATCHED, [])
        audit.record_changes(unlinked_variant_id=active.variant_id)

    # --- reading it back ---

    async def history(self, offer_id: int) -> list[OfferMatchRead]:
        await self._offer(offer_id)
        rows = await self.session.scalars(
            select(OfferMatch)
            .where(OfferMatch.offer_id == offer_id)
            .order_by(OfferMatch.decided_at.desc(), OfferMatch.id.desc())
        )
        return [OfferMatchRead.model_validate(row) for row in rows]

    async def queue(
        self, pagination: Pagination, *, reason: Reason | None = None
    ) -> tuple[list[MatchQueueRead], int]:
        stmt = select(MatchQueue)
        if reason is not None:
            stmt = stmt.where(MatchQueue.reason == reason.value)
        rows, total = await paginated(self.session, stmt.order_by(MatchQueue.offer_id), pagination)
        return [MatchQueueRead.model_validate(row) for row in rows], total

    async def summary(self) -> QueueSummary:
        """What is actually in the way, counted.

        Not "how many offers carry a barcode" — that counts signals present. This counts
        what happened when they were used, which is the number worth having.
        """
        by_reason = {
            reason: count
            for reason, count in (
                await self.session.execute(
                    select(MatchQueue.reason, func.count()).group_by(MatchQueue.reason)
                )
            ).all()
        }
        queued = sum(by_reason.values())
        matched = await self.session.scalar(
            select(func.count()).select_from(OfferMatch).where(OfferMatch.superseded_at.is_(None))
        )
        offers = await self.session.scalar(select(func.count()).select_from(Offer))
        return QueueSummary(
            total=queued,
            by_reason=by_reason,
            matched_offers=matched or 0,
            offers=offers or 0,
            matched_share=round((matched or 0) / offers, 4) if offers else 0.0,
        )

    # --- lookups ---

    async def _offer(self, offer_id: int) -> Offer:
        offer = await self.session.get(Offer, offer_id)
        if offer is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        return offer

    async def _reading(self, offer_id: int) -> NormalizedOffer | None:
        return await self.session.scalar(
            select(NormalizedOffer)
            .join(RawOffer, RawOffer.id == NormalizedOffer.raw_offer_id)
            .where(
                RawOffer.offer_id == offer_id,
                NormalizedOffer.ruleset_version == RULESET_VERSION,
            )
            .order_by(RawOffer.fetched_at.desc(), NormalizedOffer.id.desc())
            .limit(1)
        )
