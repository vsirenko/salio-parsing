"""What a channel is, as far as the collector is concerned.

Four methods, and everything specific to a shop lives behind them. The split is not
arbitrary: it follows what each step costs and what it is allowed to touch.

- `discover` is one request, or a few pages, and yields what the listing already knows.
- `fetch` is the expensive part, one product at a time, and is the only step that may
  reach the network for a single item.
- `parse` is **pure**. Given a saved response it must produce the same result with no
  network at all, which is what makes a parser fixable against the bytes that broke it
  rather than against the site as it is today.
- `read_listing` is how a cheap pass gets its facts without opening a card.

A channel returns the shop's own shapes, not ours. Turning `ATMIŅA / Iekšējā atmiņa (GB)`
into an attribute is the service's job, done against stored raw data and re-runnable; a
parser that normalised as it went would bake its mistakes into the only copy there is.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from app.features.runs.schemas import Job


@dataclass(frozen=True)
class Listing:
    """One product as the listing page knows it.

    `card` is whatever the listing carried about it — often a price and a stock flag,
    sometimes a whole JSON blob. It is what a cheap pass reads instead of opening the
    product page.
    """

    external_id: str
    url: str
    card: dict[str, Any] = field(default_factory=dict)
    seller_external_id: str | None = None


@dataclass(frozen=True)
class Part:
    """One response that went into a snapshot.

    `role` is what it was for — `detail`, `stock`, `variants`. Some shops assemble a
    product from several requests, and a snapshot that flattened them into one blob would
    lose which was which.
    """

    role: str
    url: str
    status: int
    body: str


@dataclass(frozen=True)
class Snapshot:
    """Everything the shop served for one product, kept so parsing can be redone.

    The reason it exists: a parser is wrong more often than a site changes, and every fix
    is worth only what it costs to re-apply. With a snapshot that cost is nothing; without
    one it is another crawl of the whole shop.
    """

    external_id: str
    parts: list[Part]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Carried so a re-read can produce the same observation the crawl did. A snapshot with
    # only bytes in it cannot say which trader on a marketplace the listing belonged to,
    # and a reparse of one would fail on every item for want of a fact it already had. A
    # channel does not have to set these: the worker fills them from the listing.
    url: str | None = None
    seller_external_id: str | None = None

    def part(self, role: str) -> Part | None:
        return next((part for part in self.parts if part.role == role), None)


@runtime_checkable
class Channel(Protocol):
    """One way into one shop. Registered by the slug of the source it serves."""

    slug: str

    async def discover(self, fetcher: Any, job: Job) -> list[Listing]:
        """Everything on offer, as cheaply as the shop allows."""
        ...

    async def fetch(self, fetcher: Any, listing: Listing) -> Snapshot:
        """Every request one product needs. The expensive step."""
        ...

    def parse(self, snapshot: Snapshot) -> dict[str, Any]:
        """A snapshot to the shop's own fields. Pure: no network, no clock, no randomness."""
        ...

    def read_listing(self, listing: Listing) -> dict[str, Any]:
        """What the listing already told us, for a pass that opens no cards."""
        ...


CHANNELS: dict[str, Channel] = {}


def register(channel: Channel) -> Channel:
    """Add a channel. Adding one is all it takes — nothing else changes.

    Keyed by source slug rather than by shop: a shop can have several channels, and which
    one is running is exactly what the slug names.
    """
    if channel.slug in CHANNELS:
        raise ValueError(f"a channel is already registered for '{channel.slug}'")
    CHANNELS[channel.slug] = channel
    return channel


def get(slug: str) -> Channel | None:
    return CHANNELS.get(slug)
