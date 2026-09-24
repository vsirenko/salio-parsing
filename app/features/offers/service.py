"""Taking in what a shop served, and reading it."""

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError, ValidationError
from app.db.models import (
    Attribute,
    AttributeAlias,
    AttributeValue,
    AttributeValueAlias,
    Brand,
    Category,
    CategoryAlias,
    CategoryAttribute,
    Market,
    MatchQueue,
    ModelAlias,
    NormalizedOffer,
    Offer,
    OfferMatch,
    Product,
    RawOffer,
    Run,
    Seller,
    Shop,
    Source,
    Variant,
    VariantAttribute,
)
from app.db.query import offer_is_listed, ordered, paginated_rows
from app.features.brands.normalization import normalize_brand
from app.features.offers.normalization import (
    Vocabulary,
    barcodes,
    content_hash,
    read,
    version_for,
)
from app.features.offers.schemas import (
    BatchFailure,
    BatchOffer,
    BatchResult,
    Coverage,
    IngestResult,
    NamedRef,
    NormalizedOfferRead,
    OfferRead,
    OfferTrace,
    PlacedOn,
    RawOfferBatch,
    RawOfferIngest,
    RawOfferRead,
    SellerRef,
    ShopRef,
    TraceEntry,
    TraceMatch,
    TraceObservation,
    TraceQueue,
    TraceReading,
    TraceStep,
)
from app.features.prices.service import PriceService
from app.features.runs.schemas import Kind
from app.schemas.pagination import Pagination

# What a run's coverage is counted over. Availability is not here: it has a value for
# every reading, `unknown` included, so counting it would report 1.00 forever.
COUNTED = ("title", "brand_raw", "gtin", "mpn", "model", "price")


# The registry is looked up by key, and this is the only one a reading needs by name so
# far. A second would be a reason to carry a set rather than to add another constant.
COLOR_KEY = "color"


def _found(reading: NormalizedOffer | None) -> list[str]:
    """Which of the fields worth counting this reading actually has."""
    if reading is None:
        return []
    return [field for field in COUNTED if getattr(reading, field, None) is not None]


