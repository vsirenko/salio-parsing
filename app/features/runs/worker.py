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
from app.features.runs.channel import Channel, Listing
from app.features.runs.client import Collector, CollectorError
from app.features.runs.fetching import Fetcher
from app.features.runs.schemas import Job, Kind, RunResult
from app.features.runs.snapshots import SnapshotStore

log = logging.getLogger(__name__)


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

    if job.kind is Kind.REPARSE:
        # No network at all. That is the whole point: a parser is judged against the bytes
        # that were already served, not against the site as it is today.
        seen, payloads, failed = _reparse(job, channel, store)
    else:
        async with fetcher or Fetcher() as session:
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
            seen = len(listings)
            payloads, failed = await _read_all(job, channel, session, store, listings)

    ingested, coverage, handover_error = await _hand_over(job, collector, payloads)
    return RunResult(
        items_seen=seen,
        items_ingested=ingested,
        items_failed=failed,
        coverage=coverage,
        error=handover_error,
    )


def _reparse(job: Job, channel: Channel, store: SnapshotStore) -> tuple[int, list[dict], int]:
    """Read every snapshot this channel has with the parser as it is now.

    Both areas, and the failed one is the reason to run this at all: a product that would
    not parse last time is exactly what a fix was for, and one that parses now stops being
    a broken example.
    """
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
            continue

        if was_broken:
            store.save(job.source_slug, snapshot)
            store.forget_failure(job.source_slug, external_id)

        payloads.append(
            {
                "external_id": external_id,
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
) -> tuple[list[dict], int]:
    """Turn listings into observations, keeping the bytes that produced each one.

    One product failing is one product failing. A run that threw away eight hundred
    listings because the nine hundredth had a broken price would be reporting the shop as
    closed, which is exactly what the contract exists to prevent.
    """
    payloads: list[dict] = []
    failed = 0

    for listing in listings:
        try:
            if job.kind is Kind.QUICK:
                fields = channel.read_listing(listing)
            else:
                snapshot = await channel.fetch(fetcher, listing)
                # Filled here rather than in every channel: the worker has the listing and
                # a parser should not have to remember to carry it.
                snapshot = replace(
                    snapshot,
                    url=snapshot.url or listing.url,
                    seller_external_id=snapshot.seller_external_id or listing.seller_external_id,
                )
                try:
                    fields = channel.parse(snapshot)
                except Exception:
                    # Kept apart so the parser can be fixed against the exact bytes that
                    # broke it, which is a five-minute job rather than another crawl.
                    store.save(job.source_slug, snapshot, failed=True)
                    raise
                store.save(job.source_slug, snapshot)
                store.forget_failure(job.source_slug, listing.external_id)
        except Exception as error:  # noqa: BLE001 - a parser may raise anything at all
            failed += 1
            log.warning("run %d: %s: %s", job.run_id, listing.external_id, error)
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
    job: Job, collector: Collector, payloads: list[dict]
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
