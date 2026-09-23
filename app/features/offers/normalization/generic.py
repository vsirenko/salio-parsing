"""Reading a raw payload into the fields the pipeline works on.

A pure function of the payload and the ruleset version, and that purity is what the whole
design rests on: improving a rule means re-running it over what is already stored and
comparing the old reading with the new one before accepting it. Nothing here touches the
database, and nothing here resolves a string to a row — a brand string becomes a brand
during matching, not here.
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.features.offers.normalization import barcodes

# Bumped whenever the reading below changes. Stored on every row it produces, so two
# readings of the same bytes can be told apart and compared.
RULESET_VERSION = "generic-2"

# A generic reading of a flat object. Real sources get their own rulesets; this one exists
# so that a sample can be loaded by hand and measured before any of them are written.
TITLE_KEYS = ("title", "name", "product_name")
BRAND_KEYS = ("brand", "manufacturer", "vendor", "brand_name")
CATEGORY_KEYS = ("category", "category_path", "categories", "breadcrumb")
GTIN_KEYS = ("gtin", "ean", "ean13", "barcode", "upc")
MPN_KEYS = ("mpn", "part_number", "partnumber", "sku", "vendor_code", "article")
MODEL_KEYS = ("model", "model_name")
PRICE_KEYS = ("price", "current_price", "sale_price", "amount")
CURRENCY_KEYS = ("currency", "currency_code", "currencyid")
CONDITION_KEYS = ("condition", "state")
AVAILABILITY_KEYS = ("availability", "available", "in_stock", "stock")

CONDITIONS = {
    "new": "new",
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "renewed": "refurbished",
    "used": "used",
    "second-hand": "used",
    "pre-owned": "used",
}
AVAILABILITY = {
    "in_stock": "in_stock",
    "instock": "in_stock",
    "available": "in_stock",
    "true": "in_stock",
    "yes": "in_stock",
    "out_of_stock": "out_of_stock",
    "outofstock": "out_of_stock",
    "unavailable": "out_of_stock",
    "false": "out_of_stock",
    "no": "out_of_stock",
    "preorder": "preorder",
    "pre-order": "preorder",
    "backorder": "preorder",
}

_DIGITS = re.compile(r"\d+")
_ISO_CODE = re.compile(r"\b([A-Z]{3})\b")

# Payload keys are matched case-insensitively by lowering the payload, so a key written
# with a capital in one of the tuples above would never match anything. That is exactly
# what happened to `currencyId`, and the field was silently never read.
assert all(
    key == key.lower()
    for group in (
        TITLE_KEYS,
        BRAND_KEYS,
        CATEGORY_KEYS,
        GTIN_KEYS,
        MPN_KEYS,
        MODEL_KEYS,
        PRICE_KEYS,
        CURRENCY_KEYS,
        CONDITION_KEYS,
        AVAILABILITY_KEYS,
    )
    for key in group
), "payload keys have to be written in lower case"


def content_hash(payload: dict[str, Any]) -> str:
    """A stable fingerprint of what the shop served.

    Sorted keys, so a source that reorders its JSON between fetches does not look like a
    changed page and write a row that says nothing new.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def read(payload: dict[str, Any]) -> dict[str, Any]:
    """One reading of one payload. Everything it cannot make sense of stays None."""
    return {
        "ruleset_version": RULESET_VERSION,
        "title": _text(payload, TITLE_KEYS, limit=1000),
        "brand_raw": _text(payload, BRAND_KEYS, limit=200),
        "category_raw": _category(payload),
        "gtin": _gtin(payload),
        "mpn": _text(payload, MPN_KEYS, limit=100),
        "model": _text(payload, MODEL_KEYS, limit=200),
        "attributes": _attributes(payload),
        "price": _price(payload),
        "currency_code": _currency(payload),
        "condition": _mapped(payload, CONDITION_KEYS, CONDITIONS, "new"),
        "availability": _mapped(payload, AVAILABILITY_KEYS, AVAILABILITY, "unknown"),
    }


def _first(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for key in keys:
        value = lowered.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text(payload: dict[str, Any], keys: tuple[str, ...], *, limit: int) -> str | None:
    value = _first(payload, keys)
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None


def _category(payload: dict[str, Any]) -> str | None:
    """A path, however the source expressed it.

    Joined with a separator rather than kept as a list, because what it is used for is a
    lookup in `source_category_map`, and a mapping table needs one string to key on.
    """
    value = _first(payload, CATEGORY_KEYS)
    if value is None:
        return None
    parts = value if isinstance(value, list) else [value]
    joined = " / ".join(" ".join(str(p).split()) for p in parts if str(p).strip())
    return joined[:500] or None


def _gtin(payload: dict[str, Any]) -> str | None:
    """Digits only, and only if there are the right number of them.

    A barcode field holding "n/a" or a phone number is common enough that accepting
    whatever is in it would put nonsense on the strongest signal the matcher has.
    """
    value = _first(payload, GTIN_KEYS)
    if value is None:
        return None
    digits = "".join(_DIGITS.findall(str(value)))
    return barcodes.canonical(digits) if 8 <= len(digits) <= 14 else None


def _price(payload: dict[str, Any]) -> Decimal | None:
    value = _first(payload, PRICE_KEYS)
    if value is None:
        return None
    # A comma is a decimal separator across the Baltics, and a space is a thousands
    # separator. Both arrive in feeds written for humans.
    text = str(value).replace(" ", "").replace(" ", "").replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        price = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return price if price >= 0 else None


def _currency(payload: dict[str, Any]) -> str | None:
    value = _first(payload, CURRENCY_KEYS)
    if value is not None:
        code = str(value).strip().upper()
        if len(code) == 3 and code.isalpha():
            return code

    # Plenty of sources write the currency into the price itself — "1179.00 EUR" — and
    # never send a field for it.
    price_value = _first(payload, PRICE_KEYS)
    if price_value is not None:
        found = _ISO_CODE.search(str(price_value).upper())
        if found:
            return found.group(1)
    return None


def _mapped(
    payload: dict[str, Any], keys: tuple[str, ...], table: dict[str, str], fallback: str
) -> str:
    value = _first(payload, keys)
    if value is None:
        return fallback
    return table.get(str(value).strip().lower().replace(" ", "_"), fallback)


def _attributes(payload: dict[str, Any]) -> dict[str, Any]:
    """Whatever the source called its attributes, untouched.

    Not resolved to the canonical registry here: a key nobody has mapped stays as it
    arrived and takes no part in identity, so the cost of not having mapped it is the slow
    path rather than lost data.
    """
    value = payload.get("attributes") or payload.get("params") or payload.get("specs")
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    if isinstance(value, list):
        # A list of {name, value} pairs is the other shape feeds use.
        pairs = {}
        for item in value:
            if isinstance(item, dict) and "name" in item:
                pairs[str(item["name"])] = item.get("value")
        return pairs
    return {}
