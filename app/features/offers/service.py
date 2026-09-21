"""Taking in what a shop served, and reading it."""

from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import (
    Market,
    NormalizedOffer,
    Offer,
    RawOffer,
    Seller,
    Shop,
    Source,
)
from app.db.query import paginated
from app.features.offers.normalization import RULESET_VERSION, content_hash, read
from app.features.offers.schemas import (
    Coverage,
    IngestResult,
    NormalizedOfferRead,
    OfferRead,
    RawOfferIngest,
    RawOfferRead,
)
from app.schemas.pagination import Pagination


class OfferService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- taking it in ---

    async def ingest(self, source_id: int, payload: RawOfferIngest) -> IngestResult:
        source = await self._source(source_id)
        shop = await self._shop(source.shop_id)
        await self._market(payload.market_code)
        seller = await self._seller_for(shop, payload.seller_external_id)

        offer, created = await self._offer_for(seller.id, payload)
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
            reading = await self._current_reading(existing.id)
            return IngestResult(
                offer_id=offer.id,
                raw_offer_id=existing.id,
                normalized_offer_id=reading.id if reading else None,
                offer_created=created,
                stored=False,
            )

        raw = RawOffer(
            offer_id=offer.id,
            source_id=source.id,
            payload=payload.payload,
            content_hash=digest,
            fetched_at=now,
            last_seen_at=now,
        )
        self.session.add(raw)
        await self.session.flush()

        reading = await self._store_reading(raw)
        self._apply_reading_to_offer(offer, reading)
        await self.session.flush()

        audit.set_target("offer", offer.id)
        audit.record_changes(source_id=source.id, external_id=payload.external_id, stored=True)
        return IngestResult(
            offer_id=offer.id,
            raw_offer_id=raw.id,
            normalized_offer_id=reading.id,
            offer_created=created,
            stored=True,
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
        reading = await self._store_reading(raw)
        offer = await self.session.get(Offer, raw.offer_id)
        self._apply_reading_to_offer(offer, reading)
        await self.session.flush()
        audit.record_changes(raw_offer_id=raw_offer_id, ruleset_version=RULESET_VERSION)
        return NormalizedOfferRead.model_validate(reading)

    # --- reading it back ---

    async def list_offers(
        self,
        pagination: Pagination,
        *,
        seller_id: int | None = None,
        market_code: str | None = None,
    ) -> tuple[list[OfferRead], int]:
        stmt = select(Offer)
        if seller_id is not None:
            stmt = stmt.where(Offer.seller_id == seller_id)
        if market_code is not None:
            stmt = stmt.where(Offer.market_code == market_code.upper())

        rows, total = await paginated(self.session, stmt.order_by(Offer.id), pagination)
        return [OfferRead.model_validate(row) for row in rows], total

    async def get_offer(self, offer_id: int) -> OfferRead:
        return OfferRead.model_validate(await self._offer(offer_id))

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
            raise NotFoundError(
                f"Raw offer {raw_offer_id} has no reading under ruleset '{RULESET_VERSION}'"
            )
        return NormalizedOfferRead.model_validate(reading)

    async def coverage(self) -> Coverage:
        """What share of readings carry something a deterministic matcher can use.

        The measurement the whole design is downstream of. A barcode is the strongest
        signal; brand with a part number is the next; a brand alone narrows the field but
        decides nothing. If most rows land in the last bucket, the centre of the work moves
        to pulling identity out of free text and the matcher is the wrong thing to build
        first.
        """
        has_gtin = NormalizedOffer.gtin.is_not(None)
        has_mpn = NormalizedOffer.mpn.is_not(None)
        has_brand = NormalizedOffer.brand_raw.is_not(None)

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
                ).where(NormalizedOffer.ruleset_version == RULESET_VERSION)
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

    async def _offer_for(self, seller_id: int, payload: RawOfferIngest) -> tuple[Offer, bool]:
        offer = await self.session.scalar(
            select(Offer).where(
                Offer.seller_id == seller_id, Offer.external_id == payload.external_id
            )
        )
        if offer is not None:
            return offer, False

        offer = Offer(
            seller_id=seller_id,
            market_code=payload.market_code.upper(),
            external_id=payload.external_id,
            url=payload.url,
            condition=payload.condition.value,
            condition_grade=payload.condition_grade,
        )
        self.session.add(offer)
        await self.session.flush()
        return offer, True

    async def _store_reading(self, raw: RawOffer) -> NormalizedOffer:
        fields = read(raw.payload)
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

        await self.session.flush()
        await self.session.refresh(reading)
        return reading

    @staticmethod
    def _apply_reading_to_offer(offer: Offer | None, reading: NormalizedOffer) -> None:
        """The offer's price is the latest reading — derived, and kept only so a card does
        not have to walk the observations to show a number."""
        if offer is None:
            return
        offer.price = reading.price
        offer.currency_code = reading.currency_code
        offer.availability = reading.availability

    async def _current_reading(self, raw_offer_id: int) -> NormalizedOffer | None:
        return await self.session.scalar(
            select(NormalizedOffer).where(
                NormalizedOffer.raw_offer_id == raw_offer_id,
                NormalizedOffer.ruleset_version == RULESET_VERSION,
            )
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