class OfferService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # One query per category for the life of a request, not one per listing: a batch
        # carries five hundred of them and they all want the same words.
        self._vocabularies: dict[int, Vocabulary] = {}
        # One lookup per run for the life of a request, not one per observation.
        self._run_kinds: dict[int, str | None] = {}
        # Ingestion records a price change; it does not decide when one counts. That rule
        # is the same knowledge as what the history means, so it lives with the table.
        self.prices = PriceService(session)

    # --- taking it in ---

    async def ingest(self, source_id: int, payload: RawOfferIngest) -> IngestResult:
        source = await self._source(source_id)
        shop = await self._shop(source.shop_id)
        await self._market(payload.market_code)

        result = await self._ingest_one(source, shop, payload.market_code, payload, run_id=None)
        audit.set_target("offer", result.offer_id)
        audit.record_changes(
            source_id=source.id, external_id=payload.external_id, stored=result.stored
        )
        return result

    async def ingest_batch(self, source_id: int, batch: RawOfferBatch) -> BatchResult:
        """Many observations of one channel, in one transaction and one audit entry.

        Partial on purpose: one malformed card should not throw away the pass that
        collected the other eight hundred and ninety-nine. Each item is written inside a
        savepoint, so a failure undoes that item and leaves the rest of the batch standing
        — a plain flush would abort the whole transaction on the first bad row.
        """
        if len(batch.offers) > settings.max_batch_offers:
            raise ValidationError(
                f"A batch carries at most {settings.max_batch_offers} observations;"
                f" this one has {len(batch.offers)}. Split it.",
                code="batch_too_large",
            )

        source = await self._source(source_id)
        shop = await self._shop(source.shop_id)
        await self._market(batch.market_code)
        if batch.run_id is not None and await self.session.get(Run, batch.run_id) is None:
            raise NotFoundError(f"Run {batch.run_id} not found")

        accepted = stored = created = 0
        present: Counter[str] = Counter()
        failures: list[BatchFailure] = []
        for item in batch.offers:
            try:
                async with self.session.begin_nested():
                    result = await self._ingest_one(
                        source, shop, batch.market_code, item, run_id=batch.run_id
                    )
            except AppError as error:
                failures.append(
                    BatchFailure(external_id=item.external_id, code=error.code, message=str(error))
                )
                continue
            except IntegrityError as error:
                failures.append(
                    BatchFailure(
                        external_id=item.external_id,
                        code="conflict",
                        message=type(error.orig).__name__ if error.orig else "conflict",
                    )
                )
                continue

            accepted += 1
            stored += result.stored
            created += result.offer_created
            present.update(result.read)

        # One entry for the batch, not one per observation. The trail exists to show what
        # an administrator did, and a crawl would bury that under a wall of arrivals.
        audit.set_target("source", source.id)
        audit.record_changes(
            ingested_batch=len(batch.offers),
            run_id=batch.run_id,
            accepted=accepted,
            failed=len(failures),
            stored=stored,
        )
        return BatchResult(
            accepted=accepted,
            failed=len(failures),
            stored=stored,
            offers_created=created,
            coverage={field: round(count / accepted, 4) for field, count in sorted(present.items())}
            if accepted
            else {},
            failures=failures,
        )

    async def _ingest_one(
        self,
        source: Source,
        shop: Shop,
        market_code: str,
        payload: RawOfferIngest | BatchOffer,
        *,
        run_id: int | None,
    ) -> IngestResult:
        seller = await self._seller_for(shop, payload.seller_external_id)

        offer, created = await self._offer_for(seller.id, market_code, payload)
        digest = content_hash(payload.payload)

        existing = await self.session.scalar(
            select(RawOffer).where(RawOffer.offer_id == offer.id, RawOffer.content_hash == digest)
        )
        now = datetime.now(UTC)
        offer.last_seen_at = now

        if existing is not None:
            # The page has not changed. Bumping a timestamp is the whole write, which is
            # what keeps this table proportional to how much the world changes rather than
            # to how often we look at it.
            existing.last_seen_at = now
            await self.session.flush()

            # Unchanged bytes still get read again when the rules have moved on. Without
            # this a reparse re-runs the parser and stops there: the payload comes out
            # identical, the short circuit fires, and a shop that just gained a rule keeps
            # the reading it had before anybody wrote one.
            #
            # The version is not enough on its own, and finding that out cost an afternoon.
            # A reading is a function of the rules *and* of the vocabulary handed to them,
            # and `ruleset_version` only tracks the first: 117 colour spellings entered in
            # the registry changed nothing, because no code had moved. So a reparse — whose
            # whole purpose is to re-read what is stored with the reader as it is now —
            # always recomputes, and the version check is left to ordinary ingestion, where
            # unchanged bytes genuinely should not cost work.
            reading = await self._current_reading(existing.id)
            if (
                reading is None
                or await self._is_reparse(run_id)
                or reading.ruleset_version
                != version_for(
                    source.slug,
                    shop_slug=await self._shop_slug(source),
                    category=await self._category_slug(source),
                )
            ):
                reading = await self._store_reading(existing, source=source)
                await self._apply_reading_to_offer(offer, reading, raw=existing)
            return IngestResult(
                offer_id=offer.id,
                raw_offer_id=existing.id,
                normalized_offer_id=reading.id if reading else None,
                offer_created=created,
                stored=False,
                read=_found(reading),
            )

        raw = RawOffer(
            offer_id=offer.id,
            source_id=source.id,
            run_id=run_id,
            payload=payload.payload,
            content_hash=digest,
            fetched_at=now,
            last_seen_at=now,
        )
        self.session.add(raw)
        await self.session.flush()

        reading = await self._store_reading(raw, source=source)
        await self._apply_reading_to_offer(offer, reading, raw=raw)
        await self._record_series(offer, reading, source_id=source.id)
        await self.session.flush()

        return IngestResult(
            offer_id=offer.id,
            raw_offer_id=raw.id,
            normalized_offer_id=reading.id,
            offer_created=created,
            stored=True,
            read=_found(reading),
        )

    async def renormalize(self, raw_offer_id: int) -> NormalizedOfferRead:
        """Read stored bytes again with the ruleset of today.

        The property the pipeline is built for: a rule change is re-applied to what is
        already held rather than re-crawled, and the new reading can be compared with the
        old one before anything downstream moves.
        """
        raw = await self.session.get(RawOffer, raw_offer_id)
        if raw is None:
            raise NotFoundError(f"Raw offer {raw_offer_id} not found")

        audit.set_target("offer", raw.offer_id)
        source = await self._source(raw.source_id)
        reading = await self._store_reading(raw, source=source)
        offer = await self.session.get(Offer, raw.offer_id)
        await self._apply_reading_to_offer(offer, reading, raw=raw)
        if offer is not None:
            # A re-read can change what we think was quoted. If it does, that is a change
            # in the series like any other.
            await self._record_series(offer, reading, source_id=raw.source_id)
        await self.session.flush()
        audit.record_changes(raw_offer_id=raw_offer_id, ruleset_version=reading.ruleset_version)
        return NormalizedOfferRead.model_validate(reading)

    # --- the path of one listing ---

    async def trace(self, offer_id: int) -> OfferTrace:
        """One listing from the shop's bytes to the catalogue, with every step shown.

        Reads what is stored and recomputes the reading with a trace; writes nothing. The
        other features' tables are read directly, which is allowed — every model lives in
        `app/db/models.py` — so this imports no matching or catalogue code.
        """
        offer = await self.session.get(Offer, offer_id)
        if offer is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        shop = await self.session.scalar(
            select(Shop.name)
            .join(Seller, Seller.shop_id == Shop.id)
            .where(Seller.id == offer.seller_id)
        )

        # The newest observation from a pass that carried the catalogue, the rule the
        # matcher reads by: a cheap pass carries a price and nothing else.
        raw = await self.session.scalar(
            select(RawOffer)
            .outerjoin(Run, Run.id == RawOffer.run_id)
            .where(RawOffer.offer_id == offer_id, (Run.kind.is_(None)) | (Run.kind != "quick"))
            .order_by(RawOffer.fetched_at.desc(), RawOffer.id.desc())
            .limit(1)
        )
        source = await self.session.get(Source, raw.source_id) if raw else None
        observation = stored = now = None
        steps: list[dict[str, Any]] = []
        stale = False
        if raw is not None and source is not None:
            run = await self.session.get(Run, raw.run_id) if raw.run_id else None
            observation = TraceObservation(
                raw_offer_id=raw.id,
                run_id=raw.run_id,
                run_kind=run.kind if run else None,
                fetched_at=raw.fetched_at,
                payload=raw.payload,
            )
            reading = await self.session.scalar(
                select(NormalizedOffer)
                .where(NormalizedOffer.raw_offer_id == raw.id)
                .order_by(NormalizedOffer.id.desc())
                .limit(1)
            )
            fields = read(
                raw.payload,
                source_slug=source.slug,
                shop_slug=await self._shop_slug(source),
                category=await self._category_slug(source),
                vocabulary=await self._vocabulary(source),
                trace=steps,
            )
            now = TraceReading(ruleset_version=fields["ruleset_version"], fields=_plain(fields))
            if reading is not None:
                held = {key: getattr(reading, key, None) for key in fields}
                stored = TraceReading(ruleset_version=reading.ruleset_version, fields=_plain(held))
                stale = stored.fields != now.fields
        category = (
            await self.session.scalar(
                select(Category.slug).where(Category.id == source.category_id)
            )
            if source is not None and source.category_id is not None
            else None
        )

        matches = (
            await self.session.scalars(
                select(OfferMatch)
                .where(OfferMatch.offer_id == offer_id)
                .order_by(OfferMatch.decided_at.desc(), OfferMatch.id.desc())
            )
        ).all()
        current = next((m for m in matches if m.superseded_at is None), None)
        queued = await self.session.get(MatchQueue, offer_id)

        return OfferTrace(
            offer_id=offer.id,
            shop=shop or "",
            source=source.slug if source else None,
            category=category,
            url=offer.url,
            price=offer.price,
            currency_code=offer.currency_code,
            availability=offer.availability,
            observation=observation,
            stored=stored,
            now=now,
            stale=stale,
            steps=[TraceStep(**step) for step in steps],
            match=_trace_match(current) if current else None,
            history=[_trace_match(m) for m in matches if m is not current],
            queue=(
                TraceQueue(
                    reason=queued.reason,
                    candidates=queued.candidates or [],
                    attempts=queued.attempts,
                    last_attempt_at=queued.last_attempt_at,
                )
                if queued is not None
                else None
            ),
            entry=await self._trace_entry(current.variant_id) if current else None,
        )

    async def _trace_entry(self, variant_id: int) -> TraceEntry | None:
        variant = await self.session.get(Variant, variant_id)
        if variant is None:
            return None
        product = (
            await self.session.get(Product, variant.product_id) if variant.product_id else None
        )
        axes = {
            key: text if text is not None else canonical if canonical is not None else _axis(number)
            for key, text, canonical, number in (
                await self.session.execute(
                    select(
                        Attribute.key,
                        VariantAttribute.value_text,
                        AttributeValue.canonical,
                        VariantAttribute.value_num,
                    )
                    .join(Attribute, Attribute.id == VariantAttribute.attribute_id)
                    .outerjoin(AttributeValue, AttributeValue.id == VariantAttribute.value_id)
                    .where(VariantAttribute.variant_id == variant_id)
                )
            ).all()
        }
        by_shop = dict(
            (
                await self.session.execute(
                    select(Shop.name, func.count())
                    .select_from(OfferMatch)
                    .join(Offer, Offer.id == OfferMatch.offer_id)
                    .join(Seller, Seller.id == Offer.seller_id)
                    .join(Shop, Shop.id == Seller.shop_id)
                    .where(OfferMatch.variant_id == variant_id, OfferMatch.superseded_at.is_(None))
                    .group_by(Shop.name)
                )
            ).all()
        )
        return TraceEntry(
            variant_id=variant.id,
            model=variant.model,
            title=variant.title,
            identity_key=variant.identity_key,
            axes=axes,
            product_id=product.id if product else None,
            product_title=product.title if product else None,
            listings_by_shop=by_shop,
        )

    # --- reading it back ---

    async def list_offers(
        self,
        pagination: Pagination,
        *,
        seller_id: int | None = None,
        market_code: str | None = None,
        shop_ids: list[int] | None = None,
        variant_ids: list[int] | None = None,
        product_ids: list[int] | None = None,
        condition: str | None = None,
        listed: bool | None = None,
        match_states: list[str] | None = None,
        queue_reasons: list[str] | None = None,
        methods: list[str] | None = None,
        availabilities: list[str] | None = None,
        brand_ids: list[int] | None = None,
        category_ids: list[int] | None = None,
        price_min: Decimal | None = None,
        price_max: Decimal | None = None,
        search: str | None = None,
    ) -> tuple[list[OfferRead], int]:
        stmt = _offer_rows()
        if match_states:
            stmt = stmt.where(_match_state().in_(match_states))
        if queue_reasons:
            stmt = stmt.where(MatchQueue.reason.in_(queue_reasons))
        if methods:
            stmt = stmt.where(OfferMatch.method.in_(methods))
        if availabilities:
            stmt = stmt.where(Offer.availability.in_(availabilities))
        if brand_ids:
            stmt = stmt.where(Product.brand_id.in_(brand_ids))
        if category_ids:
            stmt = stmt.where(_category_id().in_(category_ids))
        if price_min is not None:
            stmt = stmt.where(Offer.price >= price_min)
        if price_max is not None:
            stmt = stmt.where(Offer.price <= price_max)
        if search and search.strip():
            text = search.strip()
            pattern = f"%{text}%"
            matches = [Offer.title.ilike(pattern), Offer.external_id.ilike(pattern)]
            if barcodes.valid(text):
                # Stored padded to fourteen digits, so an EAN-13 typed as printed is found.
                matches.append(Offer.gtin == barcodes.canonical(text))
            stmt = stmt.where(or_(*matches))
        if seller_id is not None:
            stmt = stmt.where(Offer.seller_id == seller_id)
        if market_code is not None:
            stmt = stmt.where(Offer.market_code == market_code.upper())
        if shop_ids:
            stmt = stmt.where(Shop.id.in_(shop_ids))
        if variant_ids:
            stmt = stmt.where(OfferMatch.variant_id.in_(variant_ids))
        if product_ids:
            stmt = stmt.where(Variant.product_id.in_(product_ids))
        if condition is not None:
            stmt = stmt.where(Offer.condition == condition)
        if listed is not None:
            stmt = stmt.where(offer_is_listed() if listed else ~offer_is_listed())

        stmt = ordered(
            stmt,
            pagination,
            {
                "id": Offer.id,
                "price": Offer.price,
                "last_seen_at": Offer.last_seen_at,
                "first_seen_at": Offer.first_seen_at,
                "shop": Shop.name,
                "title": Offer.title,
            },
            Offer.id,
        )
        rows, total = await paginated_rows(self.session, stmt, pagination)
        return [_offer_read(row) for row in rows], total

    async def get_offer(self, offer_id: int) -> OfferRead:
        row = (await self.session.execute(_offer_rows().where(Offer.id == offer_id))).first()
        if row is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        return _offer_read(row)

    async def list_observations(self, offer_id: int) -> list[RawOfferRead]:
        await self._offer(offer_id)
        rows = await self.session.scalars(
            select(RawOffer)
            .where(RawOffer.offer_id == offer_id)
            .order_by(RawOffer.fetched_at.desc())
        )
        return [RawOfferRead.model_validate(row) for row in rows]

    async def get_reading(self, raw_offer_id: int) -> NormalizedOfferRead:
        reading = await self._current_reading(raw_offer_id)
        if reading is None:
            raise NotFoundError(f"Raw offer {raw_offer_id} has not been read yet")
        return NormalizedOfferRead.model_validate(reading)

    async def coverage(self) -> Coverage:
        """What share of readings carry something a deterministic matcher can use.

        The measurement the whole design is downstream of. A barcode is the strongest
        signal; brand with a part number is the next; a brand alone narrows the field but
        decides nothing. If most rows land in the last bucket, the centre of the work moves
        to pulling identity out of free text and the matcher is the wrong thing to build
        first.
        """
        # The newest reading of each observation, rather than every reading under one
        # version: a ruleset is per source now, so filtering on a single constant would
        # silently drop every shop that has rules of its own — which is to say, the ones
        # read best.
        current = (
            select(NormalizedOffer)
            .distinct(NormalizedOffer.raw_offer_id)
            .order_by(NormalizedOffer.raw_offer_id, NormalizedOffer.id.desc())
            .subquery()
        )
        has_gtin = current.c.gtin.is_not(None)
        has_mpn = current.c.mpn.is_not(None)
        has_brand = current.c.brand_raw.is_not(None)

        row = (
            await self.session.execute(
                select(
                    func.count().label("total"),
                    func.count().filter(has_gtin).label("gtin"),
                    func.count().filter(~has_gtin, has_brand, has_mpn).label("brand_mpn"),
                    func.count().filter(~has_gtin, has_brand, ~has_mpn).label("brand_only"),
                    func.count()
                    .filter(~has_gtin, case((has_brand, False), else_=True))
                    .label("nothing"),
                ).select_from(current)
            )
        ).one()

        total = row.total or 0
        deterministic = row.gtin + row.brand_mpn
        return Coverage(
            normalized_offers=total,
            with_gtin=row.gtin,
            with_brand_and_mpn=row.brand_mpn,
            with_brand_only=row.brand_only,
            with_nothing=row.nothing,
            gtin_share=round(row.gtin / total, 4) if total else 0.0,
            deterministic_share=round(deterministic / total, 4) if total else 0.0,
        )

    # --- pieces ---

    async def _seller_for(self, shop: Shop, external_id: str | None) -> Seller:
        if not shop.is_marketplace:
            seller = await self.session.scalar(select(Seller).where(Seller.shop_id == shop.id))
            if seller is None:
                raise ValidationError(
                    f"Shop '{shop.slug}' has no seller, which should be impossible",
                    code="shop_without_seller",
                )
            return seller

        if not external_id:
            raise ValidationError(
                f"'{shop.slug}' is a marketplace, so an offer has to say which seller it"
                " belongs to — otherwise its price history would be drawn through every"
                " trader on the platform at once.",
                code="seller_required",
            )

        seller = await self.session.scalar(
            select(Seller).where(Seller.shop_id == shop.id, Seller.external_id == external_id)
        )
        if seller is None:
            # Traders arrive in the data rather than being entered ahead of it.
            seller = Seller(shop_id=shop.id, external_id=external_id, name=external_id)
            self.session.add(seller)
            await self.session.flush()
        return seller

    async def _offer_for(
        self, seller_id: int, market_code: str, payload: RawOfferIngest | BatchOffer
    ) -> tuple[Offer, bool]:
        offer = await self.session.scalar(
            select(Offer).where(
                Offer.seller_id == seller_id, Offer.external_id == payload.external_id
            )
        )
        if offer is not None:
            return offer, False

        offer = Offer(
            seller_id=seller_id,
            market_code=market_code.upper(),
            external_id=payload.external_id,
            url=payload.url,
            condition=payload.condition.value,
            condition_grade=payload.condition_grade,
        )
        self.session.add(offer)
        await self.session.flush()
        return offer, True

    async def _store_reading(self, raw: RawOffer, *, source: Source) -> NormalizedOffer:
        fields = read(
            raw.payload,
            source_slug=source.slug,
            shop_slug=await self._shop_slug(source),
            category=await self._category_slug(source),
            vocabulary=await self._vocabulary(source),
        )
        reading = await self.session.scalar(
            select(NormalizedOffer).where(
                NormalizedOffer.raw_offer_id == raw.id,
                NormalizedOffer.ruleset_version == fields["ruleset_version"],
            )
        )
        if reading is None:
            reading = NormalizedOffer(raw_offer_id=raw.id, **fields)
            self.session.add(reading)
        else:
            # Re-running the same ruleset is idempotent; a new one gets its own row, so the
            # two readings can be compared rather than one replacing the other.
            for key, value in fields.items():
                setattr(reading, key, value)

        # Not part of `fields`, and deliberately: a reading is a pure function of a payload
        # and the rules, and this is the channel's own answer about what it collects. The
        # column had been declared and left null on all 76384 readings, so nothing could ask
        # the database what a listing was read as.
        reading.category_id = source.category_id

        await self.session.flush()
        await self.session.refresh(reading)
        return reading

    async def _record_series(
        self, offer: Offer, reading: NormalizedOffer, *, source_id: int
    ) -> None:
        """Two series, because they are two facts arriving at two rates."""
        await self.prices.record_price(
            offer,
            price=reading.price,
            currency_code=reading.currency_code,
            source_id=source_id,
        )
        await self.prices.record_availability(
            offer, availability=reading.availability, source_id=source_id
        )

    async def _apply_reading_to_offer(
        self, offer: Offer | None, reading: NormalizedOffer, *, raw: RawOffer
    ) -> None:
        """The offer's price is the latest reading — derived, and kept only so a card does
        not have to walk the observations to show a number.

        What it is called and what it was read as come from a pass that carried the
        catalogue only, for the reason `MatchingService._reading` gives: a quick pass has
        no title and no barcode, and taken as current it would blank both.
        """
        if offer is None:
            return
        offer.price = reading.price
        offer.currency_code = reading.currency_code
        offer.availability = reading.availability
        if await self._run_kind(raw.run_id) != Kind.QUICK.value:
            offer.title = reading.title
            offer.brand_raw = reading.brand_raw
            offer.gtin = reading.gtin
            offer.category_id = reading.category_id

    async def _is_reparse(self, run_id: int | None) -> bool:
        """Whether this batch is a re-reading of what is already stored.

        Read off the run rather than passed on the batch: the kind is already recorded
        there, and a second place to say it is a second place for the two to disagree.
        Cached for the life of the request because a batch is five hundred observations of
        one run.
        """
        return await self._run_kind(run_id) == Kind.REPARSE.value

    async def _run_kind(self, run_id: int | None) -> str | None:
        if run_id is None:
            return None
        if run_id not in self._run_kinds:
            self._run_kinds[run_id] = await self.session.scalar(
                select(Run.kind).where(Run.id == run_id)
            )
        return self._run_kinds[run_id]

    async def _vocabulary(self, source: Source) -> Vocabulary:
        """The words the rules need, loaded once for the batch rather than per listing.

        Read here and handed in so that `read` stays a pure function of its arguments: a
        reading has to be recomputable over stored bytes, and a rule that queried a registry
        would make the answer depend on when it was asked.
        """
        if source.category_id is None:
            return Vocabulary()
        if source.category_id not in self._vocabularies:
            names = await self.session.scalars(
                select(CategoryAlias.alias_normalized).where(
                    CategoryAlias.category_id == source.category_id
                )
            )
            # Every spelling of every colour, in every language the registry holds, mapped
            # to the value it means. Not scoped to the category: a colour is a colour, and
            # the registry is global for the same reason — mapping `Krāsa` once per category
            # is how a mapping queue stops draining.
            colours = await self.session.execute(
                select(AttributeValueAlias.alias_normalized, AttributeValue.canonical)
                .join(AttributeValue, AttributeValue.id == AttributeValueAlias.attribute_value_id)
                .join(Attribute, Attribute.id == AttributeValue.attribute_id)
                .where(Attribute.key == COLOR_KEY)
            )
            makers = await self.session.scalars(select(Brand.canonical_name))
            # What each maker calls what it makes, keyed the way a reading spells a maker
            # — `normalize_brand` on both sides, so the page a listing's `brand_raw` opens
            # is the page its maker's names were filed under.
            spellings = await self.session.execute(
                select(Brand.canonical_name, ModelAlias.alias_normalized, ModelAlias.model)
                .join(ModelAlias, ModelAlias.brand_id == Brand.id)
                # Only this category's names. A phone's `Air` read into a tablet's title is
                # how 130 iPads were about to become a Nubia.
                .where(ModelAlias.category_id == source.category_id)
            )
            pages: dict[str, dict[str, str]] = {}
            for maker, alias, model in spellings.all():
                pages.setdefault(normalize_brand(maker), {})[alias] = model
            # What shops call this category's attributes. A name that leads to two of them
            # in one category is dropped: which one a shop meant is not something to guess.
            named = await self.session.execute(
                select(AttributeAlias.alias_normalized, Attribute.key)
                .join(Attribute, Attribute.id == AttributeAlias.attribute_id)
                .join(CategoryAttribute, CategoryAttribute.attribute_id == Attribute.id)
                .where(CategoryAttribute.category_id == source.category_id)
            )
            keys: dict[str, set[str]] = {}
            for alias, key in named.all():
                keys.setdefault(alias, set()).add(key)
            # The words for this category's attribute values, colour aside — colour has its
            # own global map above. `nē` under connectivity is `wifi`.
            worded = await self.session.execute(
                select(
                    Attribute.key, AttributeValueAlias.alias_normalized, AttributeValue.canonical
                )
                .join(AttributeValue, AttributeValue.id == AttributeValueAlias.attribute_value_id)
                .join(Attribute, Attribute.id == AttributeValue.attribute_id)
                .join(CategoryAttribute, CategoryAttribute.attribute_id == Attribute.id)
                .where(
                    CategoryAttribute.category_id == source.category_id, Attribute.key != COLOR_KEY
                )
            )
            values: dict[str, dict[str, str]] = {}
            for key, alias, value in worded.all():
                values.setdefault(key, {})[alias] = value
            self._vocabularies[source.category_id] = Vocabulary(
                category_names=frozenset(names),
                brand_names=frozenset(name.casefold() for name in makers if name),
                colours=MappingProxyType({alias: value for alias, value in colours.all()}),
                models=MappingProxyType(
                    {maker: MappingProxyType(page) for maker, page in pages.items()}
                ),
                attribute_names=MappingProxyType(
                    {alias: next(iter(found)) for alias, found in keys.items() if len(found) == 1}
                ),
                values=MappingProxyType(
                    {key: MappingProxyType(words) for key, words in values.items()}
                ),
            )
        return self._vocabularies[source.category_id]

    async def _shop_slug(self, source: Source) -> str | None:
        """Which shop a channel is into — what selects the rules that are true of the shop."""
        return await self.session.scalar(select(Shop.slug).where(Shop.id == source.shop_id))

    async def _category_slug(self, source: Source) -> str | None:
        """What this channel collects, when it collects one thing.

        Null for a feed carrying a whole shop, and then the category's rules simply do not
        apply — which is honest rather than a gap: reading a monitor by a phone's rules is
        a confident wrong answer, and no rules at all is only a quiet one.
        """
        if source.category_id is None:
            return None
        return await self.session.scalar(
            select(Category.slug).where(Category.id == source.category_id)
        )

    async def _current_reading(self, raw_offer_id: int) -> NormalizedOffer | None:
        """The most recently computed reading of these bytes.

        Not "the one under version X": a ruleset is per source now, so no single constant
        names the right one. Re-reading always writes the current ruleset, so the newest
        row is the current one by construction — and that stays true when a source gets
        rules it did not have before.
        """
        return await self.session.scalar(
            select(NormalizedOffer)
            .where(NormalizedOffer.raw_offer_id == raw_offer_id)
            .order_by(NormalizedOffer.id.desc())
            .limit(1)
        )

    async def _offer(self, offer_id: int) -> Offer:
        offer = await self.session.get(Offer, offer_id)
        if offer is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        return offer

    async def _source(self, source_id: int) -> Source:
        source = await self.session.get(Source, source_id)
        if source is None:
            raise NotFoundError(f"Source {source_id} not found")
        return source

    async def _shop(self, shop_id: int) -> Shop:
        shop = await self.session.get(Shop, shop_id)
        if shop is None:
            raise NotFoundError(f"Shop {shop_id} not found")
        return shop

    async def _market(self, code: str) -> Market:
        market = await self.session.get(Market, code.upper())
        if market is None:
            raise ValidationError(
                f"Unknown market '{code}'. Open the market first.", code="unknown_market"
            )
        return market


