"""The questions the judge asks, and the key that keeps one from being asked twice."""

import hashlib
import json
from dataclasses import dataclass

from app.core.config import settings

BRAND_CHOICE = "brand_choice"
VARIANT_CHOICE = "variant_choice"
COLOUR_CHOICE = "colour_choice"
MODEL_MATCH = "model_match"

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

COLOUR_INSTRUCTIONS = (
    "A shop has listed a product whose title carries the maker's own name for its colour —"
    " a word like Coralred or Blueberry rather than a plain one. Decide which of the plain"
    " colours below that name is. Judge from the maker as well as the word: the same"
    " invented name belongs to different colours at different makers."
)

COLOUR_NO_MATCH_DESCRIPTION = (
    "The title does not name a colour at all, or the colour it names is none of those"
    " above — a two-tone case, or a shade with no plain name here."
)

# Not a Choice among catalogue rows but a check on one a rule already chose: does the listing
# sell the model the entry is named? Asked about the title, never about the model our
# reading cut out of it — that would reduce the question to comparing two strings, and the
# strings are what was wrong both times this was needed: `Galaxy S26+` read as `Galaxy S26`,
# and `iPhone 16 Pro` read as `iPhone 16`.
MODEL_MATCH_INSTRUCTIONS = (
    "A shop listing (`listing_title`, made by `brand`) has been filed under the catalogue"
    " entry `entry_model`. Does the listing sell that exact model, or a different model?"
    " Judge only the model designation. Storage, memory, colour, the shop's wording, the"
    " language of the title, and whether the brand or a 5G suffix is written are not part"
    " of the model."
)

SAME_MODEL = "same"
MODEL_MATCH_CRITERIA: dict[str, str | None] = {
    # The equivalence is spelled out because without it the model read `S25+` and
    # `S25 Plus` as siblings — three of five errors on the labelled set, one at 0.96.
    SAME_MODEL: (
        "The title names the model in `entry_model` itself. `+` and `Plus` are one word"
        " written two ways, with or without a space or brackets: `S25+`, `S25 +` and"
        " `S25 (Plus)` all name `S25 Plus`."
    ),
    "sibling": (
        "The title names a different model of the same line: the entry's model with a"
        " variant word added or removed — Plus or +, Pro, Ultra, Max, FE, Lite, Mini, Neo,"
        " Edge — or a neighbouring number in the series."
    ),
    "different": "The title names an unrelated model, or is not this maker's phone at all.",
    "cant_tell": "The title does not name a model clearly enough to decide.",
}


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
class Colour:
    """One plain colour a maker's invented name might mean.

    Described by the spellings the registry already holds for it, which is the only true
    thing there is to say about a colour beyond its name — and which is what makes
    `Tumši zils` and `dark blue` visibly the same option rather than two.
    """

    canonical: str
    spellings: tuple[str, ...]

    def describe(self) -> str | None:
        if not self.spellings:
            return None
        return "also written: " + ", ".join(self.spellings)


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


def colour_choice(
    *,
    title: str | None,
    brand: str | None,
    model: str | None,
    colours: list[Colour],
) -> Question:
    """Which plain colour the maker's name in this title stands for.

    The title rather than the word, because only a shop's own ruleset knows where in a
    title that shop puts its colour, and 53 of the 57 listings this is for keep it there
    rather than in a field. Asking about the title needs no such knowledge and works the
    same for every shop.

    The answer is a plain colour and not a catalogue entry on purpose. The entry question
    was asked first and refused 30 listings of 30: what those listings need is an entry of
    their own, and the only thing stopping one being made is the axis nobody can read. A
    colour fills that axis; a chosen entry would have been the wrong answer.

    It is deliberately not turned into a registry alias afterwards. `attribute_value_aliases`
    is global and a marketing colour is not — `Canyon` is pink on a Google and orange on an
    Oppo, both proved by two shops — so the word alone cannot be the key. The maker is in
    the state here, which is why this question may be asked at all.
    """
    state = {
        "listing_title": title,
        "brand": brand,
        "model": model,
    }
    ordered = sorted(colours, key=lambda colour: colour.canonical)
    criteria: dict[str, str | None] = {colour.canonical: colour.describe() for colour in ordered}
    criteria[NO_MATCH] = COLOUR_NO_MATCH_DESCRIPTION

    return Question(
        kind=COLOUR_CHOICE,
        state=state,
        instructions=COLOUR_INSTRUCTIONS,
        criteria=criteria,
        # The option key is the canonical value itself — the answer is a word, not a row,
        # so a stored verdict stays readable with no join. The value is the position, which
        # nothing reads: what this map is for here is saying which answers are real ones.
        by_option={colour.canonical: index for index, colour in enumerate(ordered)},
        hash=_identity(COLOUR_CHOICE, state, criteria),
    )


def model_match(*, title: str, brand: str, entry_model: str) -> Question:
    """Whether a listing sells the model the entry it was filed under is named.

    Three fields and nothing else. The configuration and the colour are left out on
    purpose: the matcher compares those in code and does it right, and the model is poor
    at telling 256 from 512 — its own notes say so. What the matcher cannot do is read a
    title for the word that makes another phone of the same line.
    """
    state = {"listing_title": title, "brand": brand, "entry_model": entry_model}
    criteria = dict(MODEL_MATCH_CRITERIA)
    return Question(
        kind=MODEL_MATCH,
        state=state,
        instructions=MODEL_MATCH_INSTRUCTIONS,
        criteria=criteria,
        by_option={option: index for index, option in enumerate(criteria)},
        hash=_identity(MODEL_MATCH, state, criteria),
    )
