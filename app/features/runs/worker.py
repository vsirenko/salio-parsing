"""One run, executed.

    python -m app.features.runs.worker --run-id 42

Spawned by the scheduler, one process per run, so a parser that leaks memory or wedges
takes down its own process and nothing else. A worker always finishes its own run; the
scheduler closes one only when the process is gone and the row is still open.

It reaches the service over HTTP with its own credentials rather than through the
database. A parser is the one thing here that runs hostile input through itself all day,
and what it holds while doing that decides what a compromised one is worth.
"""

import argparse
import asyncio
import logging
from collections import Counter
from dataclasses import replace

from app.core.config import settings
from app.features.runs import channel as channels
from app.features.runs import channels as _registered  # noqa: F401 - registers them
from app.features.runs.channel import Channel, Listing
from app.features.runs.client import Collector, CollectorError
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import (
    FAILURE_SAMPLE,
    ItemFailure,
    Job,
    Kind,
    RunProgress,
    RunResult,
)
from app.features.runs.snapshots import SnapshotStore, SnapshotStoreError

log = logging.getLogger(__name__)


class Failures:
    """The products a run could not bring in, and why — a sample, kept for the run's row.

    The count alone said "12 failed" and nobody could say which twelve: the reasons were in
    this process's log, and the log does not outlive the container.
    """

    def __init__(self) -> None:
        self.items: list[ItemFailure] = []

    def note(self, stage: str, external_id: object, url: str | None, error: object) -> None:
        if len(self.items) >= FAILURE_SAMPLE:
            return
        if isinstance(error, BaseException):
            error = f"{type(error).__name__}: {error}"
        self.items.append(
            ItemFailure(
                stage=stage,
                external_id=str(external_id)[:200] if external_id else None,
                url=url[:1000] if url else None,
                error=str(error)[:500] or "unknown",
            )
        )


class _ParseFailed(Exception):
    """A page that was read and would not parse, apart from one that could not be read."""


async def collect(
    job: Job,
    collector: Collector,
    *,
    fetcher: Fetcher | None = None,
    store: SnapshotStore | None = None,
) -> RunResult:
    """Work through a channel and hand over what it served.

    A full pass opens every card; a cheap one reads what the listing already said. Which
    it is was decided when the run was started, and travels on the job — the worker does
    not get to choose, because then the schedule and the work could disagree.
    """
    channel = channels.get(job.source_slug)
    if channel is None:
        return RunResult(
            items_seen=0,
            items_ingested=0,
            error=f"no channel implementation registered for '{job.source_slug}'",
        )

    store = store or SnapshotStore()
    failures = Failures()
    if job.kind is not Kind.REPARSE:
        # Before a single request: a store that cannot be written to would otherwise be
        # discovered once per product, and a run of 1400 permission errors reads as a shop
        # that served nothing rather than as a volume the daemon created root-owned.
        try:
            store.ensure_writable(job.source_slug)
        except SnapshotStoreError as error:
            return RunResult(items_seen=0, items_ingested=0, error=str(error))

    if job.kind is Kind.REPARSE:
        # No network at all. That is the whole point: a parser is judged against the bytes
        # that were already served, not against the site as it is today.
        seen, payloads, failed = _reparse(job, channel, store, failures)
    else:
        # A channel may ask for less than the default: a shop whose pages sit behind a
        # rate limiter answers 429 at the pace its index is happy with.
        polite = Fetcher(
            rate=getattr(channel, "rate", None),
            concurrency=getattr(channel, "concurrency", None),
            # The channel's proxy, when it has one: the way out to a shop that does not let
            # the server's own address in.
            proxies=job.proxies or None,
        )
        async with fetcher or polite as session:
            try:
                listings = await channel.discover(session, job)
            except Exception as error:  # noqa: BLE001 - discovery failing is the whole run
                # Unlike one product failing, this leaves nothing to collect. Reported
                # rather than raised, so the run carries the reason instead of an exit code.
                return RunResult(
                    items_seen=0,
                    items_ingested=0,
                    error=f"discover: {type(error).__name__}: {error}",
                )

            log.info("run %d: %d listing(s)", job.run_id, len(listings))
            await collector.progress(
                job.run_id, RunProgress(phase="reading", discovered=len(listings))
            )
            return await _read_and_hand_over(
                job, channel, collector, session, store, listings, failures
            )

    ingested, coverage, handover_error = await _hand_over(job, collector, payloads, failures)
    return RunResult(
        items_seen=seen,
        items_ingested=ingested,
        items_failed=failed,
        coverage=coverage,
        error=handover_error,
        failures=failures.items,
    )


