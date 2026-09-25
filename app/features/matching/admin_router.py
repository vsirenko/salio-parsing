"""Matching behind the admin panel.

POST   /api/admin/offers/{id}/match     run the ladder on one listing
PUT    /api/admin/offers/{id}/match     a human places it
DELETE /api/admin/offers/{id}/match     unlink, back to the queue
GET    /api/admin/offers/{id}/matches   every opinion ever held about it
POST   /api/admin/matching/run          work through what is unplaced
GET    /api/admin/match-queue           what could not be placed, and why
GET    /api/admin/match-queue/summary   the breakdown that says what to build next
GET    /api/admin/match-queue/{id}      one row
POST · DELETE /api/admin/match-queue/{id}/snooze  set aside until, or bring back
GET    /api/admin/matching/judge/pending  what each judge pass would pay for now
POST   /api/admin/matching/judge        ask the judge about the brand choices, then retry
POST   /api/admin/matching/judge/colours  buy the colour a title carries and no rule reads
POST   /api/admin/matching/judge/matches  ask whether each rule's match names the right model
GET    /api/admin/matching/doubts   the matches the judge doubts, for a person
POST   /api/admin/matching/doubts/{id}/keep  a person looked and left it
POST   /api/admin/offers/{id}/promote   make the variant this listing was looking for
POST   /api/admin/matching/promote      do that for everything identifiable in the queue
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import MatchingServiceDep
from app.api.pagination import pagination_params
from app.features.judge.schemas import JudgeReport, PendingKind
from app.features.matching.schemas import (
    DOUBT_SORT,
    QUEUE_SORT,
    DoubtKept,
    ManualMatch,
    MatchDoubtRead,
    MatchOutcome,
    MatchQueueRead,
    MergePair,
    MergeReport,
    Method,
    OfferMatchRead,
    PairMerge,
    PromotionReport,
    QueueSummary,
    Reason,
    RenameReport,
    RunReport,
    Snooze,
    SuspectKind,
    SuspectReport,
)
from app.schemas.common import ErrorResponse
from app.schemas.pagination import Page, Pagination

offers_router = APIRouter(prefix="/offers", tags=["admin: matching"])
router = APIRouter(prefix="/matching", tags=["admin: matching"])
queue_router = APIRouter(prefix="/match-queue", tags=["admin: matching"])

PageParams = Annotated[Pagination, Depends(pagination_params())]
QueuePageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=QUEUE_SORT, default_sort="offer_id"))
]
DoubtPageParams = Annotated[
    Pagination, Depends(pagination_params(sortable=DOUBT_SORT, default_sort="offer_id"))
]
DryRun = Annotated[
    bool,
    Query(description="Compute the same report and keep none of it: nothing is written"),
]


@offers_router.post(
    "/{offer_id}/match",
    response_model=MatchOutcome,
    summary="Run the ladder on one listing",
    responses={
        404: {"model": ErrorResponse, "description": "Offer not found"},
        422: {"model": ErrorResponse, "description": "Nothing has been read from it yet"},
    },
)
async def match_offer(offer_id: int, service: MatchingServiceDep) -> MatchOutcome:
    """Barcode, then brand with a part number, then brand with a model.

    Each rung is an index lookup rather than a scan. One hit is a match; several are
    `ambiguous`; none moves down a rung, and running out of rungs says exactly why.
    """
    return await service.match_offer(offer_id)


@offers_router.put(
    "/{offer_id}/match",
    response_model=MatchOutcome,
    summary="Place a listing by hand",
    responses={404: {"model": ErrorResponse, "description": "Offer or variant not found"}},
)
async def set_manually(
    offer_id: int, payload: ManualMatch, service: MatchingServiceDep
) -> MatchOutcome:
    """Supersedes whatever was thought before rather than overwriting it, so the previous
    opinion and its evidence survive."""
    return await service.set_manually(offer_id, payload)


@offers_router.delete(
    "/{offer_id}/match",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a listing",
    responses={404: {"model": ErrorResponse, "description": "No active match"}},
)
async def unlink(offer_id: int, service: MatchingServiceDep) -> Response:
    await service.unlink(offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@offers_router.get(
    "/{offer_id}/matches",
    response_model=list[OfferMatchRead],
    summary="Every opinion held about one listing",
)
async def history(offer_id: int, service: MatchingServiceDep) -> list[OfferMatchRead]:
    """Newest first. A superseded row is kept on purpose: a link that turned out wrong is
    worth more as a record than as a deletion."""
    return await service.history(offer_id)


@router.post("/run", response_model=RunReport, summary="Work through what is unplaced")
async def run(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000, description="How many to attempt")] = 100,
) -> RunReport:
    """Skips listings that already have a live match, retries queued ones — the catalogue
    they failed against changes underneath them."""
    return await service.run(limit=limit)


@offers_router.post(
    "/{offer_id}/promote",
    response_model=MatchOutcome,
    summary="Make the variant this listing was looking for",
    responses={
        404: {"model": ErrorResponse, "description": "Offer not found"},
        422: {"model": ErrorResponse, "description": "Not enough to build a variant from"},
    },
)
async def promote(
    offer_id: int, service: MatchingServiceDep, dry_run: DryRun = False
) -> MatchOutcome:
    """The catalogue has to start somewhere, and only the shops know what is in them.

    Deliberately not a new kind of match: the variant is created and then the ordinary
    ladder runs, so the link records the rung that actually fired rather than a method
    meaning "we made this from itself". Where the variant came from is in the audit trail.
    """
    return await service.promote(offer_id, dry_run=dry_run)


@router.post(
    "/promote",
    response_model=PromotionReport,
    summary="Start the catalogue from what can be identified",
)
async def promote_queue(
    service: MatchingServiceDep,
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="How many to consider. ~17 ms each at worst"),
    ] = 100,
    dry_run: DryRun = False,
) -> PromotionReport:
    """Takes only listings that carry a barcode and come from a channel we trust.

    A variant made from a junk listing cannot afterwards be told from a real one, so the
    rest stay queued where somebody can look at them. Each candidate is matched before it
    is promoted, because the one before it may have just created the variant it needed.
    """
    return await service.promote_queue(limit=limit, dry_run=dry_run)


@router.get(
    "/suspects",
    response_model=SuspectReport,
    summary="Entries and families that look filed twice",
)
async def list_suspects(
    service: MatchingServiceDep,
    category_id: Annotated[int | None, Query()] = None,
    brand_id: Annotated[int | None, Query()] = None,
    kind: Annotated[list[SuspectKind] | None, Query(description="Repeatable")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SuspectReport:
    """A queue to read, not a pass that acts: one part number on entries that agree on every
    axis (`merge`), one model at two nearly equal numbers (`axis` — a reading to fix), one
    name in several word orders or cases (`registry` — aliases to enter). The ones holding
    the most listings first."""
    return await service.suspects(
        category_id=category_id, brand_id=brand_id, kinds=kind, limit=limit
    )


@router.post(
    "/merge/pair",
    response_model=MergePair,
    summary="Fold one chosen entry into another",
    responses={
        404: {"model": ErrorResponse, "description": "An entry not found"},
        409: {"model": ErrorResponse, "description": "They differ on an axis, or not one thing"},
        422: {"model": ErrorResponse, "description": "The same entry twice"},
    },
)
async def merge_pair(payload: PairMerge, service: MatchingServiceDep) -> MergePair:
    """What a `merge` suspect, or a person, says is one product. Refused with
    `axes_differ` where the entries disagree on an axis, unless `despite_axes`; the survivor's
    values stand. The folded entry's id keeps resolving to the survivor."""
    return await service.merge_pair(payload)


