"""Reading what bigbox.lv's search index hands over.

Written against 984 real phones measured on 22.09.2026. Generic finds the title, the brand,
the price and the stock flag in this shape; what it cannot guess is that the barcode is
under a name it does not know, and that a field holding the maker's own code is called
nothing at all.
"""

from typing import Any

from app.features.offers.normalization import barcodes
from app.features.offers.normalization.rules import SOURCE, Rule, Ruleset, register

SLUG = "bigbox-phones"
VERSION = "bigbox-1"

# The record calls its manufacturer code by its raw column name: the index only labels the
# attributes it lets shoppers filter on, and this is not one of them.
MPN_KEY = "attribute_string_23"
# Labelled by the index itself as `Tālruņa modelis`.
LINE_KEY = "Tālruņa modelis"


def _barcode(payload: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    return {"gtin": barcodes.pick(payload.get("ean_code"))}


def _part_number(payload: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    value = (payload.get("attributes") or {}).get(MPN_KEY)
    return {"mpn": str(value).strip()[:100]} if value else {}


def _line(payload: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    line = (payload.get("attributes") or {}).get(LINE_KEY)
    return {"_line": str(line).strip()} if line else {}


RULESET = register(
    SOURCE,
    SLUG,
    Ruleset(
        version=VERSION,
        rules=(
            Rule(
                id="bigbox-barcode",
                layer=SOURCE,
                why=(
                    "The barcode is a named field, `ean_code`, on 93.2% of these products —"
                    " but named something generic does not look for, so without this rule"
                    " the strongest signal the matcher has is invisible on all of them. It"
                    " also appears a second time as `attribute_string_15`, identical on"
                    " every product that has both; reading the named one means the"
                    " duplicate can be ignored rather than reconciled."
                ),
                body=_barcode,
            ),
            Rule(
                id="bigbox-part-number",
                layer=SOURCE,
                why=(
                    "`attribute_string_23` holds the maker's own code on 91.9% of these"
                    " products, and the index never labels it — only filterable attributes"
                    " get a name in its facets. Of the values that are there, 85% look like"
                    " a code (`WP56-RD/OL`, `G3-OE/OL`) and 12.6% contain a space, which is"
                    " a shop having typed a name into a code field. Unlike ksenukai's"
                    " article numbers these are the manufacturer's, so they can agree with"
                    " another shop — the junk simply fails to match rather than matching"
                    " wrongly."
                ),
                body=_part_number,
            ),
            Rule(
                id="bigbox-line",
                layer=SOURCE,
                why=(
                    "`Tālruņa modelis` is on 40.5% of these and is not the model: it holds"
                    " `Galaxy S26` for the Ultra, the Plus and the plain one alike, and"
                    " `iPhone 17e` for every capacity. Matching on it would make one"
                    " ambiguous pile out of a whole family. It is a product **line**, which"
                    " is what the layer below the brand selects on, so that is where it goes."
                ),
                body=_line,
            ),
        ),
    ),
)
