"""Asking an outside model a bounded question, and remembering what it said.

This feature knows nothing about offers, the match queue or why anything is being asked.
It takes a question, answers it once, and stores the answer. Whoever needs a judgement
owns the decision to want one — which is what keeps an outside dependency from spreading
through the matcher.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeError,
)

from app.core import audit
from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import (
    Attribute,
    AttributeValue,
    AttributeValueAlias,
    AuditEntry,
    Brand,
    Category,
    CategoryAttribute,
    JudgeReview,
    JudgeVerdict,
    MatchQueue,
    Offer,
    OfferMatch,
    Seller,
    Shop,
    User,
    Variant,
    VariantAttribute,
)
from app.db.query import ordered, paginated
from app.features.judge import questions
from app.features.judge.questions import Candidate, Colour, Option, Question
from app.features.judge.schemas import (
    BrandRequest,
    BrandVerdict,
    Calibration,
    CalibrationBucket,
    ColourRequest,
    ColourVerdict,
    JudgeConfig,
    JudgeReport,
    JudgeSummary,
    JudgeWindow,
    Kind,
    MatchCheckRequest,
    MatchCheckVerdict,
    Named,
    Outcome,
    PendingKind,
    ReviewCreate,
    UsageDay,
    VariantRequest,
    VariantVerdict,
    VerdictAnswer,
    VerdictListing,
    VerdictOption,
    VerdictRead,
    VerdictReview,
)
from app.schemas.pagination import Pagination

ClientFactory = Callable[[], AsyncTypeSafeClient]


def build_client() -> AsyncTypeSafeClient:
    """The real client. Tests pass a factory whose transport never leaves the process."""
    key = settings.typesafe_api_key
    return AsyncTypeSafeClient(
        api_key=key.get_secret_value() if key is not None else None,
        model=settings.typesafe_model,
        timeout=settings.typesafe_timeout_seconds,
        # The SDK retries 5xx and timeouts on its own, which is wanted. Its default
        # budget is a flat 30 seconds per question, though, and a pass asks many: with a
        # service that is simply down, that turns one admin click into minutes of
        # waiting. Tying the budget to the configured timeout keeps the two from drifting
        # and makes the worst case something a person can predict from one number.
        retry=RetryPolicy(timeout=settings.typesafe_timeout_seconds * 3),
    )


COLOUR_KEY = "color"


class JudgeService:
    def __init__(self, session: AsyncSession, client_factory: ClientFactory = build_client) -> None:
        self.session = session
        self._client_factory = client_factory
        # The registry's colours, loaded at most once per instance. A pass asks about
        # hundreds of listings and gets the same list every time; the list is also part of
        # every colour question's identity, so loading it once keeps the hashes stable
        # within a pass as well as saving the queries. A colour entered while a pass is
        # running is therefore not seen by it, which is the correct trade: a question that
        # changed its options halfway through a pass would be two questions.
        self._colour_cache: list[Colour] | None = None

    # --- reading a stored answer, which never leaves the process ---

    async def stored_brand_verdict(self, request: BrandRequest) -> BrandVerdict | None:
        """What was already decided about this listing, or nothing.

        The only entry point the matcher uses. It cannot reach the network through here,
        which is the point: running the ladder stays offline, deterministic and fast.
        """
        question = await self._brand_question(request)
        if question is None:
            return None
        stored = await self._stored(question.hash)
        return None if stored is None else self._read(stored, question)

    # --- asking ---

    async def decide_brands(
        self, requests: list[BrandRequest]
    ) -> tuple[dict[int, BrandVerdict], JudgeReport]:
        """Answer a batch, paying only for the questions not answered before.

        One listing is one request — the state differs per listing, so they cannot share
        one, which is the case the parallel-questions advice does not cover. They are sent
        concurrently instead, bounded so a large pass does not open a hundred sockets.
        """
        if not settings.judge_enabled:
            raise ValidationError(
                "No TypeSafe API key is configured, so nothing can be judged."
                " Set TYPESAFE_API_KEY.",
                code="judge_disabled",
            )

        built = [(request, await self._brand_question(request)) for request in requests]
        pending = [(request, q) for request, q in built if q is not None]

        verdicts: dict[int, BrandVerdict] = {}
        unanswered: list[tuple[BrandRequest, Question]] = []
        cached = 0
        for request, question in pending:
            stored = await self._stored(question.hash)
            if stored is None:
                unanswered.append((request, question))
            else:
                cached += 1
                verdicts[request.key] = self._read(stored, question)

        asked, failed, error, usage = await self._ask_all(unanswered, verdicts, self._read)
        return verdicts, JudgeReport(
            considered=len(requests),
            asked=asked,
            cached=cached,
            accepted=sum(1 for v in verdicts.values() if v.accepted),
            unconfident=sum(
                1 for v in verdicts.values() if not v.accepted and v.choice != questions.NO_MATCH
            ),
            no_match=sum(1 for v in verdicts.values() if v.choice == questions.NO_MATCH),
            failed=failed,
            placed=0,
            input_tokens=usage[0],
            output_tokens=usage[1],
            error=error,
        )

    async def decide_variants(
        self, requests: list[VariantRequest]
    ) -> tuple[dict[int, VariantVerdict], JudgeReport]:
        """Which catalogue entry each of these listings is.

        The second question this asks, and the one the corpus could not answer on its own.
        A marketing colour name belongs to a maker — `Canyon` is pink on a Google and orange
        on an Oppo, both proved by two shops — so no global registry row can hold it, and
        there is nothing left to count. What is left is to ask.
        """
        if not settings.judge_enabled:
            raise ValidationError(
                "No TypeSafe API key is configured, so nothing can be judged."
                " Set TYPESAFE_API_KEY.",
                code="judge_disabled",
            )

        built = [(request, await self._variant_question(request)) for request in requests]
        pending = [(request, q) for request, q in built if q is not None]

        verdicts: dict[int, VariantVerdict] = {}
        unanswered: list[tuple[VariantRequest, Question]] = []
        cached = 0
        for request, question in pending:
            stored = await self._stored(question.hash)
            if stored is None:
                unanswered.append((request, question))
            else:
                cached += 1
                verdicts[request.key] = self._read_variant(stored, question)

        asked, failed, error, usage = await self._ask_all(unanswered, verdicts, self._read_variant)
        return verdicts, JudgeReport(
            considered=len(requests),
            asked=asked,
            cached=cached,
            accepted=sum(1 for v in verdicts.values() if v.accepted),
            unconfident=sum(
                1 for v in verdicts.values() if not v.accepted and v.choice != questions.NO_MATCH
            ),
            no_match=sum(1 for v in verdicts.values() if v.choice == questions.NO_MATCH),
            failed=failed,
            placed=0,
            input_tokens=usage[0],
            output_tokens=usage[1],
            error=error,
        )

    async def stored_colour_verdict(self, request: ColourRequest) -> ColourVerdict | None:
        """An answer already bought, without reaching the network.

        The matcher reads colours through this, exactly as it reads brands: running the
        ladder or a promotion stays offline and deterministic, and buying an answer is a
        separate pass somebody starts.
        """
        question = await self._colour_question(request)
        if question is None:
            return None
        stored = await self._stored(question.hash)
        return None if stored is None else self._read_colour(stored, question)

    async def decide_colours(
        self, requests: list[ColourRequest]
    ) -> tuple[dict[int, ColourVerdict], JudgeReport]:
        """What plain colour each of these listings is, by the maker's own name for it.

        The third question, and the one that unblocks the second: `variant_choice` refused
        30 of 30 listings and was right to — at confidence 1.00 a `Coralred` Samsung is
        neither of the black and grey entries the catalogue holds. They do not need matching
        to an entry, they need one of their own, and what stops that is the missing colour.
        """
        if not settings.judge_enabled:
            raise ValidationError(
                "No TypeSafe API key is configured, so nothing can be judged."
                " Set TYPESAFE_API_KEY.",
                code="judge_disabled",
            )

        built = [(request, await self._colour_question(request)) for request in requests]
        pending = [(request, q) for request, q in built if q is not None]

        verdicts: dict[int, ColourVerdict] = {}
        unanswered: list[tuple[ColourRequest, Question]] = []
        cached = 0
        for request, question in pending:
            stored = await self._stored(question.hash)
            if stored is None:
                unanswered.append((request, question))
            else:
                cached += 1
                verdicts[request.key] = self._read_colour(stored, question)

        asked, failed, error, usage = await self._ask_all(unanswered, verdicts, self._read_colour)
        return verdicts, JudgeReport(
            considered=len(requests),
            asked=asked,
            cached=cached,
            accepted=sum(1 for v in verdicts.values() if v.accepted),
            unconfident=sum(
                1 for v in verdicts.values() if not v.accepted and v.choice != questions.NO_MATCH
            ),
            no_match=sum(1 for v in verdicts.values() if v.choice == questions.NO_MATCH),
            failed=failed,
            placed=0,
            input_tokens=usage[0],
            output_tokens=usage[1],
            error=error,
        )

    async def check_matches(
        self, requests: list[MatchCheckRequest], *, budget: int
    ) -> tuple[dict[int, MatchCheckVerdict], JudgeReport]:
        """Whether each listing sells the model its entry is named, at most `budget` paid for.

        The fourth question, and the only one that questions a decision rather than making
        one. A rule's match is right far more often than not — 8982 were checked on
        22.09.2026 and 45-odd were wrong — so the cost that matters is asking at all, and
        the store is what keeps it proportional to how many matches are new. `budget`
        bounds what a pass pays for; answers already held do not count against it, so a
        pass always moves forward however many of them there are.
        """
        if not settings.judge_enabled:
            raise ValidationError(
                "No TypeSafe API key is configured, so nothing can be judged."
                " Set TYPESAFE_API_KEY.",
                code="judge_disabled",
            )

        verdicts: dict[int, MatchCheckVerdict] = {}
        unanswered: list[tuple[MatchCheckRequest, Question]] = []
        cached = 0
        for request in requests:
            question = questions.model_match(
                title=request.title, brand=request.brand, entry_model=request.entry_model
            )
            stored = await self._stored(question.hash)
            if stored is not None:
                cached += 1
                verdicts[request.key] = self._read_match(stored, question)
            elif len(unanswered) < budget:
                unanswered.append((request, question))

        asked, failed, error, usage = await self._ask_all(unanswered, verdicts, self._read_match)
        return verdicts, JudgeReport(
            considered=len(requests),
            asked=asked,
            cached=cached,
            accepted=sum(1 for v in verdicts.values() if not v.doubted),
            unconfident=0,
            no_match=0,
            failed=failed,
            placed=0,
            doubted=sum(1 for v in verdicts.values() if v.doubted),
            input_tokens=usage[0],
            output_tokens=usage[1],
            error=error,
        )

    @staticmethod
    def _read_match(stored: JudgeVerdict, question: Question) -> MatchCheckVerdict:
        same = Decimal(str((stored.answer.get("probabilities") or {}).get(questions.SAME_MODEL, 0)))
        return MatchCheckVerdict(
            choice=stored.choice,
            confidence=stored.confidence,
            same=same,
            doubted=same < Decimal(str(settings.judge_doubt_below)),
        )

    @staticmethod
    def _read_colour(stored: JudgeVerdict, question: Question) -> ColourVerdict:
        known = stored.choice in question.by_option
        confident = float(stored.confidence) >= settings.judge_min_confidence
        accepted = known and confident
        return ColourVerdict(
            canonical=stored.choice if accepted else None,
            choice=stored.choice,
            confidence=stored.confidence,
            accepted=accepted,
            no_match=stored.choice == questions.NO_MATCH,
        )

    async def _colour_question(self, request: ColourRequest) -> Question | None:
        """None when the registry holds no colours to choose between."""
        if not request.title:
            return None
        colours = await self._colours()
        if len(colours) < 2:
            return None
        return questions.colour_choice(
            title=request.title,
            brand=request.brand,
            model=request.model,
            colours=colours,
        )

    async def _colours(self) -> list[Colour]:
        """Every plain colour the registry holds, with the spellings it knows for each.

        The spellings are the only true thing there is to say about a colour beyond its
        name, and they are what makes `Tumši zils` and `dark blue` visibly one option
        rather than two.
        """
        if self._colour_cache is not None:
            return self._colour_cache
        rows = await self.session.execute(
            select(AttributeValue.canonical, AttributeValueAlias.alias_normalized)
            .join(Attribute, Attribute.id == AttributeValue.attribute_id)
            .outerjoin(
                AttributeValueAlias,
                AttributeValueAlias.attribute_value_id == AttributeValue.id,
            )
            .where(Attribute.key == COLOUR_KEY)
        )
        spellings: dict[str, set[str]] = {}
        for canonical, alias in rows.all():
            held = spellings.setdefault(canonical, set())
            if alias and alias != canonical:
                held.add(alias)
        self._colour_cache = [
            Colour(canonical=canonical, spellings=tuple(sorted(aliases)))
            for canonical, aliases in sorted(spellings.items())
        ]
        return self._colour_cache

    async def _ask_all(
        self,
        unanswered: list[tuple[Any, Question]],
        verdicts: dict[int, Any],
        read: Callable[[JudgeVerdict, Question], Any],
    ) -> tuple[int, int, str | None, tuple[int, int]]:
        """Send what is left, then write what came back.

        The two halves are deliberately apart. The calls run together; the writes run one
        after another on the request's own session, which is not safe to share between
        tasks. Nothing is written until every answer is in, so a pass either records a
        listing or does not — never half of one.
        """
        if not unanswered:
            return 0, 0, None, (0, 0)

        # The same question can appear twice in one pass — two shops listing the same
        # thing in the same words. Asking once is the whole point of the store, so it has
        # to hold within a pass as well as across them.
        by_hash: dict[str, Question] = {q.hash: q for _, q in unanswered}
        gate = asyncio.Semaphore(settings.judge_concurrency)

        async with self._client_factory() as client:

            async def ask(question: Question) -> SystemOneResponse:
                async with gate:
                    return await client.system_one(
                        state=question.state,
                        questions={
                            question.kind: Choice(
                                instructions=question.instructions, criteria=question.criteria
                            )
                        },
                    )

            results = await asyncio.gather(
                *(ask(question) for question in by_hash.values()), return_exceptions=True
            )

        asked = failed = 0
        error: str | None = None
        tokens_in = tokens_out = 0
        answered: dict[str, JudgeVerdict] = {}

        for question, result in zip(by_hash.values(), results, strict=True):
            if isinstance(result, BaseException):
                failed += 1
                # A failure here is a service being unreachable or a key being wrong, not
                # a listing being difficult. It is reported, never stored: a stored
                # failure would look like an answer on the next pass.
                if error is None:
                    error = f"{type(result).__name__}: {result}"
                if not isinstance(result, TypeSafeError):
                    raise result
                continue

            asked += 1
            tokens_in += result.usage.input_tokens
            tokens_out += result.usage.output_tokens
            answered[question.hash] = await self._store(question, result)

        for request, question in unanswered:
            stored = answered.get(question.hash)
            if stored is not None:
                verdicts[request.key] = read(stored, question)

        return asked, failed, error, (tokens_in, tokens_out)

    # --- writing ---

    async def _store(self, question: Question, response: SystemOneResponse) -> JudgeVerdict:
        answer = response.choices[question.kind]
        verdict = JudgeVerdict(
            kind=question.kind,
            question_hash=question.hash,
            state=question.state,
            options=list(question.criteria),
            criteria=question.criteria,
            answer=answer.model_dump(mode="json"),
            choice=answer.choice,
            confidence=Decimal(str(answer.confidence)).quantize(Decimal("0.0001")),
            # What answered, not what was asked for: `jev-latest` moves, and a verdict
            # nobody can attribute to a version cannot be re-examined later.
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        try:
            # A savepoint rather than the plain flush the other services use. Those handle
            # a conflict by rolling the request back and returning 409; here the conflict
            # is harmless and the pass has to continue, so only this one insert is undone
            # and the verdicts already written in the same pass survive.
            async with self.session.begin_nested():
                self.session.add(verdict)
                await self.session.flush()
        except IntegrityError:
            # Another pass asked the same question first. Its answer is as good as this
            # one, and the store holds one row per question on purpose.
            existing = await self._stored(question.hash)
            if existing is None:
                raise
            return existing

        return verdict

    # --- reading ---

    async def verdicts(
        self,
        pagination: Pagination,
        *,
        kinds: list[str] | None = None,
        outcomes: list[str] | None = None,
        no_match: bool | None = None,
        confidence_min: Decimal | None = None,
        confidence_max: Decimal | None = None,
        search: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        forgotten: bool | None = None,
    ) -> tuple[list[VerdictRead], int]:
        stmt = select(JudgeVerdict)
        if kinds:
            stmt = stmt.where(JudgeVerdict.kind.in_(kinds))
        if outcomes:
            stmt = stmt.where(_outcome().in_(outcomes))
        if no_match is not None:
            chose_none = JudgeVerdict.choice == questions.NO_MATCH
            stmt = stmt.where(chose_none if no_match else ~chose_none)
        if confidence_min is not None:
            stmt = stmt.where(JudgeVerdict.confidence >= confidence_min)
        if confidence_max is not None:
            stmt = stmt.where(JudgeVerdict.confidence <= confidence_max)
        if search and search.strip():
            stmt = stmt.where(
                JudgeVerdict.state["listing_title"].astext.ilike(f"%{search.strip()}%")
            )
        if created_from is not None:
            stmt = stmt.where(JudgeVerdict.created_at >= created_from)
        if created_to is not None:
            stmt = stmt.where(JudgeVerdict.created_at < created_to)
        if forgotten is not None:
            stmt = stmt.where(
                JudgeVerdict.forgotten_at.is_not(None)
                if forgotten
                else JudgeVerdict.forgotten_at.is_(None)
            )
        stmt = ordered(
            stmt,
            pagination,
            {
                "id": JudgeVerdict.id,
                "created_at": JudgeVerdict.created_at,
                "confidence": JudgeVerdict.confidence,
                "tokens": JudgeVerdict.input_tokens + JudgeVerdict.output_tokens,
            },
            JudgeVerdict.id,
        )
        rows, total = await paginated(self.session, stmt, pagination)
        return await self._verdict_reads(list(rows)), total

    async def verdict(self, verdict_id: int) -> VerdictRead:
        stored = await self.session.get(JudgeVerdict, verdict_id)
        if stored is None:
            raise NotFoundError(f"Verdict {verdict_id} not found")
        [read] = await self._verdict_reads([stored])
        return read

    async def forget(self, verdict_id: int) -> None:
        """Stop answering with this, so the next pass asks again — after the options it
        was asked about were described differently, say. Kept, not deleted: it was paid
        for, and the usage it counts in is money that was spent."""
        stored = await self.session.get(JudgeVerdict, verdict_id)
        audit.set_target("judge_verdict", verdict_id)
        if stored is None:
            raise NotFoundError(f"Verdict {verdict_id} not found")
        if stored.forgotten_at is None:
            stored.forgotten_at = datetime.now(UTC)
            await self.session.flush()
            audit.record_changes(forgotten=True, kind=stored.kind)

    async def review(
        self, verdict_id: int, payload: ReviewCreate, *, reviewer_id: int
    ) -> VerdictRead:
        stored = await self.session.get(JudgeVerdict, verdict_id)
        audit.set_target("judge_verdict", verdict_id)
        if stored is None:
            raise NotFoundError(f"Verdict {verdict_id} not found")
        existing = await self.session.get(JudgeReview, verdict_id)
        if existing is None:
            existing = JudgeReview(verdict_id=verdict_id)
            self.session.add(existing)
        existing.correct = payload.correct
        existing.note = payload.note
        existing.reviewed_by = reviewer_id
        existing.reviewed_at = datetime.now(UTC)
        await self.session.flush()
        audit.record_changes(correct=payload.correct, note=payload.note)
        return await self.verdict(verdict_id)

    async def calibration(self, kind: str | None, *, buckets: int = 10) -> Calibration:
        """The answers of a kind in equal-width buckets of the number their threshold is
        on, each with how many a person marked right and wrong."""
        is_check = kind == questions.MODEL_MATCH
        score = (
            JudgeVerdict.answer["probabilities"][questions.SAME_MODEL].as_float()
            if is_check
            else JudgeVerdict.confidence
        )
        bucket = func.least(func.floor(score * buckets), buckets - 1).label("bucket")
        stmt = (
            select(
                bucket,
                func.count(),
                func.count(JudgeReview.verdict_id),
                func.count().filter(JudgeReview.correct.is_(True)),
                func.count().filter(JudgeReview.correct.is_(False)),
            )
            .select_from(JudgeVerdict)
            .outerjoin(JudgeReview, JudgeReview.verdict_id == JudgeVerdict.id)
            .group_by(bucket)
        )
        if kind is not None:
            stmt = stmt.where(JudgeVerdict.kind == kind)
        counted = {int(row[0]): row[1:] for row in (await self.session.execute(stmt)).all()}
        width = Decimal(1) / buckets
        return Calibration(
            kind=kind,
            score="same" if is_check else "confidence",
            threshold=settings.judge_doubt_below if is_check else settings.judge_min_confidence,
            buckets=[
                CalibrationBucket(
                    low=(width * index).quantize(Decimal("0.01")),
                    high=(width * (index + 1)).quantize(Decimal("0.01")),
                    answers=counted.get(index, (0, 0, 0, 0))[0],
                    reviewed=counted.get(index, (0, 0, 0, 0))[1],
                    correct=counted.get(index, (0, 0, 0, 0))[2],
                    incorrect=counted.get(index, (0, 0, 0, 0))[3],
                )
                for index in range(buckets)
            ],
        )

    async def usage(self, *, days: int) -> list[UsageDay]:
        """Per day and kind: answers bought and their tokens from the store, answers the
        store gave instead from the passes' reports in the trail — a cache hit writes no
        verdict, and the trail is where it is recorded. A pass is one kind of question,
        which is how its hits are attributed."""
        since = datetime.now(UTC) - timedelta(days=days)
        day = func.date_trunc("day", JudgeVerdict.created_at)
        bought = (
            await self.session.execute(
                select(
                    day,
                    JudgeVerdict.kind,
                    func.count(),
                    func.sum(JudgeVerdict.input_tokens),
                    func.sum(JudgeVerdict.output_tokens),
                )
                .where(JudgeVerdict.created_at >= since)
                .group_by(day, JudgeVerdict.kind)
            )
        ).all()
        passed = func.date_trunc("day", AuditEntry.created_at)
        hits = (
            await self.session.execute(
                select(
                    passed,
                    AuditEntry.path,
                    func.coalesce(func.sum(AuditEntry.changes["cached"].as_integer()), 0),
                )
                .where(
                    AuditEntry.method == "POST",
                    AuditEntry.path.in_(PASS_KINDS),
                    AuditEntry.status_code < 300,
                    AuditEntry.created_at >= since,
                )
                .group_by(passed, AuditEntry.path)
            )
        ).all()
        table: dict[tuple[date, str], dict[str, int]] = {}
        for when, kind, count, tokens_in, tokens_out in bought:
            entry = table.setdefault((when.date(), kind), {})
            entry.update(asked=count, input_tokens=tokens_in or 0, output_tokens=tokens_out or 0)
        for when, path, cached in hits:
            entry = table.setdefault((when.date(), PASS_KINDS[path]), {})
            entry["cached"] = entry.get("cached", 0) + int(cached)
        return [
            UsageDay(
                day=when,
                kind=kind,
                asked=entry.get("asked", 0),
                cached=entry.get("cached", 0),
                input_tokens=entry.get("input_tokens", 0),
                output_tokens=entry.get("output_tokens", 0),
            )
            for (when, kind), entry in sorted(table.items())
        ]

    @staticmethod
    def config() -> JudgeConfig:
        return JudgeConfig(
            enabled=settings.judge_enabled,
            model=settings.typesafe_model,
            min_confidence=settings.judge_min_confidence,
            doubt_below=settings.judge_doubt_below,
            concurrency=settings.judge_concurrency,
            timeout_seconds=settings.typesafe_timeout_seconds,
        )

    async def pending(
        self,
        *,
        brands: list[BrandRequest],
        variants: list[VariantRequest],
        colours: list[ColourRequest],
        matches: list[MatchCheckRequest],
    ) -> list[PendingKind]:
        """What each pass would pay for now: its questions, built exactly as the pass
        builds them, less the ones the store already answers."""
        built: dict[str, tuple[int, set[str]]] = {}
        for kind, requests, build in (
            (questions.BRAND_CHOICE, brands, self._brand_question),
            (questions.VARIANT_CHOICE, variants, self._variant_question),
            (questions.COLOUR_CHOICE, colours, self._colour_question),
        ):
            hashes = set()
            for request in requests:
                question = await build(request)
                if question is not None:
                    hashes.add(question.hash)
            built[kind] = (len(requests), hashes)
        built[questions.MODEL_MATCH] = (
            len(matches),
            {
                questions.model_match(
                    title=request.title, brand=request.brand, entry_model=request.entry_model
                ).hash
                for request in matches
            },
        )
        averages = dict(
            (kind, (tokens_in, tokens_out))
            for kind, tokens_in, tokens_out in (
                await self.session.execute(
                    select(
                        JudgeVerdict.kind,
                        func.avg(JudgeVerdict.input_tokens),
                        func.avg(JudgeVerdict.output_tokens),
                    )
                    .where(JudgeVerdict.input_tokens > 0)
                    .group_by(JudgeVerdict.kind)
                )
            ).all()
        )
        out = []
        for kind, (eligible, hashes) in built.items():
            to_ask = len(hashes - await self._stored_hashes(hashes))
            average = averages.get(kind)
            out.append(
                PendingKind(
                    kind=Kind(kind),
                    eligible=eligible,
                    to_ask=to_ask,
                    estimated_input_tokens=round(float(average[0]) * to_ask) if average else None,
                    estimated_output_tokens=round(float(average[1]) * to_ask) if average else None,
                )
            )
        return out

    async def _verdict_reads(self, stored: list[JudgeVerdict]) -> list[VerdictRead]:
        if not stored:
            return []
        labels = await self._labels(stored)
        listings = await self._listings(stored)
        reviews = {
            review.verdict_id: (review, email)
            for review, email in (
                await self.session.execute(
                    select(JudgeReview, User.email)
                    .outerjoin(User, User.id == JudgeReview.reviewed_by)
                    .where(JudgeReview.verdict_id.in_([row.id for row in stored]))
                )
            ).all()
        }
        out = []
        for row in stored:
            answer = row.answer or {}
            options = [
                VerdictOption(
                    key=key,
                    label=labels.get((row.kind, key), key),
                    description=_description(row, key),
                )
                for key in row.options or []
            ]
            review = reviews.get(row.id)
            out.append(
                VerdictRead(
                    id=row.id,
                    kind=Kind(row.kind),
                    question_hash=row.question_hash,
                    state=row.state,
                    options=options,
                    answer=VerdictAnswer(
                        choice=answer.get("choice", row.choice),
                        confidence=Decimal(str(answer.get("confidence", row.confidence))),
                        probabilities=answer.get("probabilities") or {},
                    ),
                    choice=row.choice,
                    choice_label=labels.get((row.kind, row.choice), row.choice),
                    confidence=row.confidence,
                    model=row.model,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    created_at=row.created_at,
                    forgotten_at=row.forgotten_at,
                    outcome=Outcome(_outcome_of(row)),
                    listings=listings.get(row.id, []),
                    review=VerdictReview(
                        correct=review[0].correct,
                        note=review[0].note,
                        reviewed_by=review[1],
                        reviewed_at=review[0].reviewed_at,
                    )
                    if review
                    else None,
                )
            )
        return out

    async def _labels(self, stored: list[JudgeVerdict]) -> dict[tuple[str, str], str]:
        """What a person reads for each option key: a slug is how it was sent, not a name."""
        keys: dict[str, set[str]] = {}
        for row in stored:
            keys.setdefault(row.kind, set()).update(row.options or [])
        labels: dict[tuple[str, str], str] = {}
        for kind in keys:
            labels[(kind, questions.NO_MATCH)] = "None of these"
        if keys.get(questions.BRAND_CHOICE):
            for slug, name in (
                await self.session.execute(
                    select(Brand.slug, Brand.canonical_name).where(
                        Brand.slug.in_(keys[questions.BRAND_CHOICE])
                    )
                )
            ).all():
                labels[(questions.BRAND_CHOICE, slug)] = name
        if keys.get(questions.VARIANT_CHOICE):
            for slug, override, title in (
                await self.session.execute(
                    select(Variant.slug, Variant.title_override, Variant.title).where(
                        Variant.slug.in_(keys[questions.VARIANT_CHOICE])
                    )
                )
            ).all():
                labels[(questions.VARIANT_CHOICE, slug)] = override or title
        for key in keys.get(questions.COLOUR_CHOICE, set()) - {questions.NO_MATCH}:
            labels[(questions.COLOUR_CHOICE, key)] = key
        for key, label in MODEL_MATCH_LABELS.items():
            labels[(questions.MODEL_MATCH, key)] = label
        return labels

    async def _listings(self, stored: list[JudgeVerdict]) -> dict[int, list[VerdictListing]]:
        """The listings each question was about, found the way it was asked: by the
        listing's title and, where the question names the shop's brand string, by that."""
        titles = {
            row.state.get("listing_title") for row in stored if row.state.get("listing_title")
        }
        if not titles:
            return {}
        rows = (
            await self.session.execute(
                select(
                    Offer.id,
                    Offer.title,
                    Offer.brand_raw,
                    Shop.id,
                    Shop.name,
                    OfferMatch.variant_id,
                    OfferMatch.method,
                    OfferMatch.decided_by,
                    MatchQueue.offer_id,
                )
                .join(Seller, Seller.id == Offer.seller_id)
                .join(Shop, Shop.id == Seller.shop_id)
                .outerjoin(
                    OfferMatch,
                    (OfferMatch.offer_id == Offer.id) & OfferMatch.superseded_at.is_(None),
                )
                .outerjoin(MatchQueue, MatchQueue.offer_id == Offer.id)
                .where(Offer.title.in_(titles))
                .order_by(Offer.id)
            )
        ).all()
        by_title: dict[str, list[Any]] = {}
        for row in rows:
            by_title.setdefault(row[1], []).append(row)
        out: dict[int, list[VerdictListing]] = {}
        for verdict in stored:
            brand = _brand_as_asked(verdict)
            out[verdict.id] = [
                VerdictListing(
                    offer_id=row[0],
                    title=row[1],
                    shop=Named(id=row[3], name=row[4]),
                    state="placed" if row[5] else "queued" if row[8] else "unplaced",
                    variant_id=row[5],
                    method=row[6],
                    decided_by=row[7],
                )
                for row in by_title.get(verdict.state.get("listing_title"), [])
                if brand is _ANY or row[2] == brand
            ]
        return out

    async def summary(self) -> JudgeSummary:
        now = datetime.now(UTC)
        return JudgeSummary(
            day=await self._window(now - timedelta(days=1)),
            week=await self._window(now - timedelta(days=7)),
            all_time=await self._window(None),
        )

    async def _window(self, since: datetime | None) -> JudgeWindow:
        bought = select(
            JudgeVerdict.kind,
            func.count(),
            func.coalesce(func.sum(JudgeVerdict.input_tokens), 0),
            func.coalesce(func.sum(JudgeVerdict.output_tokens), 0),
        ).group_by(JudgeVerdict.kind)
        # Every pass that asks lives under this prefix and records its report; the trail
        # keeps it whatever the response was, so only the ones that finished are counted.
        passes = select(
            func.count(),
            func.coalesce(func.sum(AuditEntry.changes["cached"].as_integer()), 0),
        ).where(
            AuditEntry.method == "POST",
            AuditEntry.path.like("/api/admin/matching/judge%"),
            AuditEntry.status_code < 300,
        )
        if since is not None:
            bought = bought.where(JudgeVerdict.created_at >= since)
            passes = passes.where(AuditEntry.created_at >= since)
        rows = (await self.session.execute(bought)).all()
        count, cached = (await self.session.execute(passes)).one()
        return JudgeWindow(
            since=since,
            passes=count,
            asked=sum(row[1] for row in rows),
            cached=cached,
            input_tokens=sum(row[2] for row in rows),
            output_tokens=sum(row[3] for row in rows),
            by_kind={row[0]: row[1] for row in rows},
        )

    async def _stored(self, question_hash: str) -> JudgeVerdict | None:
        return await self.session.scalar(
            select(JudgeVerdict).where(
                JudgeVerdict.question_hash == question_hash, JudgeVerdict.forgotten_at.is_(None)
            )
        )

    async def _stored_hashes(self, hashes: set[str]) -> set[str]:
        """Which of these questions the store can answer, in a few queries, not one each."""
        held: set[str] = set()
        ordered_hashes = sorted(hashes)
        for start in range(0, len(ordered_hashes), 1000):
            chunk = ordered_hashes[start : start + 1000]
            held.update(
                await self.session.scalars(
                    select(JudgeVerdict.question_hash).where(
                        JudgeVerdict.question_hash.in_(chunk), JudgeVerdict.forgotten_at.is_(None)
                    )
                )
            )
        return held

    @staticmethod
    def _read(stored: JudgeVerdict, question: Question) -> BrandVerdict:
        """Turn a stored answer into what code may do with it.

        The threshold is applied here rather than at the call site so that one number
        governs every caller. It is a starting point and not a measurement: the docs are
        explicit that a threshold has to be evaluated against real data.
        """
        brand_id = question.by_option.get(stored.choice)
        confident = float(stored.confidence) >= settings.judge_min_confidence
        accepted = brand_id is not None and confident
        return BrandVerdict(
            brand_id=brand_id if accepted else None,
            choice=stored.choice,
            confidence=stored.confidence,
            accepted=accepted,
            no_match=stored.choice == questions.NO_MATCH,
        )

    # --- building the question ---

    async def _brand_question(self, request: BrandRequest) -> Question | None:
        """None when there is nothing to choose between.

        A single candidate is not a choice, and asking one would buy an answer that was
        already known.
        """
        if len(request.brand_ids) < 2:
            return None
        candidates = await self._candidates(request.brand_ids)
        if len(candidates) < 2:
            return None
        return questions.brand_choice(
            title=request.title,
            brand_raw=request.brand_raw,
            model_raw=request.model_raw,
            candidates=candidates,
        )

    @staticmethod
    def _read_variant(stored: JudgeVerdict, question: Question) -> VariantVerdict:
        variant_id = question.by_option.get(stored.choice)
        confident = float(stored.confidence) >= settings.judge_min_confidence
        accepted = variant_id is not None and confident
        return VariantVerdict(
            variant_id=variant_id if accepted else None,
            choice=stored.choice,
            confidence=stored.confidence,
            accepted=accepted,
            no_match=stored.choice == questions.NO_MATCH,
        )

    async def _variant_question(self, request: VariantRequest) -> Question | None:
        """None when there is nothing to choose between."""
        if len(request.variant_ids) < 2:
            return None
        options = await self._options(request.variant_ids)
        if len(options) < 2:
            return None
        return questions.variant_choice(
            title=request.title,
            brand=request.brand,
            model=request.model,
            options=options,
        )

    async def _options(self, variant_ids: list[int]) -> list[Option]:
        """Describe each entry by the axes it holds and nothing else.

        The axes are what these entries differ in — the model string is the same on all of
        them, which is why the listing was ambiguous in the first place — so describing
        them by anything else would describe them identically and decide nothing.
        """
        variants = (
            await self.session.scalars(select(Variant).where(Variant.id.in_(variant_ids)))
        ).all()
        rows = await self.session.execute(
            select(
                VariantAttribute.variant_id,
                Attribute.name,
                VariantAttribute.value_num,
                AttributeValue.canonical,
            )
            .join(Attribute, Attribute.id == VariantAttribute.attribute_id)
            .outerjoin(AttributeValue, AttributeValue.id == VariantAttribute.value_id)
            .join(
                CategoryAttribute,
                (CategoryAttribute.attribute_id == VariantAttribute.attribute_id)
                & (CategoryAttribute.identity_bearing.is_(True)),
            )
            .where(VariantAttribute.variant_id.in_(variant_ids))
        )
        held: dict[int, list[tuple[str, str]]] = {}
        for variant_id, name, number, canonical in rows.all():
            value = canonical if canonical is not None else _plain(number)
            if value:
                held.setdefault(variant_id, []).append((name, value))

        return [
            Option(
                variant_id=variant.id,
                slug=variant.slug,
                axes=tuple(sorted(held.get(variant.id, []))),
            )
            for variant in variants
        ]

    async def _candidates(self, brand_ids: list[int]) -> list[Candidate]:
        """Describe each brand by what the catalogue already has under it.

        The only true thing available about a brand here. A brand with nothing under it
        gets no description, the answer comes back unconfident, and an unconfident answer
        is one this refuses to act on — which is the correct behaviour, not a gap.
        """
        brands = (await self.session.scalars(select(Brand).where(Brand.id.in_(brand_ids)))).all()
        rows = await self.session.execute(
            select(Variant.brand_id, Category.name)
            .join(Category, Category.id == Variant.category_id)
            .where(Variant.brand_id.in_(brand_ids))
            .distinct()
        )
        seen: dict[int, set[str]] = {}
        for brand_id, name in rows.all():
            seen.setdefault(brand_id, set()).add(name)

        return [
            Candidate(
                brand_id=brand.id,
                slug=brand.slug,
                canonical_name=brand.canonical_name,
                # Sorted because this ends up in the question's identity: a set's order
                # would make the same question hash differently between runs.
                categories=tuple(sorted(seen.get(brand.id, ()))),
            )
            for brand in brands
        ]


def _plain(number: object) -> str:
    """A number as a person would write it: `256` rather than `256.000000`."""
    if number is None:
        return ""
    text = f"{number}".rstrip("0").rstrip(".")
    return text or "0"


# The pass each audited path is, for attributing the cache hits its report records.
PASS_KINDS = {
    "/api/admin/matching/judge": questions.BRAND_CHOICE,
    "/api/admin/matching/judge/ambiguous": questions.VARIANT_CHOICE,
    "/api/admin/matching/judge/colours": questions.COLOUR_CHOICE,
    "/api/admin/matching/judge/matches": questions.MODEL_MATCH,
}

MODEL_MATCH_LABELS = {
    questions.SAME_MODEL: "The entry's model",
    "sibling": "Another model of the same line",
    "different": "An unrelated model",
    "cant_tell": "Cannot tell",
}

_NO_MATCH_DESCRIPTIONS = {
    questions.BRAND_CHOICE: questions.NO_MATCH_DESCRIPTION,
    questions.VARIANT_CHOICE: questions.VARIANT_NO_MATCH_DESCRIPTION,
    questions.COLOUR_CHOICE: questions.COLOUR_NO_MATCH_DESCRIPTION,
}

_ANY = object()


def _description(row: JudgeVerdict, key: str) -> str | None:
    """What the model was told about an option: kept since criteria were stored, and for
    what never changes — the model check's options and "none of these" — known anyway."""
    if row.criteria is not None:
        return row.criteria.get(key)
    if row.kind == questions.MODEL_MATCH:
        return questions.MODEL_MATCH_CRITERIA.get(key)
    if key == questions.NO_MATCH:
        return _NO_MATCH_DESCRIPTIONS.get(row.kind)
    return None