async def _read_and_hand_over(
    job: Job,
    channel: Channel,
    collector: Collector,
    fetcher: Fetcher,
    store: SnapshotStore,
    listings: list[Listing],
    failures: Failures | None = None,
) -> RunResult:
    """Read the listings a slice at a time and hand each slice over as it is read.

    A shop used to be read whole and handed over at the end, so nothing a run collected
    reached the database until it was done, and a worker that died at nine tenths had lost
    all of it. A slice keeps the shop's order — each one is read side by side and handed
    over in listing order — so a run can still be compared with the one before it.
    """
    failures = failures or Failures()
    every = settings.worker_handover_every
    ingested = failed = 0
    weighted: Counter[str] = Counter()
    for start in range(0, len(listings), every):
        payloads, broken = await _read_all(
            job, channel, fetcher, store, listings[start : start + every], failures
        )
        failed += broken
        accepted, coverage, error = await _hand_over(job, collector, payloads, failures)
        ingested += accepted
        for field, share in coverage.items():
            weighted[field] += share * accepted
        if error is not None:
            return RunResult(
                items_seen=len(listings),
                items_ingested=ingested,
                items_failed=failed,
                coverage=_share(weighted, ingested),
                error=error,
                failures=failures.items,
            )
        log.info("run %d: %d of %d handed over", job.run_id, ingested, len(listings))
        await collector.progress(
            job.run_id,
            RunProgress(
                phase="reading",
                discovered=len(listings),
                read=min(start + every, len(listings)) - failed,
                failed=failed,
                handed_over=ingested,
            ),
        )
    return RunResult(
        items_seen=len(listings),
        items_ingested=ingested,
        items_failed=failed,
        coverage=_share(weighted, ingested),
        failures=failures.items,
    )


def _reparse(
    job: Job, channel: Channel, store: SnapshotStore, failures: Failures | None = None
) -> tuple[int, list[dict], int]:
    """Read every snapshot this channel has with the parser as it is now.

    Both areas, and the failed one is the reason to run this at all: a product that would
    not parse last time is exactly what a fix was for, and one that parses now stops being
    a broken example.
    """
    failures = failures or Failures()
    good = store.stored(job.source_slug)
    broken = store.stored(job.source_slug, failed=True)

    payloads: list[dict] = []
    failed = 0
    for external_id in sorted(set(good) | set(broken)):
        was_broken = external_id in broken
        snapshot = store.load(job.source_slug, external_id, failed=was_broken)
        if snapshot is None:  # pragma: no cover - listed and then removed
            continue

        try:
            fields = channel.parse(snapshot)
        except Exception as error:  # noqa: BLE001 - a parser may raise anything at all
            failed += 1
            if not was_broken:
                # It parsed before and does not now: the new parser is worse for this one,
                # and the bytes belong with the other broken examples.
                store.save(job.source_slug, snapshot, failed=True)
            log.warning("run %d: %s: %s", job.run_id, external_id, error)
            failures.note("parse", snapshot.external_id or external_id, snapshot.url, error)
            continue

        if was_broken:
            store.save(job.source_slug, snapshot)
            store.forget_failure(job.source_slug, external_id)

        payloads.append(
            {
                # The snapshot's own id, not the one the filename yielded. A file name has
                # to be safe to put in a path, so `MJXP4HX/A` is stored as `MJXP4HX_A` —
                # and reported under that name a reparse does not re-read the product, it
                # invents a second one beside it. cec's Apple codes all carry that slash,
                # and one reparse doubled the shop from 92 listings to 184.
                "external_id": snapshot.external_id or external_id,
                "payload": fields,
                "url": snapshot.url,
                "seller_external_id": snapshot.seller_external_id,
            }
        )

    return len(good) + len(broken), payloads, failed


async def _read_all(
    job: Job,
    channel: Channel,
    fetcher: Fetcher,
    store: SnapshotStore,
    listings: list[Listing],
    failures: Failures | None = None,
) -> tuple[list[dict], int]:
    """Turn listings into observations, keeping the bytes that produced each one.

    One product failing is one product failing. A run that threw away eight hundred
    listings because the nine hundredth had a broken price would be reporting the shop as
    closed, which is exactly what the contract exists to prevent.

    **Products are read side by side, and the shop still sees one polite crawler.** The
    throttle is not here: `Fetcher` bounds how many requests are open at once and how many
    are started per second, so the rate is the same whether one product is in flight or a
    hundred. What was here instead was a loop that awaited each product before starting the
    next, which pinned the whole run to one slot and left the others idle — a shop of 1400
    cards took half an hour to read at a rate that reads it in ten minutes. The pool is
    sized to the fetcher's own concurrency, because a product usually costs one request and
    more tasks than slots would only queue against the gate.
    """
    failures = failures or Failures()
    if job.kind is Kind.QUICK:
        # A cheap pass opens nothing: the listing already carried the facts, so there is no
        # waiting to overlap and a pool would be machinery for its own sake.
        return _read_cards(job, channel, listings, failures)

    # Positional, so the order a run reports is the order the shop listed in however the
    # requests happen to finish. A run that shuffles its own output cannot be diffed
    # against the one before it.
    observations: list[dict | None] = [None] * len(listings)
    failed = 0
    room = asyncio.Semaphore(max(1, settings.fetch_concurrency))

    async def read_one(position: int, listing: Listing) -> None:
        nonlocal failed
        async with room:
            try:
                observations[position] = await _observe(job, channel, fetcher, store, listing)
            except _ParseFailed as error:
                failed += 1
                log.warning("run %d: %s: %s", job.run_id, listing.external_id, error.__cause__)
                failures.note("parse", listing.external_id, listing.url, error.__cause__)
            except Exception as error:  # noqa: BLE001 - a parser may raise anything at all
                failed += 1
                log.warning("run %d: %s: %s", job.run_id, listing.external_id, error)
                failures.note("fetch", listing.external_id, listing.url, error)

    await asyncio.gather(
        *(read_one(position, listing) for position, listing in enumerate(listings))
    )
    return [seen for seen in observations if seen is not None], failed


