"""Generating a title, a slug and an identity key.

All three are derived, and the rule for each is the same: recompute from the inputs, never
edit in place. What a human wants to pin lives in an `*_override` column beside the derived
value, so a correction survives the next regeneration instead of being flattened by it.
"""

import hashlib
import re
import unicodedata
from decimal import Decimal

# Long enough to stay readable in a URL, short enough that the id on the end is still
# visible. The tail is what makes collisions impossible, so the head does not have to try.
SLUG_HEAD = 80

_NOT_SLUG = re.compile(r"[^a-z0-9]+")
_NOT_MODEL = re.compile(r"[^0-9a-zЀ-ӿ]+")


def normalize_model(value: str) -> str:
    """The matching form of a model designation.

    Case and separators are noise a source adds at will: `WW90T554DAX`, `ww90t554-dax` and
    `WW 90 T554 DAX` are one model written three ways. Everything that is not a letter or a
    digit goes, which also means the form is language-neutral — the point of matching on a
    model rather than on a title.

    Except `+`, which is not a separator: `Galaxy S26+` is not `Galaxy S26`. Dropping it gave
    the two one form and so one identity key, and listings of the plus phone were already
    being filed under the plain one when it was found. It is spelled out rather than kept,
    because makers and shops write `Galaxy S25+` and `Galaxy S25 Plus` for the same phone,
    and the catalogue had both as separate entries. A maker's name is the same word in
    every language, so this is structure, not vocabulary.
    """
    text = unicodedata.normalize("NFKC", value).casefold().replace("+", "plus")
    return _NOT_MODEL.sub("", text)


def slugify(text: str, *, entity_id: int) -> str:
    """A slug for something a machine created.

    Derived with the id appended, because nobody hand-names a million rows. The tail also
    means a retitle does not break the link: the old URL keeps resolving to the same row.
    """
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    head = _NOT_SLUG.sub("-", ascii_text.lower()).strip("-")[:SLUG_HEAD].strip("-")
    return f"{head}-{entity_id}" if head else str(entity_id)


# Bytes are stored in megabytes and written in the largest unit that is at least one of
# them, the binary way the reading converted them: `128GB` was read as 131072.
_BYTE_UNITS = (("TB", 1024 * 1024), ("GB", 1024), ("MB", 1))


def display_number(value: Decimal, unit: str | None) -> str:
    """A stored number as a person reads it, in the unit the attribute declares.

    The stored form is right for keys and filters and wrong for a title: `OnePlus 10T
    131072 black` was the name of 2235 of 2400 entries, because this printed the megabytes
    with no unit. The key is built from the stored value and is not touched by this.
    """
    if unit == "MB":
        for name, size in _BYTE_UNITS:
            if value >= size:
                return f"{_plain(Decimal(value) / size)} {name}"
    if unit == "inch":
        return f'{_plain(value)}"'
    return f"{_plain(value)} {unit}" if unit else _plain(value)


def _plain(value: Decimal) -> str:
    """At most two decimals, and none that say nothing: 126, 1.5, 6.78."""
    return format(value.quantize(Decimal("0.01")).normalize(), "f")


def compose_title(brand: str, model: str, attribute_values: list[str]) -> str:
    """Brand, model, then the identity-bearing values in the category's own order.

    `category_attribute.position` is what orders them — the same field that orders the
    filters, because the order that reads well in a list reads well in a name.
    """
    parts = [brand.strip(), model.strip(), *(v.strip() for v in attribute_values)]
    return " ".join(part for part in parts if part)


def compute_identity_key(
    *,
    brand_id: int,
    category_id: int,
    model_normalized: str,
    kind: str,
    unit_count: int,
    identity_values: dict[str, str | Decimal | bool | None],
    expected_keys: set[str],
) -> str | None:
    """The hash two offers of the same thing both arrive at, or None.

    None whenever a single identity-bearing attribute of the category is missing. That rule
    is the whole safety of the mechanism: a key built from a partial set would be equal for
    two different things that happen to share the attributes that *were* extracted, and it
    would merge them confidently. Missing an axis means the variant takes the long way
    round through the matcher, which is slow rather than wrong.

    Brand and category are in the hash because without them a phone and a tablet with the
    same colour and storage would collide.
    """
    if expected_keys - {k for k, v in identity_values.items() if v is not None}:
        return None

    axes = ";".join(f"{key}={_render(identity_values[key])}" for key in sorted(expected_keys))
    material = f"{brand_id}|{category_id}|{model_normalized}|{kind}|{unit_count}|{axes}"
    return hashlib.sha256(material.encode()).hexdigest()


def _render(value: str | Decimal | bool) -> str:
    """One text form per value, so the same number never hashes two ways.

    A Decimal is normalized first: 256 and 256.00 are one capacity, and str() would
    disagree with itself about that.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)