@router.post(
    "/merge",
    response_model=MergeReport,
    summary="Fold together the entries a barcode or a part number says are one product",
)
async def merge_duplicates(
    service: MatchingServiceDep,
    limit: Annotated[
        int, Query(ge=1, le=500, description="How many pairs to consider. ~90 ms each")
    ] = 100,
    dry_run: DryRun = False,
) -> MergeReport:
    """A barcode decides, and so does a part number of a maker whose part numbers name one
    configuration (Apple). Elsewhere a part number names a family as often as a product, so
    two entries sharing one are usually two real configurations. A pair whose entries
    disagree on an axis is refused either way."""
    return await service.merge_duplicates(limit=limit, dry_run=dry_run)


@router.post(
    "/rebuild",
    response_model=RenameReport,
    summary="Rebuild the entries named after a reading that has since changed",
)
async def rebuild_stale(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=500, description="How many to consider")] = 100,
) -> RenameReport:
    """Only an entry with one listing on it. Two shops agreeing on an entry is evidence its
    name is good enough, and one of them disagreeing about a `5G` suffix is not a reason to
    rename what they share."""
    return await service.rebuild_named_from_a_stale_reading(limit=limit)


@router.post(
    "/judge/ambiguous",
    response_model=JudgeReport,
    summary="Ask the judge which entry a listing is",
)
async def judge_ambiguous(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200, description="How many to ask about")] = 50,
) -> JudgeReport:
    """Only `ambiguous`, and only after the corpus has been asked and could not answer: a
    marketing colour belongs to a maker, and no global registry row can hold it."""
    return await service.judge_ambiguous(limit=limit)


