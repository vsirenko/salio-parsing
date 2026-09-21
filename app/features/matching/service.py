"""Placing a listing in the catalogue, or saying exactly why it could not be placed."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

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
from app.features.judge.schemas import BrandRequest, BrandVerdict, JudgeReport
from app.features.judge.service import JudgeService
from app.features.matching.schemas import (
    DecidedBy,
    ManualMatch,
    MatchOutcome,
    MatchQueueRead,
    Method,
    OfferMatchRead,
    QueueSummary,
    Reason,
    RunReport,
)
from app.schemas.pagination import Pagination

# How much each rung is worth. A barcode is proof; a model string that agreed is a guess
# that landed, and the gap between them is what `method` exists to preserve.
CONFIDENCE = {
    Method.GTIN: Decimal("1.000"),
    Method.BRAND_MPN: Decimal("0.950"),
    Method.BRAND_MODEL: Decimal("0.800"),
    Method.HUMAN: Decimal("1.000"),
}


class BrandLookup(NamedTuple):
    """What a brand string turned into, and what stood in the way when it turned into
    nothing.

    `candidates` is the point of carrying a tuple rather than a brand: a string that means
    two brands is a question with the answers already in hand, and dropping them would turn
    a one-click choice back into a search.
    """

    brand: Brand | None
    state: str
    candidates: list[int]
    # Present only when a stored judgement is what settled it. Carried so the match it
    # leads to can record that a model, not an alias, chose the brand.
    verdict: BrandVerdict | None = None


class MatchingService:
    def __init__(self, session: AsyncSession, judge: JudgeService) -> None:
        self.session = session
        # Consulted, never called from the ladder. `stored_brand_verdict` reads the
        # verdict store and cannot reach the network, so running the matcher stays
        # offline, deterministic and as fast as its indexes — asking is a separate pass
        # an admin starts.
        self.judge = judge

    # --- running it ---

    async def match_offer(self, offer_id: int) -> MatchOutcome:
        offer = await self._offer(offer_id)
        reading = await self._reading(offer_id)
        if reading is None:
            raise ValidationError(
                f"Offer {offer_id} has not been read yet", code="nothing_to_match"
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
                return await self._queue(offer, Reason.AMBIGUOUS, self._variants(found, "gtin"))

        lookup = await self._resolve_brand(offer, reading)
        brand = lookup.brand
        # A brand a model chose is not a brand an alias stated, and a match built on one
        # says so: `method` stays the rung that fired, `decided_by` names what had the
        # final say, and the evidence carries the answer it had.
        judged = lookup.verdict is not None
        by = DecidedBy.JUDGE if judged else None
        via = (
            {
                "brand_via": "judge",
                "brand_choice": lookup.verdict.choice,
                "brand_confidence": float(lookup.verdict.confidence),
            }
            if judged
            else {}
        )

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
                        {"signal": "mpn", "brand_id": brand.id, "value": reading.mpn, **via},
                        decided_by=by,
                    )
                if len(found) > 1:
                    return await self._queue(offer, Reason.AMBIGUOUS, self._variants(found, "mpn"))

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
                        {"signal": "model", "brand_id": brand.id, "value": model, **via},
                        decided_by=by,
                    )
                if len(found) > 1:
                    return await self._queue(
                        offer, Reason.AMBIGUOUS, self._variants(found, "model")
                    )

        return await self._queue(offer, *self._why(reading, lookup))

    @staticmethod
    def _why(reading: NormalizedOffer, lookup: BrandLookup) -> tuple[Reason, list[dict]]:
        """Name the problem and hand over whatever was found while failing.

        Each reason is a different kind of work, so they are not one bucket — and the two
        brand reasons are not one either. A string that means nothing has to be researched;
        a string that means two brands only has to be chosen between, and the difference is
        whether there is anything on the row to choose from.

        Order matters: an offer with nothing in it is not a brand problem, and a brand that
        would not resolve is not the catalogue missing a row.
        """
        has_any = any((reading.gtin, reading.mpn, reading.model, reading.brand_raw))
        if not has_any:
            return Reason.NO_SIGNALS, []
        if lookup.state == "ambiguous":
            return Reason.BRAND_AMBIGUOUS, [
                {"brand_id": brand_id, "why": "brand_alias"} for brand_id in lookup.candidates
            ]
        # The judge was asked and said none of the candidates makes this. That is not an
        # unanswered choice any more — it is a brand nobody has, which is different work.
        if lookup.state in ("unknown", "unreadable", "judged_none"):
            return Reason.BRAND_UNKNOWN, []
        return Reason.SIGNALS_UNMATCHED, []

    @staticmethod
    def _variants(variant_ids: list[int], signal: str) -> list[dict]:
        return [{"variant_id": variant_id, "why": signal} for variant_id in variant_ids]

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

    async def _resolve_brand(self, offer: Offer, reading: NormalizedOffer) -> BrandLookup:
        """A brand string to a brand, or an honest nothing with its reason attached.

        A string that resolves to two brands is not a brand: Delta is taps and machine
        tools. Picking one would send the search into the wrong block, where it would find
        nothing and report the catalogue as incomplete. Both brands are carried back so the
        queue row can hold the question rather than only the failure.

        An alias cannot settle that, and no alias ever will: `Delta` belongs to both of
        them legitimately, so this is decided per listing and not once for the string. That
        is the gap a stored judgement fills — and only a stored one, read here without a
        network call.
        """
        if not reading.brand_raw:
            return BrandLookup(None, "none_given", [])
        try:
            normalized = normalize_brand(reading.brand_raw)
        except ValueError:
            # A string that normalizes to nothing — punctuation, a stray trademark sign.
            # Same work as a brand nobody knows: a person reads the raw value.
            return BrandLookup(None, "unreadable", [])

        rows = await self.session.execute(
            select(Brand)
            .join(BrandAlias, BrandAlias.brand_id == Brand.id)
            .where(BrandAlias.alias_normalized == normalized)
            .order_by(Brand.id)
        )
        brands = list(rows.scalars().unique())
        if len(brands) == 1:
            return BrandLookup(brands[0], "resolved", [brands[0].id])
        if not brands:
            return BrandLookup(None, "unknown", [])

        candidates = [brand.id for brand in brands]
        verdict = await self.judge.stored_brand_verdict(
            self._brand_request(offer, reading, candidates)
        )
        if verdict is None:
            return BrandLookup(None, "ambiguous", candidates)
        if verdict.accepted:
            chosen = next(brand for brand in brands if brand.id == verdict.brand_id)
            return BrandLookup(chosen, "resolved_judge", candidates, verdict)
        # Answered "neither" is a decision; answered without enough certainty is not, and
        # leaving that one ambiguous is what keeps a weak opinion from placing a listing.
        return BrandLookup(None, "judged_none" if verdict.no_match else "ambiguous", candidates)

    @staticmethod
    def _brand_request(
        offer: Offer, reading: NormalizedOffer, candidates: list[int]
    ) -> BrandRequest:
        """The listing, in the terms the judge asks about it.

        One place builds it, so the question a pass asks and the question the ladder looks
        up are the same question — they are keyed by their content, and a field spelled
        differently in two places would be a store that never hits.
        """
        return BrandRequest(
            key=offer.id,
            title=reading.title,
            brand_raw=reading.brand_raw,
            model_raw=reading.model,
            brand_ids=candidates,
        )

    # --- writing the outcome ---

    async def _link(
        self,
        offer: Offer,
        variant_id: int,
        method: Method,
        evidence: dict,
        *,
        decided_by: DecidedBy | None = None,
    ) -> MatchOutcome:
        await self._supersede(offer.id)
        if decided_by is None:
            decided_by = DecidedBy.HUMAN if method is Method.HUMAN else DecidedBy.RULE
        match = OfferMatch(
            offer_id=offer.id,
            variant_id=variant_id,
            method=method.value,
            confidence=CONFIDENCE[method],
            evidence=evidence,
            decided_by=decided_by.value,
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

    async def _queue(self, offer: Offer, reason: Reason, candidates: list[dict]) -> MatchOutcome:
        existing = await self.session.get(MatchQueue, offer.id)
        if existing is None:
            self.session.add(
                MatchQueue(offer_id=offer.id, reason=reason.value, candidates=candidates)
            )
        else:
            existing.reason = reason.value
            existing.candidates = candidates
            existing.attempts += 1
            existing.last_attempt_at = datetime.now(UTC)

        await self.session.flush()
        return MatchOutcome(
            offer_id=offer.id,
            matched=False,
            method=None,
            variant_id=None,
            reason=reason,
            candidates=candidates,
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

    # --- asking for help ---

    async def judge_brands(self, *, limit: int = 50) -> JudgeReport:
        """Put the brand choices nobody could make in front of the judge, then retry them.

        Only `brand_ambiguous`. The other reasons have nothing to choose between, and a
        choice is the only thing the judge does — handing it `signals_unmatched` would be
        asking a question whose options do not exist.

        Answering and placing are one call because they are useless apart: a verdict that
        nothing acts on is a row, and re-running the whole queue to pick it up would redo
        every listing that is stuck for an unrelated reason.
        """
        rows = (
            await self.session.scalars(
                select(MatchQueue)
                .where(MatchQueue.reason == Reason.BRAND_AMBIGUOUS.value)
                .order_by(MatchQueue.offer_id)
                .limit(limit)
            )
        ).all()

        requests: list[BrandRequest] = []
        for row in rows:
            reading = await self._reading(row.offer_id)
            if reading is None:
                continue
            offer = await self._offer(row.offer_id)
            candidates = [
                entry["brand_id"] for entry in row.candidates if entry.get("brand_id") is not None
            ]
            requests.append(self._brand_request(offer, reading, candidates))

        verdicts, report = await self.judge.decide_brands(requests)

        placed = 0
        for offer_id, verdict in verdicts.items():
            if not verdict.accepted and not verdict.no_match:
                continue
            # Re-run rather than write the brand in: the verdict is now in the store, so
            # the ladder resolves it on its own and takes whichever rung actually fires.
            reading = await self._reading(offer_id)
            if reading is None:
                continue
            outcome = await self._decide(await self._offer(offer_id), reading)
            placed += outcome.matched

        report = report.model_copy(update={"placed": placed})
        audit.record_changes(**report.model_dump(mode="json"))
        return report

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
            .where(RawOffer.offer_id == offer_id)
            .order_by(RawOffer.fetched_at.desc(), NormalizedOffer.id.desc())
            .limit(1)
        )