def _plain(fields: dict[str, Any]) -> dict[str, Any]:
    """A reading as JSON carries it: a number as its shortest string, the rest as it is —
    so `529.00` stored and `529` recomputed are one price, not a stale reading."""
    return {
        key: _number(value) if isinstance(value, Decimal) else value
        for key, value in fields.items()
    }


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _trace_match(match: OfferMatch) -> TraceMatch:
    return TraceMatch(
        variant_id=match.variant_id,
        method=match.method,
        confidence=match.confidence,
        decided_by=match.decided_by,
        decided_at=match.decided_at,
        superseded_at=match.superseded_at,
        evidence=match.evidence or {},
    )


def _axis(number: Decimal | None) -> str:
    return _number(number) if number is not None else ""


def _match_state() -> Any:
    """An active match, else a queue row, else neither — the invariant keeps them apart."""
    return case(
        (OfferMatch.id.is_not(None), "placed"),
        (MatchQueue.offer_id.is_not(None), "queued"),
        else_="unplaced",
    )


def _category_id() -> Any:
    """The product's category once placed, else what the listing's channel collects."""
    return func.coalesce(Product.category_id, Offer.category_id)


def _offer_rows() -> Any:
    """Each listing with its shop and seller named, and the entry it is placed on, if any."""
    return (
        select(
            Offer,
            Shop.id.label("shop_id"),
            Shop.name.label("shop_name"),
            Seller.name.label("seller_name"),
            OfferMatch.variant_id.label("variant_id"),
            OfferMatch.method.label("method"),
            Variant.title.label("variant_title"),
            Brand.id.label("brand_id"),
            Brand.canonical_name.label("brand_name"),
            Category.id.label("category_id"),
            Category.name.label("category_name"),
            _match_state().label("match_state"),
            MatchQueue.reason.label("queue_reason"),
            offer_is_listed().label("listed"),
        )
        .join(Seller, Seller.id == Offer.seller_id)
        .join(Shop, Shop.id == Seller.shop_id)
        .outerjoin(
            OfferMatch, (OfferMatch.offer_id == Offer.id) & OfferMatch.superseded_at.is_(None)
        )
        .outerjoin(Variant, Variant.id == OfferMatch.variant_id)
        .outerjoin(Product, Product.id == Variant.product_id)
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .outerjoin(Category, Category.id == _category_id())
        .outerjoin(MatchQueue, MatchQueue.offer_id == Offer.id)
    )


def _offer_read(row: Any) -> OfferRead:
    offer = row[0]
    return OfferRead(
        id=offer.id,
        shop=ShopRef(id=row.shop_id, name=row.shop_name),
        seller=SellerRef(id=offer.seller_id, name=row.seller_name),
        title=offer.title,
        brand_raw=offer.brand_raw,
        gtin=offer.gtin,
        brand=NamedRef(id=row.brand_id, name=row.brand_name) if row.brand_id else None,
        category=NamedRef(id=row.category_id, name=row.category_name) if row.category_id else None,
        match_state=row.match_state,
        queue_reason=row.queue_reason,
        placed_on=PlacedOn(
            variant_id=row.variant_id, variant_title=row.variant_title, method=row.method
        )
        if row.variant_id is not None
        else None,
        listed=bool(row.listed),
        market_code=offer.market_code,
        external_id=offer.external_id,
        url=offer.url,
        condition=offer.condition,
        condition_grade=offer.condition_grade,
        price=offer.price,
        currency_code=offer.currency_code,
        availability=offer.availability,
        first_seen_at=offer.first_seen_at,
        last_seen_at=offer.last_seen_at,
    )