@router.post(
    "/judge/colours",
    response_model=JudgeReport,
    summary="Ask the judge what colour a listing is",
)
async def judge_colours(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=200, description="How many to ask about")] = 50,
) -> JudgeReport:
    """For listings whose colour is in the title, where no rule may cut it out: 53 of the 57
    this was written for keep it there. The answer is kept against the title and the maker
    rather than entered in the registry — `Canyon` is pink on a Google and orange on an
    Oppo, so a global alias would be wrong somewhere."""
    return await service.judge_colours(limit=limit)


@router.post(
    "/judge/matches",
    response_model=JudgeReport,
    summary="Ask whether each rule's match names the right model",
    responses={422: {"model": ErrorResponse, "description": "No TypeSafe API key configured"}},
)
async def check_matches(
    service: MatchingServiceDep,
    limit: Annotated[
        int, Query(ge=1, le=2000, description="How many new questions to pay for")
    ] = 500,
) -> JudgeReport:
    """Every live match a rule made, asked about by the listing's title and the entry's
    name. Answers already held are free and do not count against `limit`, so repeated
    passes work through the catalogue and then pay only for what is new. Nothing is moved:
    what comes out is `GET /doubts`."""
    return await service.check_matches(limit=limit)


@router.get(
    "/doubts",
    response_model=Page[MatchDoubtRead],
    summary="The matches the judge doubts",
)
async def doubts(
    service: MatchingServiceDep,
    pagination: DoubtPageParams,
    method: Annotated[
        list[Method] | None, Query(description="What placed it. Repeat for several")
    ] = None,
    shop_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
) -> Page[MatchDoubtRead]:
    """Live rule matches whose verdict gives the listing less than `JUDGE_DOUBT_BELOW` chance
    of naming the entry's own model. Each one is a decision for a person — unlink, split,
    merge or leave it (`POST /doubts/{offer_id}/keep`). `sort=same` puts the surest
    doubts first."""
    items, total = await service.doubts(
        pagination,
        methods=[value.value for value in method or []],
        shop_ids=shop_id,
    )
    return Page[MatchDoubtRead].of(items, total, pagination)


@router.post(
    "/doubts/{offer_id}/keep",
    response_model=DoubtKept,
    summary="A person looked at a doubted match and left it",
    responses={
        404: {"model": ErrorResponse, "description": "No active match"},
        409: {"model": ErrorResponse, "description": "Not a rule's match"},
    },
)
async def keep_doubted(offer_id: int, service: MatchingServiceDep) -> DoubtKept:
    """The same entry by the same signal, now decided by a person: the rule's match is
    superseded and stays in the history, and a person's decision survives the next pass.
    It leaves `GET /doubts`, which is only about what a rule decided."""
    return await service.keep_doubted(offer_id)


@router.get(
    "/judge/pending",
    response_model=list[PendingKind],
    summary="What each judge pass would pay for now",
)
async def judge_pending(service: MatchingServiceDep) -> list[PendingKind]:
    """Per kind: the listings a pass would consider with no limit, the distinct questions
    among them the store cannot answer, and their tokens at this kind's average. Asks
    nothing and writes nothing."""
    return await service.judge_pending()


