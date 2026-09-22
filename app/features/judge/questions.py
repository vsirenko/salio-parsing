"""The questions the judge asks, and the key that keeps one from being asked twice."""

import hashlib
import json
from dataclasses import dataclass

from app.core.config import settings

BRAND_CHOICE = "brand_choice"
VARIANT_CHOICE = "variant_choice"

# A Choice has to be able to answer "neither". Without a way out the model can only pick
# one of the options it was handed, and it will do that as confidently as any other
# answer — which is the one failure mode that produces a wrong match rather than no match.
NO_MATCH = "none_of_these"

BRAND_INSTRUCTIONS = (
    "A shop has listed this product. Several unrelated companies trade under the brand"
    " name the listing states, so decide which of them makes this particular product."
    " Judge from what the listing is about: the kind of product, the model designation,"
    " and the words in the title."
)

NO_MATCH_DESCRIPTION = (
    "None of the companies above makes this kind of product, or the listing does not say"
    " enough to tell them apart."
)

VARIANT_INSTRUCTIONS = (
    "A shop has listed a product that this catalogue already holds in several versions,"
    " and they differ only in the ways listed below — usually the colour the maker gave"
    " it. Decide which version the listing is. The maker's own name for a colour is the"
    " thing to judge on: it is in the listing's title and it is not a plain colour word."
)

VARIANT_NO_MATCH_DESCRIPTION = (
    "The listing is none of the versions above, or its title does not say which one it is."
)


@dataclass(frozen=True)
class Candidate:
    """One brand a listing might mean, described by what it is known to make.

    The description is built from the categories the brand already has variants in, and
    from nothing else. It is the only thing we actually know to be true about it, and an
    invented description would be answered just as confidently as a real one.
    """

    brand_id: int
    slug: str
    canonical_name: str
    categories: tuple[str, ...]

    def describe(self) -> str | None:
        if not self.categories:
            # Nothing in the catalogue under this brand yet, so there is nothing true to
            # say. Saying nothing is correct: the answer should come back unconfident,
            # and an unconfident answer is one this is built to ignore.
            return None
        return f"{self.canonical_name}, which this catalogue lists under: " + ", ".join(
            self.categories
        )


@dataclass(frozen=True)
class Option:
    """One catalogue entry a listing might be, described by what tells it from the others.

    The description is the axes it holds — `colour: black`, `capacity: 256 GB` — and
    nothing else. Those are what the entries differ in, and they are what the catalogue
    actually knows; a title would describe every option the same way and decide nothing.
    """

    variant_id: int
    slug: str
    axes: tuple[tuple[str, str], ...]

    def describe(self) -> str | None:
        if not self.axes:
            # An entry that records none of the axes cannot be told from its neighbours,
            # so there is nothing true to say and the answer should come back unconfident.
            return None
        return ", ".join(f"{name}: {value}" for name, value in self.axes)


@dataclass(frozen=True)
class Question:
    """A question ready to send, and the identity that decides whether it has to be."""

    kind: str
    state: dict
    instructions: str
    criteria: dict[str, str | None]
    # Option key back to the row it stands for. The option keys are brand slugs: unique,
    # stable, and readable in a stored verdict months later, which an id is not.
    by_option: dict[str, int]
    hash: str


def brand_choice(
    *,
    title: str | None,
    brand_raw: str | None,
    model_raw: str | None,
    candidates: list[Candidate],
) -> Question:
    """Which of these companies made the thing in this listing.

    Named fields rather than one blob: the docs ask for state a question can be answered
    from, and "the brand field said Delta" is a different fact from "the title says tap".
    """
    state = {
        "listing_title": title,
        "brand_as_written": brand_raw,
        "model_as_written": model_raw,
    }
    ordered = sorted(candidates, key=lambda candidate: candidate.slug)
    criteria: dict[str, str | None] = {
        candidate.slug: candidate.describe() for candidate in ordered
    }
    criteria[NO_MATCH] = NO_MATCH_DESCRIPTION

    return Question(
        kind=BRAND_CHOICE,
        state=state,
        instructions=BRAND_INSTRUCTIONS,
        criteria=criteria,
        by_option={candidate.slug: candidate.brand_id for candidate in ordered},
        hash=_identity(BRAND_CHOICE, state, criteria),
    )


def _identity(kind: str, state: dict, criteria: dict) -> str:
    """What makes two questions the same question.

    Covers the state and the options exactly as they will be sent, so a listing whose
    title changed, or whose candidates changed because a brand was added, is a new
    question and gets asked again rather than answered from a stale store.

    The configured model name is in the key, not the one that answered. Pinning a version
    is a deliberate act and deserves fresh answers; `jev-latest` moving underneath is not,
    and should not silently invalidate everything ever asked.
    """
    payload = json.dumps(
        {"kind": kind, "model": settings.typesafe_model, "state": state, "criteria": criteria},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def variant_choice(
    *,
    title: str | None,
    brand: str | None,
    model: str | None,
    options: list[Option],
) -> Question:
    """Which of these catalogue entries the listing is.

    The state names the maker separately from the title on purpose: a marketing colour
    belongs to a maker — `Canyon` is pink on a Google and orange on an Oppo, both proved by
    two shops — so the brand is part of the question and not decoration.
    """
    state = {
        "listing_title": title,
        "brand": brand,
        "model": model,
    }
    ordered = sorted(options, key=lambda option: option.slug)
    criteria: dict[str, str | None] = {option.slug: option.describe() for option in ordered}
    criteria[NO_MATCH] = VARIANT_NO_MATCH_DESCRIPTION

    return Question(
        kind=VARIANT_CHOICE,
        state=state,
        instructions=VARIANT_INSTRUCTIONS,
        criteria=criteria,
        by_option={option.slug: option.variant_id for option in ordered},
        hash=_identity(VARIANT_CHOICE, state, criteria),
    )