async def _observe(
    job: Job,
    channel: Channel,
    fetcher: Fetcher,
    store: SnapshotStore,
    listing: Listing,
) -> dict:
    """One product: its requests, its snapshot, its fields."""
    snapshot = await channel.fetch(fetcher, listing)
    # Filled here rather than in every channel: the worker has the listing and a parser
    # should not have to remember to carry it.
    snapshot = replace(
        snapshot,
        url=snapshot.url or listing.url,
        seller_external_id=snapshot.seller_external_id or listing.seller_external_id,
    )
    try:
        fields = channel.parse(snapshot)
    except Exception as error:
        # Kept apart so the parser can be fixed against the exact bytes that broke it,
        # which is a five-minute job rather than another crawl.
        store.save(job.source_slug, snapshot, failed=True)
        raise _ParseFailed(str(error)) from error

    store.save(job.source_slug, snapshot)
    store.forget_failure(job.source_slug, listing.external_id)
    return {
        "external_id": listing.external_id,
        "payload": fields,
        "url": listing.url,
        "seller_external_id": listing.seller_external_id,
    }


def _read_cards(
    job: Job, channel: Channel, listings: list[Listing], failures: Failures | None = None
) -> tuple[list[dict], int]:
    """What the listing already told us, for a pass that opens no cards."""
    failures = failures or Failures()
    payloads: list[dict] = []
    failed = 0
    for listing in listings:
        try:
            fields = channel.read_listing(listing)
        except Exception as error:  # noqa: BLE001 - a parser may raise anything at all
            failed += 1
            log.warning("run %d: %s: %s", job.run_id, listing.external_id, error)
            failures.note("parse", listing.external_id, listing.url, error)
            continue
        payloads.append(
            {
                "external_id": listing.external_id,
                "payload": fields,
                "url": listing.url,
                "seller_external_id": listing.seller_external_id,
            }
        )
    return payloads, failed


async def _hand_over(
    job: Job, collector: Collector, payloads: list[dict], failures: Failures | None = None
) -> tuple[int, dict[str, float], str | None]:
    """Post in batches, summing the coverage the service measured.

    Coverage comes back from the service rather than being computed here: it has to be the
    same reading the matcher will use, or the number describes the parser's opinion of
    itself.
    """
    if not payloads:
        return 0, {}, None

    market = job.market_codes[0] if job.market_codes else None
    if market is None:
        return 0, {}, "the shop is shown in no market, so there is nowhere to put its offers"

    ingested = 0
    seen: Counter[str] = Counter()
    for start in range(0, len(payloads), settings.max_batch_offers):
        chunk = payloads[start : start + settings.max_batch_offers]
        try:
            result = await collector.hand_over(
                job.source_id,
                {"market_code": market, "run_id": job.run_id, "offers": chunk},
            )
        except CollectorError as error:
            return ingested, _share(seen, ingested), f"handing over: {error}"

        ingested += result["accepted"]
        if failures is not None:
            urls = {item["external_id"]: item.get("url") for item in chunk}
            for refused in result.get("failures") or []:
                failures.note(
                    "ingest",
                    refused.get("external_id"),
                    urls.get(refused.get("external_id")),
                    f"{refused.get('code')}: {refused.get('message')}",
                )
        for field, share in result.get("coverage", {}).items():
            seen[field] += share * result["accepted"]

    return ingested, _share(seen, ingested), None


def _share(seen: Counter[str], total: int) -> dict[str, float]:
    if not total:
        return {}
    return {field: round(count / total, 4) for field, count in sorted(seen.items())}


async def main(run_id: int, *, collector: Collector | None = None) -> int:
    async with collector or Collector() as session:
        try:
            job = await session.job(run_id)
        except CollectorError as error:
            # Nothing can be reported through a service that cannot be reached. The
            # scheduler notices the exit code and closes the run itself.
            log.error("run %d: %s", run_id, error)
            return 1

        try:
            result = await collect(job, session)
        except Exception as error:  # noqa: BLE001 - a parser may raise anything at all
            result = RunResult(
                items_seen=0, items_ingested=0, error=f"{type(error).__name__}: {error}"
            )

        try:
            await session.finish(run_id, result)
        except CollectorError as error:
            log.error("run %d finished but could not be reported: %s", run_id, error)
            return 1

    if result.error:
        log.error("run %d failed: %s", run_id, result.error)
        return 1
    log.info("run %d collected %d item(s)", run_id, result.items_ingested)
    return 0


if __name__ == "__main__":  # pragma: no cover
    from app.core.logging import configure_logging

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    arguments = parser.parse_args()

    configure_logging()
    raise SystemExit(asyncio.run(main(arguments.run_id)))