@router.post(
    "/judge",
    response_model=JudgeReport,
    summary="Ask the judge about the brand choices",
    responses={422: {"model": ErrorResponse, "description": "No TypeSafe API key configured"}},
)
async def judge_brands(
    service: MatchingServiceDep,
    limit: Annotated[int, Query(ge=1, le=500, description="How many to ask about")] = 50,
) -> JudgeReport:
    """Works `brand_ambiguous` and nothing else: it is the bucket that arrives with its
    options already in hand, and choosing between options is the only thing the judge does.

    A question already answered is not asked again, so running this twice costs nothing the
    second time. Answers below the confidence threshold are recorded and not acted on.
    """
    return await service.judge_brands(limit=limit)


@queue_router.get("/summary", response_model=QueueSummary, summary="What is in the way")
async def summary(service: MatchingServiceDep) -> QueueSummary:
    """The breakdown that decides what to build next.

    Mostly `signals_unmatched` means the work is creating variants. `brand_unknown` means
    reading raw strings and naming the brand behind them; `no_signals` means pulling
    identity out of titles. `brand_ambiguous` and `ambiguous` are the buckets that already
    carry their candidates, so they are the two a pair judge can help with — and if both are
    nearly empty, a judge is not what this needs.
    """
    return await service.summary()


@queue_router.get("", response_model=Page[MatchQueueRead], summary="What could not be placed")
async def queue(
    service: MatchingServiceDep,
    pagination: QueuePageParams,
    reason: Annotated[
        list[Reason] | None, Query(description="One kind of problem. Repeat for several")
    ] = None,
    shop_id: Annotated[list[int] | None, Query(description="Repeat for several")] = None,
    brand_id: Annotated[
        list[int] | None,
        Query(description="The brand the matcher settled on. Repeat for several"),
    ] = None,
    category_id: Annotated[
        list[int] | None, Query(description="What the channel collects. Repeat for several")
    ] = None,
    search: Annotated[
        str | None,
        Query(max_length=200, description="Title or the shop's id contains; barcode equals"),
    ] = None,
    include_snoozed: Annotated[
        bool, Query(description="Also the rows a person set aside until later")
    ] = False,
) -> Page[MatchQueueRead]:
    """Each row carries its listing and the near misses that were considered, compared axis
    by axis with it, so deciding is a choice rather than a search. `sort=-siblings` puts
    first the brand and model whose one new entry would place the most listings."""
    items, total = await service.queue(
        pagination,
        reasons=[value.value for value in reason or []],
        shop_ids=shop_id,
        brand_ids=brand_id,
        category_ids=category_id,
        search=search,
        include_snoozed=include_snoozed,
    )
    return Page[MatchQueueRead].of(items, total, pagination)


@queue_router.get(
    "/{offer_id}",
    response_model=MatchQueueRead,
    summary="One queued listing",
    responses={404: {"model": ErrorResponse, "description": "Not queued"}},
)
async def queue_row(offer_id: int, service: MatchingServiceDep) -> MatchQueueRead:
    return await service.queue_row(offer_id)


@queue_router.post(
    "/{offer_id}/snooze",
    response_model=MatchQueueRead,
    summary="Set a queued listing aside until a time",
    responses={
        404: {"model": ErrorResponse, "description": "Not queued"},
        422: {"model": ErrorResponse, "description": "A time in the past, or with no zone"},
    },
)
async def snooze(offer_id: int, payload: Snooze, service: MatchingServiceDep) -> MatchQueueRead:
    """Hidden from the queue until then. The matcher still retries it, and the promotion
    sweep leaves it alone: a person has said not now."""
    return await service.snooze(offer_id, payload)


@queue_router.delete(
    "/{offer_id}/snooze",
    response_model=MatchQueueRead,
    summary="Bring a snoozed listing back",
    responses={404: {"model": ErrorResponse, "description": "Not queued"}},
)
async def unsnooze(offer_id: int, service: MatchingServiceDep) -> MatchQueueRead:
    return await service.unsnooze(offer_id)
