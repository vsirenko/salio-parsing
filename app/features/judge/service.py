"""Asking an outside model a bounded question, and remembering what it said.

This feature knows nothing about offers, the match queue or why anything is being asked.
It takes a question, answers it once, and stores the answer. Whoever needs a judgement
owns the decision to want one — which is what keeps an outside dependency from spreading
through the matcher.
"""

import asyncio
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeError,
)

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.db.models import Brand, Category, JudgeVerdict, Variant
from app.db.query import paginated
from app.features.judge import questions
from app.features.judge.questions import Candidate, Question
from app.features.judge.schemas import BrandRequest, BrandVerdict, JudgeReport, VerdictRead
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


class JudgeService:
    def __init__(self, session: AsyncSession, client_factory: ClientFactory = build_client) -> None:
        self.session = session
        self._client_factory = client_factory

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

        asked, failed, error, usage = await self._ask_all(unanswered, verdicts)
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

    async def _ask_all(
        self,
        unanswered: list[tuple[BrandRequest, Question]],
        verdicts: dict[int, BrandVerdict],
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
                verdicts[request.key] = self._read(stored, question)

        return asked, failed, error, (tokens_in, tokens_out)

    # --- writing ---

    async def _store(self, question: Question, response: SystemOneResponse) -> JudgeVerdict:
        answer = response.choices[question.kind]
        verdict = JudgeVerdict(
            kind=question.kind,
            question_hash=question.hash,
            state=question.state,
            options=list(question.criteria),
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
        self, pagination: Pagination, *, kind: str | None = None
    ) -> tuple[list[VerdictRead], int]:
        stmt = select(JudgeVerdict)
        if kind is not None:
            stmt = stmt.where(JudgeVerdict.kind == kind)
        rows, total = await paginated(
            self.session, stmt.order_by(JudgeVerdict.id.desc()), pagination
        )
        return [VerdictRead.model_validate(row) for row in rows], total

    async def _stored(self, question_hash: str) -> JudgeVerdict | None:
        return await self.session.scalar(
            select(JudgeVerdict).where(JudgeVerdict.question_hash == question_hash)
        )

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
