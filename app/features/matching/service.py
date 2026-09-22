"""Placing a listing in the catalogue, or saying exactly why it could not be placed."""

import logging
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import AppError, ConflictError, NotFoundError, ValidationError
from app.db.models import (
    Attribute,
    AttributeValue,
    AvailabilityEvent,
    Brand,
    BrandAlias,
    CategoryAttribute,
    MatchQueue,
    NormalizedOffer,
    Offer,
    OfferMatch,
    PriceEvent,
    Product,
    RawOffer,
    Run,
    Source,
    Variant,
    VariantAttribute,
    VariantGtin,
    VariantMpn,
)
from app.db.query import paginated
from app.features.brands.normalization import normalize_brand
from app.features.catalog.identity import normalize_model
from app.features.catalog.schemas import (
    IdentifierCreate,
    IdentifierOrigin,
    ProductCreate,
    SourceKind,
    ValueOrigin,
    VariantAttributeSet,
    VariantCreate,
    VariantUpdate,
)
from app.features.catalog.service import CatalogService
from app.features.judge.schemas import (
    BrandRequest,
    BrandVerdict,
    ColourRequest,
    JudgeReport,
    VariantRequest,
)
from app.features.judge.service import COLOUR_KEY, JudgeService
from app.features.matching.schemas import (
    DecidedBy,
    ManualMatch,
    MatchOutcome,
    MatchQueueRead,
    MergeReport,
    Method,
    OfferMatchRead,
    PromotionReport,
    QueueSummary,
    Reason,
    RenameReport,
    RunReport,
)
from app.features.runs.schemas import Kind
from app.schemas.pagination import Pagination

# How much each rung is worth. A barcode is proof; a model string that agreed is a guess
# that landed, and the gap between them is what `method` exists to preserve.
log = logging.getLogger(__name__)

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