def _brand_as_asked(row: JudgeVerdict) -> Any:
    """The shop's brand string the question names, or `_ANY` where it names ours."""
    if row.kind == questions.BRAND_CHOICE:
        return row.state.get("brand_as_written")
    if row.kind in (questions.VARIANT_CHOICE, questions.COLOUR_CHOICE):
        return row.state.get("brand")
    return _ANY


def _outcome() -> Any:
    """`_outcome_of`, as SQL, so a list can filter on it. The two have to agree."""
    same = JudgeVerdict.answer["probabilities"][questions.SAME_MODEL].as_float()
    return case(
        (
            JudgeVerdict.kind == questions.MODEL_MATCH,
            case((same < settings.judge_doubt_below, "doubt"), else_="confirmed"),
        ),
        (
            JudgeVerdict.choice == questions.NO_MATCH,
            case(
                (JudgeVerdict.kind == questions.BRAND_CHOICE, "brand_unknown"),
                else_="no_match",
            ),
        ),
        (JudgeVerdict.confidence >= settings.judge_min_confidence, "accepted"),
        else_="below_threshold",
    )


def _outcome_of(row: JudgeVerdict) -> str:
    """What policy made of an answer, as the readers above act on it: "none of these" is
    acted on whatever its confidence, a choice only above the threshold."""
    if row.kind == questions.MODEL_MATCH:
        same = float((row.answer.get("probabilities") or {}).get(questions.SAME_MODEL, 0))
        return "doubt" if same < settings.judge_doubt_below else "confirmed"
    if row.choice == questions.NO_MATCH:
        return "brand_unknown" if row.kind == questions.BRAND_CHOICE else "no_match"
    if float(row.confidence) >= settings.judge_min_confidence:
        return "accepted"
    return "below_threshold"