class IdentityCheck(NamedTuple):
    """What comparing the axes said about a set of candidates.

    Three answers, not two. `agreed` and `unverifiable` are different enough that the rungs
    treat them differently, and `checked` is the difference between "the axes confirmed it"
    and "there was nothing to check with" — which look identical in `agreed` and mean
    opposite things to anything that wants to learn from the match.
    """

    agreed: list[int]
    unverifiable: list[int]
    # False when the listing brought no axis at all. Then every candidate is in `agreed`
    # because none could be ruled out, which is not the same as being confirmed.
    checked: bool
    # The candidates where *every* axis the listing carried was compared and agreed —
    # not merely one of them. The difference is what decides whether a match is solid
    # enough to write a barcode onto, and it was the gap that let a black phone's barcode
    # land on a blue one's entry: they agreed on capacity, and the entry had no colour to
    # disagree with yet.
    complete: frozenset[int] = frozenset()


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
        identity = await self._identity(offer, reading)
        if reading.gtin:
            found = await self._retire_learned(
                await self._by_gtin(reading.gtin), reading.gtin, identity
            )
            if len(found) == 1:
                outcome = await self._link(
                    offer, found[0], Method.GTIN, {"signal": "gtin", "value": reading.gtin}
                )
                # Proof, so what this listing knows about the thing is worth keeping.
                await self._reconcile(found[0], reading)
                return outcome
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
                # A part number is *meant* to name the thing you buy, and on one shop it
                # does. On another it names the model: `CPH2865` is the Oppo Reno16 5G at
                # 256 GB and at 512 GB alike, and five of twenty matches on this rung had
                # pulled two capacities onto one variant. So a candidate that contradicts
                # an axis is dropped — but one with nothing to compare is still taken,
                # which is where this differs from the model rung below. There a family
                # name has to be confirmed before it is believed; here a part number is
                # believed until something says otherwise.
                check = await self._identity_agrees(found, identity)
                usable = sorted(check.agreed + check.unverifiable)
                if len(usable) == 1:
                    outcome = await self._link(
                        offer,
                        usable[0],
                        Method.BRAND_MPN,
                        {"signal": "mpn", "brand_id": brand.id, "value": reading.mpn, **via},
                        decided_by=by,
                    )
                    # The barcode this listing carried, on the entry its part number
                    # found. Without it the strongest signal there is never reaches the
                    # catalogue from this rung: `PHONE WAVE 7C` matched by part number and
                    # kept its barcode to itself, so the next shop carrying that barcode
                    # found nothing, built `Wave 7C` beside it, and one phone became two
                    # entries. Twenty-six barcodes were sitting on two entries each when
                    # this was found. Guarded exactly as the rung below it is: every axis
                    # the category names has to have been weighed, because a part number
                    # can name a family and agreeing on the capacity while the entry has no
                    # colour to disagree with is not agreement.
                    if usable[0] in check.complete:
                        await self._learn_gtin(usable[0], reading)
                    if check.checked and usable[0] in check.agreed:
                        await self._reconcile(usable[0], reading)
                    return outcome
                if len(usable) > 1:
                    return await self._queue(offer, Reason.AMBIGUOUS, self._variants(usable, "mpn"))
                # Everything the part number found is a different configuration. Not a
                # miss — the listing goes on to look for a variant of its own.

            # 3. The model designation, normalized so that WW90T554DAX, ww90t554-dax and
            #    WW 90 T554 DAX are one string. Language-neutral, which matters when a
            #    title shares nothing across three languages but the brand and this.
            model = reading.model or reading.title
            if model:
                found = await self._by_model(brand.id, model)
                # A model string names a family, not a thing you can buy. `Galaxy S26 Ultra
                # 5G` is the 256, the 512 and the terabyte alike, and matching on it alone
                # filed fifteen listings spanning a thousand euros as one product. So the
                # candidates it produces have to agree on the axes before one of them is
                # accepted.
                check = await self._identity_agrees(found, identity)
                agreed, unverifiable = check.agreed, check.unverifiable
                if len(agreed) > 1:
                    # An entry that records no colour agrees with every colour, because it
                    # has nothing to disagree with — and one of those sitting beside a real
                    # one made every coloured listing of that model ambiguous, with the
                    # outcome depending on which arrived first. Among candidates that all
                    # agree, one that agreed on *every* axis the category names has more
                    # evidence behind it than one that agreed on the two it happened to
                    # hold, so it wins. Two complete ones would be a real question and stay
                    # ambiguous.
                    complete = [variant_id for variant_id in agreed if variant_id in check.complete]
                    if len(complete) == 1:
                        agreed = complete
                if len(agreed) == 1:
                    outcome = await self._link(
                        offer,
                        agreed[0],
                        Method.BRAND_MODEL,
                        {"signal": "model", "brand_id": brand.id, "value": model, **via},
                        decided_by=by,
                    )
                    # Only when every axis this listing carried was weighed. Agreeing on
                    # capacity while the entry has no colour to disagree with is not the
                    # same thing, and treating it as one is how a black phone's barcode
                    # ended up on a blue one's entry — permanently, at confidence 1.00.
                    if agreed[0] in check.complete:
                        await self._learn_gtin(agreed[0], reading)
                    if check.checked:
                        await self._reconcile(agreed[0], reading)
                    return outcome
                if len(agreed) > 1:
                    return await self._queue(
                        offer, Reason.AMBIGUOUS, self._variants(agreed, "model")
                    )
                if unverifiable:
                    # The model agreed and there was no axis in common to check it with.
                    # Not a match and not a miss: somebody, or a judge, decides.
                    return await self._queue(
                        offer, Reason.LOW_CONFIDENCE, self._variants(unverifiable, "model")
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

        # A barcode needs no brand. The first rung ran before the brand was looked at, and
        # reaching here means it found nothing — so whatever the brand turned out to be
        # cannot explain this failure, and naming it sends somebody to write aliases when
        # what is missing is the product. Measured the hard way: 520 real listings, 99.6%
        # of them carrying a barcode, all reported as `brand_unknown` when the truth was an
        # empty catalogue.
        #
        # Part numbers and model strings are different: both rungs search within a brand,
        # so a brand that would not resolve really is what stopped them.
        if reading.gtin:
            return Reason.SIGNALS_UNMATCHED, []

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

    async def _retire_learned(
        self, found: list[int], gtin: str, identity: dict[str, Any]
    ) -> list[int]:
        """Drop a candidate whose barcode we inferred and whose axes now contradict it.

        A barcode a shop published is evidence from the world and stays proof: two shops
        calling one phone `graphite` and `grey` disagree about a shade, not about which
        phone it is, and 431 live matches are exactly that.

        A barcode `_learn_gtin` put on an entry is our own conclusion, and this is how one
        hardened into proof. A bigbox `White Titanium` listing with no barcode became an
        entry; an rdveikals `Natural Titanium` listing matched it on the model while both
        still read `titanium`; the match looked complete because the wrong axis agreed, and
        the entry was given that listing's barcode. From then on the listing found itself by
        that barcode on every pass, and this rung never looked at a colour. Forty-nine
        matches were held that way and forty of them were a different colour family —
        black against orange, white against green — not a shade.

        So a learned barcode yields to a contradiction and the listing falls through to the
        rungs below, which do weigh the axes. A stated one does not.
        """
        if not found or not identity:
            return found
        keep: list[int] = []
        for variant_id in found:
            check = await self._identity_agrees([variant_id], identity)
            if variant_id not in check.agreed and check.checked:
                origin = await self.session.scalar(
                    select(VariantGtin.origin).where(
                        VariantGtin.variant_id == variant_id, VariantGtin.gtin == gtin
                    )
                )
                if origin == IdentifierOrigin.RULE.value:
                    log.info("match: variant %d keeps a learned barcode it contradicts", variant_id)
                    continue
            keep.append(variant_id)
        return keep

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

    async def _identity(self, offer: Offer, reading: NormalizedOffer) -> dict[str, Any]:
        """The axes this listing is taken to name — what it said, plus what was bought.

        A reading is a pure function of a payload and the rules that apply to it, and it
        stays that way: a bought answer is not a rule and cannot be one. It is consulted
        here instead, exactly where a bought brand is consulted, and for the same reason —
        the ladder and the promotion bar are the two places that have to know.

        Only the colour, and only when the reading found none. The category's rule reads a
        colour out of a field and never out of a title, because cutting one out of a title
        takes 358 forms across one shop and canonicalising those by guessing splits one
        product into several. 53 of the 57 listings this was written for keep their colour
        in the title, so there is no field to read and nothing left to count.

        It is deliberately not written into `attribute_value_aliases`, which is where the
        plan started. That table is global and a marketing colour is not: `Canyon` is pink
        on a Google and orange on an Oppo, both proved by two shops, so an alias learned
        from one listing would be applied by the reading to a different maker's phone — the
        confident wrong answer the colour rule exists to avoid. A verdict is keyed by the
        title and the maker together, which is the granularity a marketing name has.
        """
        identity = dict(reading.identity or {})
        if identity.get(COLOUR_KEY):
            return identity
        verdict = await self.judge.stored_colour_verdict(
            ColourRequest(
                key=offer.id,
                title=reading.title,
                brand=reading.brand_raw,
                model=reading.model,
            )
        )
        if verdict is not None and verdict.accepted and verdict.canonical:
            identity[COLOUR_KEY] = verdict.canonical
        return identity

    async def _identity_agrees(
        self, variant_ids: list[int], identity: dict[str, Any]
    ) -> IdentityCheck:
        """Split candidates into the ones whose axes agree and the ones nothing can check.

        Compared on the axes both sides happen to carry. A candidate that disagrees on one
        of them is a different thing wearing the same model string — a different capacity,
        usually — and is dropped. A candidate with no axis in common cannot be confirmed or
        denied, which is a third answer and the one `low_confidence` was waiting for.

        The check only applies when the listing brought an axis to check with. Without one
        there is nothing to disagree about, and refusing on that basis would stop the rung
        firing at all until every category and every shop is furnished.
        """
        if not variant_ids:
            return IdentityCheck([], [], False)
        # Numbers and canonical enum values alike. Colour was left out while nothing could
        # resolve `Melna` to anything, and leaving it out is how two colours of one phone
        # stayed one catalogue entry.
        wanted: dict[str, Decimal | str] = {}
        for key, value in identity.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float | Decimal):
                wanted[key] = Decimal(str(value))
            elif isinstance(value, str) and value:
                wanted[key] = value
        if not wanted:
            # The listing carries no axis at all — its category has no rules yet, or it
            # said nothing this reading could use. There is nothing to check with, and
            # refusing on that basis would mean the model rung never fires until both sides
            # are furnished. It goes back to being what it was: a model string, at the
            # confidence a model string is worth.
            return IdentityCheck(sorted(variant_ids), [], False)

        rows = await self.session.execute(
            select(
                VariantAttribute.variant_id,
                Attribute.key,
                VariantAttribute.value_num,
                AttributeValue.canonical,
            )
            .join(Attribute, Attribute.id == VariantAttribute.attribute_id)
            .outerjoin(AttributeValue, AttributeValue.id == VariantAttribute.value_id)
            .where(VariantAttribute.variant_id.in_(variant_ids))
        )
        held: dict[int, dict[str, Decimal | str]] = {}
        for variant_id, key, number, canonical in rows.all():
            if number is not None:
                held.setdefault(variant_id, {})[key] = number
            elif canonical is not None:
                held.setdefault(variant_id, {})[key] = canonical

        required = await self._identity_axes(variant_ids)

        agreed: list[int] = []
        unverifiable: list[int] = []
        complete: set[int] = set()
        for variant_id in variant_ids:
            theirs = held.get(variant_id, {})
            shared = set(theirs) & set(wanted)
            if not shared:
                unverifiable.append(variant_id)
            elif all(theirs[key] == wanted[key] for key in shared):
                agreed.append(variant_id)
                # Complete means the axes the *category* says tell its products apart were
                # all known on both sides — not merely that everything the listing happened
                # to carry was weighed. Two shops that state no colour make a red and a
                # black phone look identical, and under the weaker reading that silence
                # counted as agreement.
                wanted_here = required.get(variant_id) or set(wanted)
                if wanted_here <= shared:
                    complete.add(variant_id)
        return IdentityCheck(sorted(agreed), sorted(unverifiable), True, frozenset(complete))

    async def _identity_axes(self, variant_ids: list[int]) -> dict[int, set[str]]:
        """Which axes each candidate's category says tell its products apart.

        `category_attributes.identity_bearing` is where that is written down, and it is a
        property of the pair rather than of the attribute: a capacity tells two phones apart
        and would mean nothing on a monitor. A category that declares none leaves the older
        rule standing — everything the listing carried — because requiring nothing would
        make every match complete, which is the opposite of the intent.
        """
        rows = await self.session.execute(
            select(Variant.id, Attribute.key)
            .join(CategoryAttribute, CategoryAttribute.category_id == Variant.category_id)
            .join(Attribute, Attribute.id == CategoryAttribute.attribute_id)
            .where(Variant.id.in_(variant_ids), CategoryAttribute.identity_bearing.is_(True))
        )
        axes: dict[int, set[str]] = {}
        for variant_id, key in rows.all():
            axes.setdefault(variant_id, set()).add(key)
        return axes

    async def _reconcile(self, variant_id: int, reading: NormalizedOffer) -> None:
        """Fill in axes the variant does not have, from a listing that just matched it.

        `variant_attributes` says of itself that it holds an attribute "reconciled across
        its offers", and until now it was not: axes were written once, when a listing became
        a catalogue entry, and never again. So an entry created from a shop that does not
        state colour had none, for good — and the comparison that decides whether the next
        listing is the same thing only looks at the axes both sides carry, so colour could
        not separate anything. Three hundred and twenty-seven entries held two colours at
        once because of it: one `Nokia 3210` for the black, the blue and the gold.

        **Gaps only, never an answer already there.** A shop that states 512 GB for a phone
        whose own title reads `4/128GB` is in the collected data; letting whichever listing
        arrived second overwrite the first would make the catalogue depend on crawl order.

        **And only from a match that proved something.** A barcode is proof. A model string
        is a conclusion, and teaching the variant from one turns the conclusion into a fact
        the next listing is then measured against — which is exactly how a learned barcode
        hardened a wrong guess before. So a rung below the barcode teaches only when the
        axes it did compare agreed.
        """
        if not reading.identity:
            return
        try:
            # What the shop itself said, and not a colour the judge named for it. This
            # writes onto an entry somebody else created, where a bought answer would spread
            # from the listing it was bought for to every listing that entry ever matches.
            await self._carry_identity(
                CatalogService(self.session),
                variant_id,
                dict(reading.identity or {}),
                only_if_absent=True,
            )
        except ConflictError:
            # Filling in the last axis is exactly when a duplicate surfaces: two entries
            # that arrive at the same identity are the same thing. That is worth knowing and
            # it is not this listing's problem — the match stands, the two entries stay as
            # they are, and merging them is a decision somebody makes with `variant_merges`.
            # Refusing the match instead would lose a listing over a fact about two others.
            log.info("run: variant %d already has a twin at this identity", variant_id)

    async def _learn_gtin(self, variant_id: int, reading: NormalizedOffer) -> None:
        """Keep the barcode of a listing that was placed without it.

        `variant_gtins` is plural for the ordinary reasons — regional packaging, a reissue,
        a change of supplier — and this is a fourth: a shop that carries a barcode nobody
        else has yet. Of 207 barcodes the two collected shops share, 88 were on no variant
        at all, because the listings carrying them matched on the model instead and the
        barcode was tried, missed and dropped. The same work was then redone on every pass,
        and the strongest signal the matcher has stayed invisible on both shops.

        Only from a match an axis confirmed. A model match is a conclusion, not proof, and
        writing its barcode onto the variant turns that conclusion into proof: every later
        listing with that barcode would match at confidence 1.00, and a wrong one could not
        be argued with afterwards. Confirmed by an axis it is worth keeping; unconfirmed it
        is exactly the guess that should not harden.

        The barcode is known to be on no variant: this runs only below the first rung,
        which looked it up and found nothing.
        """
        if not reading.gtin:
            return
        self.session.add(
            VariantGtin(
                variant_id=variant_id,
                gtin=reading.gtin,
                origin=IdentifierOrigin.RULE.value,
            )
        )
        await self.session.flush()
        audit.record_changes(learned_gtin=reading.gtin, onto_variant=variant_id)

    async def _brand_from_title(self, reading: NormalizedOffer) -> Brand | None:
        """The maker the title begins with, when the field named one nobody knows.

        A shop can be wrong about a brand and still be right about everything else.
        bm.market files eight Google Pixels under `Getnord`, a maker of rugged phones that
        did not make them: the title says `Google Pixel 10`, the model, the colour and the
        capacity all agree with the Pixels four other shops sell, and only the one field
        disagrees. Read as it stands, the listing is lost — and entering `Getnord` in the
        registry would be worse, because then it would be filed confidently under a maker
        that did not make it.

        Deliberately narrow. This runs only where the field resolved to **nothing**, so a
        title is never weighed against a brand a shop stated correctly, and two words before
        one because a maker's name can be two — `Bang & Olufsen`, `Kruger&Matz`.
        """
        # The title first, then the model. The title is where a maker's name usually
        # begins; the model is the fallback for a shop that puts the kind in front of it —
        # m79 writes `Smartphone Apple iPhone 16 Plus…`, so the first two words are the kind
        # and the maker is third, and 79 listings with a barcode and a good model could not
        # be placed for want of a brand nobody stated.
        for source in ((reading.title or "").split(), (reading.model or "").split()):
            found = await self._named_by(source)
            if found is not None:
                return found
        # And from the other end. A whole supplier feed at m79 writes the maker last, in
        # front of the shop's own suffix: `MOBILE PHONE GALAXY FOLD7/512GB SM-F966B SAMSUNG
        # Mobilais Telefons`. Only the last few words, and one at a time, because a word
        # anywhere in a title that happens to be a maker's name is not a claim that the
        # maker made this — `Case for iPhone` is the shape that would go wrong.
        return await self._named_at_the_end((reading.title or "").split())

    async def _named_at_the_end(self, words: list[str]) -> Brand | None:
        """The maker a title ends with, behind whatever the shop appends to everything."""
        for word in reversed(words[-4:]):
            found = await self._named_by([word])
            if found is not None:
                return found
        return None

    async def _named_by(self, words: list[str]) -> Brand | None:
        """The maker the first word or two of these words name, if exactly one does."""
        for take in (2, 1):
            if len(words) < take:
                continue
            try:
                normalized = normalize_brand(" ".join(words[:take]))
            except ValueError:
                continue
            found = list(
                (
                    await self.session.execute(
                        select(Brand)
                        .join(BrandAlias, BrandAlias.brand_id == Brand.id)
                        .where(BrandAlias.alias_normalized == normalized)
                    )
                )
                .scalars()
                .unique()
            )
            if len(found) == 1:
                return found[0]
        return None

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
            # No field at all is not a shop stating a brand correctly, so the title is
            # weighed here for the same reason it is weighed below and with less risk:
            # there is nothing to second-guess. m79.lv is why — it states a maker on 28% of
            # its listings and names one in the title of almost all of them, and without
            # this 425 fully-read phones could not become a catalogue entry.
            named = await self._brand_from_title(reading)
            if named is not None:
                return BrandLookup(named, "resolved_title", [named.id])
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
            # The field names a maker nobody has heard of, and the title may name one we
            # have. Only then: a field that resolves is never second-guessed, and a field
            # that resolves to two is a question the judge answers, not this.
            named = await self._brand_from_title(reading)
            if named is not None:
                return BrandLookup(named, "resolved_title", [named.id])
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

    # --- starting the catalogue ---

    async def promote(self, offer_id: int) -> MatchOutcome:
        """Make the variant this listing was looking for, and let the ladder place it.

        The catalogue has to start somewhere, and the only thing that knows what is in the
        shops is the shops. A listing that carries a barcode, a brand we recognise and a
        category is a listing we can build a catalogue entry out of.

        Deliberately not a new kind of match. The variant is created and then the ordinary
        ladder runs, so the link records the rung that actually fired — a barcode, usually —
        rather than a special method that means "we made this from itself". Where the
        variant came from is what the audit trail is for.
        """
        offer = await self._offer(offer_id)
        reading = await self._reading(offer_id)
        if reading is None:
            raise ValidationError(
                f"Offer {offer_id} has not been read yet", code="nothing_to_match"
            )

        audit.set_target("offer", offer_id)
        variant = await self._variant_from(offer, reading)
        outcome = await self._decide(offer, reading)
        audit.record_changes(
            promoted_to_variant=variant.id,
            model=variant.model,
            matched=outcome.matched,
            method=outcome.method.value if outcome.method else None,
        )
        return outcome

    async def promote_queue(self, *, limit: int = 100) -> PromotionReport:
        """Start the catalogue from the listings that can be identified, and no others.

        A variant made from a junk listing cannot afterwards be told from a real one, so
        this takes only what carries a barcode and comes from a channel we trust. The rest
        stay queued, where somebody can look at them.

        Each candidate is matched before it is promoted, because the one before it may have
        just created the variant it needed — which is the first thing this system has ever
        been able to do.
        """
        rows = (
            await self.session.scalars(
                select(MatchQueue)
                .where(MatchQueue.reason == Reason.SIGNALS_UNMATCHED.value)
                .order_by(MatchQueue.offer_id)
                .limit(limit)
            )
        ).all()

        promoted = matched = 0
        reasons: Counter[str] = Counter()
        for row in rows:
            reading = await self._reading(row.offer_id)
            if reading is None:
                reasons["not_read"] += 1
                continue
            offer = await self._offer(row.offer_id)

            # It may already have what it needs: the listing before it in this very pass
            # could have created the variant.
            outcome = await self._decide(offer, reading)
            if outcome.matched:
                matched += 1
                continue

            refusal = await self._why_not_promotable(offer, reading)
            if refusal is not None:
                reasons[refusal] += 1
                continue

            try:
                # A savepoint per listing, for the same reason the batch ingestion has one:
                # the services here answer a conflict by rolling the request back, and a
                # rollback in the middle of a bounded loop does not undo one listing — it
                # empties the transaction and leaves every ORM row the loop still holds
                # expired. The pass then fails on the *next* listing, somewhere unrelated,
                # with a lazy load that cannot run. Undoing only the listing that failed is
                # what lets the other nine hundred stand.
                async with self.session.begin_nested():
                    await self._variant_from(offer, reading)
            except AppError as error:
                reasons[error.code] += 1
                continue
            except IntegrityError:
                # A clash the service did not name — two listings racing for one slug, a
                # barcode already spoken for. One listing's problem, not the pass's.
                reasons["conflict"] += 1
                continue

            promoted += 1
            await self._decide(offer, reading)

        audit.record_changes(
            considered=len(rows), promoted=promoted, matched=matched, **dict(reasons)
        )
        return PromotionReport(
            considered=len(rows),
            promoted=promoted,
            matched=matched,
            skipped=sum(reasons.values()),
            reasons=dict(reasons),
        )

    async def merge_duplicates(self, *, limit: int = 100) -> MergeReport:
        """Fold together the catalogue entries a barcode says are one product.

        The catalogue splits a phone in two whenever two shops write its model differently
        and neither listing had a barcode to say otherwise at the time: `PHONE WAVE 7C` and
        `Wave 7C`, `Edge 70 Fusion` and `Motorola Edge 70 Fusion`, `Moto G37` and
        `Moto G37 5G`. Afterwards a listing on each side carries the same barcode, and that
        is not an opinion — it is the strongest signal this system has, contradicting itself.

        Only a barcode. A part number is not enough and never will be: `SM-S948B` covers
        every colour and capacity of one phone, so two entries sharing one are usually two
        real configurations rather than one written twice.

        The entry that already holds the barcode survives, because it is the one the first
        rung will keep finding; failing that the one carrying more listings, which loses
        less if this is ever undone.
        """
        pairs = await self._barcode_duplicates(limit=limit)
        merged, reasons, folded = 0, Counter(), []
        catalog = CatalogService(self.session)
        for gtin, first, second in pairs:
            survivor, loser = await self._which_survives(gtin, first, second)
            try:
                async with self.session.begin_nested():
                    await catalog.merge_variants(
                        loser,
                        survivor,
                        reason=f"both held a listing carrying {gtin}",
                        decided_by="rule",
                    )
            except AppError as error:
                reasons[error.code] += 1
                continue
            except IntegrityError:
                reasons["conflict"] += 1
                continue
            merged += 1
            folded.append(f"{loser} -> {survivor}")

        audit.record_changes(found=len(pairs), merged=merged, **dict(reasons))
        return MergeReport(
            found=len(pairs),
            merged=merged,
            refused=sum(reasons.values()),
            reasons=dict(reasons),
            pairs=folded,
        )

    async def rebuild_named_from_a_stale_reading(self, *, limit: int = 100) -> RenameReport:
        """Rename the entries whose only listing no longer reads the way they were named.

        A catalogue entry built from one listing takes its model from that listing's
        reading. When the reading improves the entry does not follow: discover.lv wrote its
        working memory into 217 of its model strings, so `Pixel 10` became `Pixel 10 12`,
        `Pixel 10 16` and so on — one entry per memory size. Fixing the rule fixed the
        reading and left 189 entries standing under names nothing reads any more.

        Only an entry with exactly one listing on it. Two shops agreeing on an entry is
        evidence the name is good enough, and one of them disagreeing about a `5G` suffix
        is not a reason to rename what they share.

        A rename that collides is the answer rather than the problem: the identity key says
        the entry has just become one that already exists, and the two are merged.
        """
        stale = await self._stale_names(limit=limit)
        renamed = merged = 0
        reasons: Counter[str] = Counter()
        catalog = CatalogService(self.session)

        for variant_id, model in stale:
            try:
                async with self.session.begin_nested():
                    await catalog.update_variant(variant_id, VariantUpdate(model=model[:200]))
                renamed += 1
            except ConflictError as error:
                twin = (error.details or {}).get("variant_id")
                if twin is None:
                    reasons[error.code] += 1
                    continue
                try:
                    async with self.session.begin_nested():
                        await catalog.merge_variants(
                            variant_id,
                            twin,
                            reason=f"renamed to {model!r} and became an entry that existed",
                            decided_by="rule",
                        )
                    merged += 1
                except AppError as failure:
                    reasons[failure.code] += 1
                except IntegrityError:
                    reasons["conflict"] += 1
            except AppError as error:
                reasons[error.code] += 1
            except IntegrityError:
                reasons["conflict"] += 1

        audit.record_changes(found=len(stale), renamed=renamed, merged=merged, **dict(reasons))
        return RenameReport(
            found=len(stale),
            renamed=renamed,
            merged=merged,
            refused=sum(reasons.values()),
            reasons=dict(reasons),
        )

    async def _stale_names(self, *, limit: int) -> list[tuple[int, str]]:
        """Entries with one listing, named after a reading that listing has outgrown."""
        newest = (
            select(
                OfferMatch.variant_id.label("variant_id"),
                NormalizedOffer.model.label("model"),
                func.row_number()
                .over(
                    partition_by=RawOffer.offer_id,
                    order_by=(RawOffer.fetched_at.desc(), NormalizedOffer.id.desc()),
                )
                .label("rank"),
            )
            .join(RawOffer, RawOffer.id == NormalizedOffer.raw_offer_id)
            .join(
                OfferMatch,
                (OfferMatch.offer_id == RawOffer.offer_id) & (OfferMatch.superseded_at.is_(None)),
            )
            .where(NormalizedOffer.model.is_not(None))
            .subquery()
        )
        alone = (
            select(OfferMatch.variant_id)
            .where(OfferMatch.superseded_at.is_(None))
            .group_by(OfferMatch.variant_id)
            .having(func.count() == 1)
            .subquery()
        )
        rows = await self.session.execute(
            select(newest.c.variant_id, newest.c.model)
            .join(Variant, Variant.id == newest.c.variant_id)
            .join(alone, alone.c.variant_id == newest.c.variant_id)
            .where(newest.c.rank == 1, Variant.model != newest.c.model)
            .limit(limit)
        )
        return [(variant_id, model) for variant_id, model in rows.all()]

    async def _barcode_duplicates(self, *, limit: int) -> list[tuple[str, int, int]]:
        """Barcodes whose listings sit on two catalogue entries, as (barcode, one, other)."""
        newest = (
            select(
                NormalizedOffer.gtin.label("gtin"),
                OfferMatch.variant_id.label("variant_id"),
                func.row_number()
                .over(
                    partition_by=RawOffer.offer_id,
                    order_by=(RawOffer.fetched_at.desc(), NormalizedOffer.id.desc()),
                )
                .label("rank"),
            )
            .join(RawOffer, RawOffer.id == NormalizedOffer.raw_offer_id)
            .join(
                OfferMatch,
                (OfferMatch.offer_id == RawOffer.offer_id) & (OfferMatch.superseded_at.is_(None)),
            )
            .where(NormalizedOffer.gtin.is_not(None))
            .subquery()
        )
        rows = await self.session.execute(
            select(newest.c.gtin, func.array_agg(func.distinct(newest.c.variant_id)))
            .where(newest.c.rank == 1)
            .group_by(newest.c.gtin)
            .having(func.count(func.distinct(newest.c.variant_id)) == 2)
            .limit(limit)
        )
        return [(gtin, variants[0], variants[1]) for gtin, variants in rows.all()]

    async def _which_survives(self, gtin: str, first: int, second: int) -> tuple[int, int]:
        """The entry that keeps its id, and the one folded into it."""
        holding = await self.session.scalar(
            select(VariantGtin.variant_id).where(
                VariantGtin.gtin == gtin, VariantGtin.variant_id.in_((first, second))
            )
        )
        if holding is not None:
            return (holding, second if holding == first else first)

        counts = {
            variant_id: await self.session.scalar(
                select(func.count())
                .select_from(OfferMatch)
                .where(OfferMatch.variant_id == variant_id, OfferMatch.superseded_at.is_(None))
            )
            for variant_id in (first, second)
        }
        return (first, second) if counts[first] >= counts[second] else (second, first)

    async def _why_not_promotable(self, offer: Offer, reading: NormalizedOffer) -> str | None:
        """The bar a listing has to clear before it becomes a catalogue entry.

        A barcode, **or** an identity complete enough that another shop would arrive at the
        same one. The first was the only bar for as long as it was the only thing two shops
        could agree on — and that left a whole shop unable to contribute anything, because
        1a.lv publishes no barcode at all: 27 of its listings sat in the queue fully read,
        brand resolved, model, capacity and colour all known, invisible to the catalogue.

        The second bar is not a weaker one. It asks for every axis the *category* calls
        identity-bearing, which is what `identity_key` is computed from and what makes it
        unique in the table: two shops that both describe the phone completely arrive at the
        same key and meet there. A junk listing clears neither bar — it has no model and no
        colour — and a category that declares no axes has no second bar at all, because
        requiring nothing would let anything through.
        """
        source = await self._source_of(offer)
        if source is None or source.trust != "high":
            return "source_not_trusted"
        if reading.gtin:
            return None
        identity = await self._identity(offer, reading)
        if await self._identity_is_complete(identity, source.category_id):
            return None
        return "no_barcode"

    async def _identity_is_complete(
        self, identity: dict[str, Any], category_id: int | None
    ) -> bool:
        """Whether the reading names every axis its category says tells its products apart."""
        if category_id is None:
            return False
        required = {
            key
            for (key,) in await self.session.execute(
                select(Attribute.key)
                .join(CategoryAttribute, CategoryAttribute.attribute_id == Attribute.id)
                .where(
                    CategoryAttribute.category_id == category_id,
                    CategoryAttribute.identity_bearing.is_(True),
                )
            )
        }
        if not required:
            return False
        named = {key for key, value in identity.items() if value not in (None, "")}
        return required <= named

    async def _variant_from(self, offer: Offer, reading: NormalizedOffer) -> Variant:
        """Build a catalogue entry out of one listing, identifiers and all."""
        lookup = await self._resolve_brand(offer, reading)
        if lookup.brand is None:
            raise ValidationError(
                "The brand has to be settled before a variant can be made from this listing",
                code="brand_unresolved",
            )

        source = await self._source_of(offer)
        if source is None or source.category_id is None:
            raise ValidationError(
                "The channel does not say which category it collects, so there is nothing"
                " to file this under",
                code="category_unknown",
            )

        model = (reading.model or "").strip()
        if not model:
            # Deliberately no fallback to the title. A shop title is a sentence —
            # `Tālrunis Oukitel WP58 Pro 6,7" viedtālrunis Dual SIM Android 15 5G USB…` —
            # and a catalogue entry named after one is worse than no entry: it cannot be
            # searched for, it groups with nothing, and it looks like a real product. A
            # channel with no model rule leaves its listings in the queue, where the gap is
            # visible, and they still match variants another shop created by barcode.
            raise ValidationError(
                "This channel does not read a model, and a shop's title is not one",
                code="no_model",
            )

        catalog = CatalogService(self.session)
        variant = await catalog.create_variant(
            VariantCreate(
                brand_id=lookup.brand.id,
                category_id=source.category_id,
                model=model[:200],
                product_id=await self._family(
                    catalog, lookup.brand.id, source.category_id, model[:200]
                ),
            )
        )
        if reading.gtin:
            await catalog.add_gtin(variant.id, IdentifierCreate(value=reading.gtin))
        if reading.mpn:
            await catalog.add_mpn(variant.id, IdentifierCreate(value=reading.mpn))
        await self._carry_identity(catalog, variant.id, await self._identity(offer, reading))

        # The trail is where a catalogue entry's origin lives: nothing on the row says
        # which listing it was built from, and that is the first thing anybody will ask.
        audit.set_target("variant", variant.id)
        audit.record_changes(created_from_offer=offer.id, source=source.slug)
        return await self.session.get(Variant, variant.id)

    async def _family(
        self, catalog: CatalogService, brand_id: int, category_id: int, model: str
    ) -> int:
        """The product this variant belongs to, made if it is the first of its family.

        A brand and a model string name a **family** — `Galaxy S26 Ultra 5G` is the 256, the
        512 and the terabyte — which is what the product level is for. Matching on it as
        though it named one buyable thing is what filed fifteen listings and a thousand
        euros of price range as a single entry.

        The design note said grouping was a later, cheaper decision than creating a variant,
        and that inventing a family from a single data point would be a guess. It is not a
        guess here: the family is exactly what the model string already said, and the
        alternative is a catalogue where every variant is an orphan.
        """
        existing = await self.session.scalar(
            select(Product.id).where(
                Product.brand_id == brand_id,
                Product.category_id == category_id,
                func.lower(Product.model) == model.lower(),
            )
        )
        if existing is not None:
            return existing
        product = await catalog.create_product(
            ProductCreate(brand_id=brand_id, category_id=category_id, model=model)
        )
        return product.id

    async def _carry_identity(
        self,
        catalog: CatalogService,
        variant_id: int,
        identity: dict[str, Any],
        *,
        only_if_absent: bool = False,
    ) -> None:
        """Put the axes the reading worked out onto the variant it just became.

        Without this a variant is a brand and a model string and nothing else, and every
        capacity of one phone is the same catalogue entry — which is exactly what happened:
        `Galaxy S26 Ultra 5G` matched fifteen listings spanning three capacities and a
        thousand euros. The axes are what `identity_key` is computed from, and setting them
        is what makes that key mean anything.
        """
        for key, value in identity.items():
            attribute = await self.session.scalar(select(Attribute).where(Attribute.key == key))
            if attribute is None:
                # An axis a rule produced and nobody entered in the registry. Not an error:
                # the registry is filled by a person and the rules run ahead of them.
                continue
            if attribute.value_type == "number" and isinstance(value, int | float | Decimal):
                await catalog.set_variant_attribute(
                    variant_id,
                    VariantAttributeSet(
                        attribute_id=attribute.id,
                        value_num=Decimal(str(value)),
                        source_kind=SourceKind.PARAM,
                        origin=ValueOrigin.CONSENSUS,
                    ),
                    only_if_absent=only_if_absent,
                )
                continue

            if attribute.value_type == "enum" and isinstance(value, str):
                # The rule already resolved the shop's word to a canonical one — that is
                # what `attribute_value_aliases` is for — so this only has to find the row
                # it named. A value nobody entered is skipped for the same reason a whole
                # attribute is: the rules run ahead of whoever fills the registry.
                row = await self.session.scalar(
                    select(AttributeValue).where(
                        AttributeValue.attribute_id == attribute.id,
                        AttributeValue.canonical == value,
                    )
                )
                if row is None:
                    continue
                await catalog.set_variant_attribute(
                    variant_id,
                    VariantAttributeSet(
                        attribute_id=attribute.id,
                        value_id=row.id,
                        source_kind=SourceKind.PARAM,
                        origin=ValueOrigin.CONSENSUS,
                    ),
                    only_if_absent=only_if_absent,
                )

    async def _source_of(self, offer: Offer) -> Source | None:
        return await self.session.scalar(
            select(Source)
            .join(RawOffer, RawOffer.source_id == Source.id)
            .where(RawOffer.offer_id == offer.id)
            .order_by(RawOffer.fetched_at.desc())
            .limit(1)
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

    async def judge_ambiguous(self, *, limit: int = 50) -> JudgeReport:
        """Put the entries nobody could choose between in front of the judge.

        Only `ambiguous`, and only because the corpus has been asked first and cannot
        answer. These listings reach the model rung, find several entries that differ in one
        axis and agree on every other, and carry nothing to tell them apart — almost always
        a colour the maker invented a name for. Counting what the shops call it settles some
        of those names and proves the rest cannot be settled that way at all: `Canyon` is
        pink on a Google and orange on an Oppo, both by two shops, so no global registry row
        can hold it. What is left is to ask.

        A verdict places the listing rather than being re-run like a brand's, because no
        rung consults it: the model rung found the candidates and the judge chose among
        them, so that is exactly what the link records — `method` the rung that fired,
        `decided_by` the judge.
        """
        rows = (
            await self.session.scalars(
                select(MatchQueue)
                .where(MatchQueue.reason == Reason.AMBIGUOUS.value)
                .order_by(MatchQueue.offer_id)
                .limit(limit)
            )
        ).all()

        requests: list[VariantRequest] = []
        for row in rows:
            reading = await self._reading(row.offer_id)
            if reading is None:
                continue
            candidates = [
                entry["variant_id"]
                for entry in row.candidates
                if entry.get("variant_id") is not None
            ]
            requests.append(
                VariantRequest(
                    key=row.offer_id,
                    title=reading.title,
                    brand=reading.brand_raw,
                    model=reading.model,
                    variant_ids=candidates,
                )
            )

        verdicts, report = await self.judge.decide_variants(requests)

        placed = 0
        for offer_id, verdict in verdicts.items():
            if not verdict.accepted or verdict.variant_id is None:
                continue
            offer = await self._offer(offer_id)
            await self._link(
                offer,
                verdict.variant_id,
                Method.BRAND_MODEL,
                {
                    "signal": "model",
                    "judged": verdict.choice,
                    "confidence": str(verdict.confidence),
                },
                decided_by=DecidedBy.JUDGE,
            )
            placed += 1

        report = report.model_copy(update={"placed": placed})
        audit.record_changes(**report.model_dump(mode="json"))
        return report

    async def judge_colours(self, *, limit: int = 50) -> JudgeReport:
        """Buy the colour for the listings a colour is the only thing missing from.

        The third question, and the one that unblocks the second. `variant_choice` refused
        30 listings of 30 and was right to: at confidence 1.00 a `Coralred` Samsung is
        neither of the black and grey entries the catalogue holds. Those listings do not
        need an entry chosen for them, they need one made — and what stops that is the
        promotion bar, which asks for every axis the category calls identity-bearing.
        Colour is one, the shop wrote it in its title rather than in a field, and no rule
        may cut it out of there.

        Both buckets, because it is the same gap wearing two shapes: `ambiguous` is a
        listing whose colour would have told two entries apart, `signals_unmatched` one
        whose colour is all that keeps it from becoming an entry of its own. A listing with
        no model is skipped — a colour would not save it, and a shop's title is not a model.

        Re-run rather than placed, as brands are: the verdict is in the store, so the ladder
        consults it on its own and takes whichever rung actually fires.
        """
        rows = (
            await self.session.scalars(
                select(MatchQueue)
                .where(
                    MatchQueue.reason.in_((Reason.AMBIGUOUS.value, Reason.SIGNALS_UNMATCHED.value))
                )
                .order_by(MatchQueue.offer_id)
                .limit(limit)
            )
        ).all()

        requests: list[ColourRequest] = []
        for row in rows:
            reading = await self._reading(row.offer_id)
            if reading is None or not reading.model:
                continue
            if (reading.identity or {}).get(COLOUR_KEY):
                continue
            requests.append(
                ColourRequest(
                    key=row.offer_id,
                    title=reading.title,
                    brand=reading.brand_raw,
                    model=reading.model,
                )
            )

        verdicts, report = await self.judge.decide_colours(requests)

        placed = 0
        for offer_id, verdict in verdicts.items():
            if not verdict.accepted:
                continue
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
        """The newest reading from a pass that carried the catalogue — not simply the newest.

        A cheap pass observes a price and a stock flag and nothing else; that is what
        `delivers_quick` declares and why it is cheap. Its reading therefore has no barcode,
        no part number and no model, and taken as the current one it erases the identity the
        expensive pass collected. Measured the hard way: a shop went from 1393 of 1396
        products carrying a barcode to none, and every one of them stopped matching, because
        a two-minute price refresh had run after the four-minute catalogue pass.

        Nothing is lost by passing over it. A price is not read from here — it is on the
        offer row, and updating that row is exactly what the cheap pass is for.

        A reading with no run at all is a sample somebody loaded by hand, which is a full
        observation and counts.
        """
        return await self.session.scalar(
            select(NormalizedOffer)
            .join(RawOffer, RawOffer.id == NormalizedOffer.raw_offer_id)
            .outerjoin(Run, Run.id == RawOffer.run_id)
            .where(
                RawOffer.offer_id == offer_id,
                or_(Run.id.is_(None), Run.kind != Kind.QUICK.value),
            )
            .order_by(RawOffer.fetched_at.desc(), NormalizedOffer.id.desc())
            .limit(1)
        )
