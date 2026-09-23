"""Two pages to look at what the pipeline produced, written as plain HTML files.

Not an endpoint. The API serves JSON to a panel that does not exist yet, and until it does
the only way to see whether a catalogue is any good is to look at it. This reads the
database, writes two self-contained files and stops — nothing is cached, nothing is served,
and running it twice is the whole refresh story.

    .venv/bin/python -m tools.preview

`index.html` is the storefront: products, their variants, and every shop's price for each.
`unmatched.html` is the other half of the truth — the listings the matcher could not place,
grouped by what is missing, because "386 did not match" is a number nobody can act on.

Both pages have a tab per category collected, and the header counts that category alone —
listings placed and not, and each shop's placed out of what it listed — so a phone week and a
tablet week cannot hide inside one average. The tab is kept in the address, `#tablets`, and
the link between the pages carries it.
"""

import asyncio
import html
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.db.session import session_factory
from app.features.brands.normalization import normalize_brand

OUT = Path(__file__).resolve().parent.parent / "var" / "preview"

# The order `MatchingService.promote_queue` checks these in, mirrored here so a listing is
# filed under the first thing that stops it rather than under all of them. Keep it in step
# with `_why_not_promotable` and `_variant_from`; the page says which it came from.
LADDER = (
    "axis_unpublished",
    "no_barcode",
    "source_not_trusted",
    "brand_unresolved",
    "category_unknown",
    "no_model",
)

WHY = {
    "no_barcode": (
        "No barcode. A variant built from a listing nobody else can agree with is a guess"
        " wearing the authority of a catalogue, so the bar to start an entry is a barcode"
        " — these still match entries another shop created."
    ),
    "no_model": (
        "No model read. A shop title is a sentence, not a model, and an entry named after"
        " one cannot be searched for and groups with nothing. The channel needs a rule."
    ),
    "brand_unresolved": (
        "The brand string resolves to no brand, or to several. Until it is settled there is"
        " nothing to file the entry under."
    ),
    "source_not_trusted": "The channel is not trusted enough to start catalogue entries.",
    "category_unknown": "The channel does not say which category it collects.",
    "promotable": (
        "Nothing is missing. The last promotion pass stopped before these — it takes a"
        " bounded number of rows — so another pass turns each of them into a catalogue"
        " entry. Not a gap: work that has not been run yet."
    ),
    "axis_unpublished": (
        "The catalogue holds this phone and the shop never said which colour it is. Several"
        " entries fit and nothing can tell them apart — not a person and not the judge,"
        " which refused thirty such questions of thirty. It waits for another shop to carry"
        " the same barcode, or for this one to start publishing the axis."
    ),
    "not_read": "No reading of this listing was stored, so there is nothing to judge it by.",
}

PRODUCTS = """
    select p.id, p.title, b.canonical_name as brand, c.name as category, c.slug as tab
    from products p
    join brands b on b.id = p.brand_id
    join categories c on c.id = p.category_id
    -- A family the rebuild pass emptied is hidden rather than deleted: the trail points
    -- at it. The storefront does not show it, and neither does this.
    where p.is_visible
"""

VARIANTS = """
    select v.id, v.product_id, v.model, v.title, v.image_url, c.slug as tab
    from variants v
    left join categories c on c.id = v.category_id
"""

OFFERS = """
    select m.variant_id, o.id, o.price, o.currency_code, o.availability, o.url,
           sh.name as shop, m.method, m.confidence
    from offer_matches m
    join offers o on o.id = m.offer_id
    join sellers s on s.id = o.seller_id
    join shops sh on sh.id = s.shop_id
    where m.superseded_at is null
    order by o.price
"""

AXES = """
    select va.variant_id, a.key, a.unit_dimension, va.value_num, va.value_text,
           av.canonical, coalesce(ca.identity_bearing, false) as identity_bearing
    from variant_attributes va
    join attributes a on a.id = va.attribute_id
    join variants v on v.id = va.variant_id
    left join attribute_values av on av.id = va.value_id
    left join category_attributes ca
           on ca.attribute_id = va.attribute_id and ca.category_id = v.category_id
"""

QUEUED = """
    select q.offer_id, q.reason, q.attempts, o.url, o.price, o.currency_code,
           sh.name as shop, src.trust, src.category_id,
           n.title, n.brand_raw, n.gtin, n.mpn, n.model, n.identity,
           -- What the matcher settled on, which is not always what the shop said and is
           -- often the only answer there is: m79's German feed states no maker at all.
           nb.canonical_name as brand_read,
           qc.slug as tab
    from match_queue q
    join offers o on o.id = q.offer_id
    join sellers s on s.id = o.seller_id
    join shops sh on sh.id = s.shop_id
    -- The newest reading from a pass that carried the catalogue, which is the same rule
    -- the matcher uses. A cheap pass observes a price and nothing else, and taking its
    -- reading as the current one made 792 listings that do carry a barcode report as
    -- carrying none.
    left join lateral (
        select r.id, r.offer_id, r.source_id
        from raw_offers r
        left join runs ru on ru.id = r.run_id
        where r.offer_id = o.id and (ru.kind is null or ru.kind <> 'quick')
        order by r.fetched_at desc, r.id desc
        limit 1
    ) raw on true
    left join sources src on src.id = raw.source_id
    left join lateral (
        select no2.*
        from normalized_offers no2
        where no2.raw_offer_id = raw.id
        order by no2.id desc
        limit 1
    ) n on true
    left join brands nb on nb.id = n.brand_id
    left join categories qc on qc.id = src.category_id
    order by sh.name, n.title
"""

ALIASES = "select alias_normalized, brand_id from brand_aliases"

# Every listing collected, with the category and the shop it was collected for and whether
# it is placed. The share these make is the one number that says whether an evening's work
# moved anything, and it is counted per category because a phone and a tablet are two
# catalogues: one number for both would let a good week on one hide a bad one on the other.
# The category is the channel's, from the listing's newest full pass — the same rule the
# queue uses above.
LISTINGS = """
    select o.id, sh.name as shop, c.slug as tab, c.name as category,
           exists (
               select 1 from offer_matches m
               where m.offer_id = o.id and m.superseded_at is null
           ) as placed,
           exists (select 1 from match_queue q where q.offer_id = o.id) as queued
    from offers o
    join sellers s on s.id = o.seller_id
    join shops sh on sh.id = s.shop_id
    left join lateral (
        select r.source_id
        from raw_offers r
        left join runs ru on ru.id = r.run_id
        where r.offer_id = o.id and (ru.kind is null or ru.kind <> 'quick')
        order by r.fetched_at desc, r.id desc
        limit 1
    ) raw on true
    left join sources src on src.id = raw.source_id
    left join categories c on c.id = src.category_id
"""

# A listing whose channel names no category still counts; it gets a tab of its own rather
# than disappearing from every total.
NO_CATEGORY = ("none", "No category")


def _plain(value: Any) -> Any:
    """JSON does not take a Decimal, and a page built from one fails at the last step."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _rows(result) -> list[dict]:
    return [{k: _plain(v) for k, v in row._mapping.items()} for row in result]


def _axis(row: dict) -> str | None:
    """One identity axis of a variant, in the shape a person reads it in.

    Capacity is stored in megabytes, because that is the only unit every listing can be
    converted into without rounding a feature phone's 4 MB away. A shopper reads `512 GB`.
    """
    if row["value_num"] is None:
        return row["canonical"] or row["value_text"]

    amount = float(row["value_num"])
    if row["unit_dimension"] == "MB":
        for size, unit in ((1024 * 1024, "TB"), (1024, "GB")):
            if amount >= size and amount % size == 0:
                return f"{amount / size:g} {unit}"
        return f"{amount:g} MB"
    if row["key"] == "screen_inch":
        return f'{amount:g}"'
    return f"{amount:g} {row['unit_dimension']}".strip()


def _refusal(row: dict, brands: dict[str, set[int]]) -> str:
    """Why this listing cannot start a catalogue entry, by the promoter's own ladder."""
    if row["title"] is None and row["gtin"] is None and row["model"] is None:
        return "not_read"
    # Ahead of the ladder, because it is a better answer than any rung of it: the catalogue
    # already holds this phone and the only thing missing is which of its colours this is.
    # `no_barcode` is true of these and tells nobody anything.
    if row["reason"] == "axis_unpublished":
        return "axis_unpublished"
    if not row["gtin"]:
        return "no_barcode"
    if row["trust"] != "high":
        return "source_not_trusted"
    try:
        found = brands.get(normalize_brand(row["brand_raw"] or ""), set())
    except ValueError:
        found = set()
    if len(found) != 1:
        return "brand_unresolved"
    if row["category_id"] is None:
        return "category_unknown"
    if not (row["model"] or "").strip():
        return "no_model"
    # Everything the promoter asks for is there, so what stopped it was the bound on how
    # many rows one pass takes. Not a gap — work that has not been run.
    return "promotable"


async def collect() -> dict:
    async with session_factory() as session:
        products = _rows(await session.execute(text(PRODUCTS)))
        variants = _rows(await session.execute(text(VARIANTS)))
        offers = _rows(await session.execute(text(OFFERS)))
        axes = _rows(await session.execute(text(AXES)))
        queued = _rows(await session.execute(text(QUEUED)))
        aliases = _rows(await session.execute(text(ALIASES)))
        listings = _rows(await session.execute(text(LISTINGS)))

    brands: dict[str, set[int]] = defaultdict(set)
    for row in aliases:
        brands[row["alias_normalized"]].add(row["brand_id"])

    by_variant: dict[int, list[dict]] = defaultdict(list)
    for row in offers:
        by_variant[row["variant_id"]].append(row)

    axes_by_variant: dict[int, list[str]] = defaultdict(list)
    for row in sorted(axes, key=lambda r: (not r["identity_bearing"], r["key"])):
        shown = _axis(row)
        if shown:
            axes_by_variant[row["variant_id"]].append(shown)

    by_product: dict[int | None, list[dict]] = defaultdict(list)
    for variant in variants:
        variant["offers"] = by_variant.get(variant["id"], [])
        variant["axes"] = axes_by_variant.get(variant["id"], [])
        by_product[variant["product_id"]].append(variant)

    catalogue = []
    for product in products:
        kids = sorted(by_product.get(product["id"], []), key=lambda v: v["title"])
        if not kids:
            # A family with nothing in it is a name and no prices: nothing to compare.
            continue
        prices = [o["price"] for v in kids for o in v["offers"] if o["price"] is not None]
        shops = {o["shop"] for v in kids for o in v["offers"]}
        product |= {
            "variants": kids,
            "offer_count": sum(len(v["offers"]) for v in kids),
            "shops": sorted(shops),
            "low": min(prices) if prices else None,
            "high": max(prices) if prices else None,
        }
        catalogue.append(product)
    catalogue.sort(key=lambda p: (-len(p["shops"]), -p["offer_count"], p["title"]))

    for row in queued:
        row["missing"] = _refusal(row, brands)
    queued.sort(
        key=lambda r: (
            LADDER.index(r["missing"]) if r["missing"] in LADDER else 99,
            r["shop"],
            r["title"] or "",
        )
    )

    # A variant with no product is one the catalogue could not give a family to. Worth
    # seeing rather than hiding, and it is the same page's job.
    orphans = sorted(by_product.get(None, []), key=lambda v: v["title"])

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "tabs": _tabs(listings, catalogue, variants, queued),
        "products": catalogue,
        "orphans": orphans,
        "queued": queued,
        "missing_counts": dict(Counter(r["missing"] for r in queued).most_common()),
        "totals": {
            "products": len(products),
            "variants": len(variants),
            "matched": len(offers),
            "queued": len(queued),
            # Every shop that has been collected from, not every shop that got a listing
            # placed. A channel that contributes nothing is the interesting case, and
            # counting only the ones that worked would hide it.
            "shops": len({row["shop"] for row in listings}),
            "listings": len(listings),
            "share": (100 * len(offers) / len(listings)) if listings else 0.0,
        },
    }


def _tabs(
    listings: list[dict], catalogue: list[dict], variants: list[dict], queued: list[dict]
) -> list[dict]:
    """One tab per category collected, with the exact counts its header shows.

    Counted from the listings rather than from the catalogue, so a shop that placed nothing
    still appears, with its zero — that is the case worth seeing.
    """
    for row in listings + queued:
        row["tab"] = row.get("tab") or NO_CATEGORY[0]
    names = {row["tab"]: row.get("category") or NO_CATEGORY[1] for row in listings}
    tabs = []
    for slug in sorted(names, key=lambda t: (t == NO_CATEGORY[0], t)):
        mine = [row for row in listings if row["tab"] == slug]
        by_shop: dict[str, list[dict]] = defaultdict(list)
        for row in mine:
            by_shop[row["shop"]].append(row)
        tabs.append(
            {
                "slug": slug,
                "name": names[slug],
                "listings": len(mine),
                "placed": sum(row["placed"] for row in mine),
                "queued": sum(row["queued"] for row in mine),
                # A queue row left behind by a listing that was placed since: counted apart,
                # so placed and not placed add up to the listings exactly.
                "stale": sum(row["queued"] and row["placed"] for row in mine),
                "products": sum(1 for p in catalogue if p["tab"] == slug),
                "variants": sum(1 for v in variants if v["tab"] == slug),
                "shops": [
                    {
                        "shop": shop,
                        "listings": len(rows),
                        "placed": sum(row["placed"] for row in rows),
                    }
                    for shop, rows in sorted(by_shop.items(), key=lambda kv: -len(kv[1]))
                ],
            }
        )
    return tabs


# --- the pages ---

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfaf8; --fg: #1a1a1a; --muted: #6b6b6b; --line: #e3e0da;
  --card: #ffffff; --accent: #1d4ed8; --warn: #b45309; --ok: #15803d;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16171a; --fg: #e8e6e3; --muted: #9a9894; --line: #2c2e33;
    --card: #1e2024; --accent: #7aa2f7; --warn: #d79a45; --ok: #6cbf76;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
header { border-bottom: 1px solid var(--line); padding: 20px 24px; }
h1 { font-size: 19px; margin: 0 0 6px; font-weight: 620; }
.sub { color: var(--muted); font-size: 13px; }
.sub a { color: var(--accent); }
main { padding: 20px 24px 60px; max-width: 1100px; }
.bar { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }
input, select {
  font: inherit; padding: 7px 10px; border: 1px solid var(--line);
  border-radius: 7px; background: var(--card); color: var(--fg);
}
input { flex: 1 1 260px; }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px; margin-bottom: 10px;
}
.card h2 { font-size: 15px; margin: 0; font-weight: 600; }
.meta { color: var(--muted); font-size: 12.5px; margin-top: 3px; }
.price { float: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.variant { border-top: 1px solid var(--line); margin-top: 12px; padding-top: 10px; }
.axes { color: var(--muted); font-size: 12.5px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px 6px 0; vertical-align: top; }
th { color: var(--muted); font-weight: 500; border-bottom: 1px solid var(--line); }
td { border-bottom: 1px solid var(--line); }
tr:last-child td { border-bottom: 0; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.tag {
  display: inline-block; font-size: 11.5px; padding: 1px 7px; border-radius: 20px;
  border: 1px solid var(--line); color: var(--muted); margin-right: 4px;
}
.none { color: var(--warn); }
/* A maker the shop did not state and the matcher worked out: a conclusion, not a fact the
   shop published, and marked so nobody reads the two as the same kind of thing. */
.read { color: var(--dim); font-style: italic; }
.yes { color: var(--ok); }
.why { color: var(--muted); max-width: 70ch; margin: 2px 0 12px; }
section { margin-bottom: 30px; }
section h2 { font-size: 15px; margin: 0 0 2px; }
.empty { color: var(--muted); padding: 30px 0; }
.tabs { display: flex; gap: 4px; margin: 4px 0 10px; }
.tabs a {
  padding: 5px 12px; border: 1px solid var(--line); border-radius: 20px;
  color: var(--muted); font-size: 13px;
}
.tabs a.on { color: var(--fg); border-color: var(--accent); font-weight: 600; }
.tabs a:hover { text-decoration: none; }
.tabs .n { color: var(--muted); font-weight: 400; font-variant-numeric: tabular-nums; }
.shops { margin-top: 8px; }
.shops .tag { font-variant-numeric: tabular-nums; margin-bottom: 4px; }
.shops b { color: var(--fg); font-weight: 600; }
"""

SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__STYLE__</style></head>
<body>
<header>
  <h1>__TITLE__</h1>
  <nav class="tabs" id="tabs"></nav>
  <div class="sub" id="sub">__SUB__</div>
  <div class="shops" id="shops"></div>
</header>
<main id="main"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// Three states, not two. Most of one shop's catalogue is `preorder` — the thing can be
// bought today and arrives in a fortnight — and drawing it the same grey as `out_of_stock`
// read as a shop with nothing on its shelves.
const STOCK = {
  in_stock: ["yes", "in stock"],
  preorder: ["warn", "to order"],
  out_of_stock: ["none", "out of stock"],
};
const stock = s => {
  const [cls, label] = STOCK[s] || ["axes", s || "unknown"];
  return `<span class="${esc(cls)}">${esc(label)}</span>`;
};
const money = (n, c) => n == null ? "—" : n.toFixed(2) + " " + (c === "EUR" ? "\\u20ac" : c || "");
// A brand dropdown built from the rows themselves, counted, so an option that would show
// nothing is never offered. Keyed case-insensitively: shops write `SAMSUNG` and `Samsung`
// for one maker, and two options for it would split one list in two.
// Rows with no maker at all get an option of their own; an empty value would be "all".
const brandKey = name => (name || "—").toLowerCase();
function brandOptions(select, names) {
  const counts = new Map();
  for (const name of names) {
    const key = brandKey(name);
    const seen = counts.get(key);
    counts.set(key, seen ? [seen[0], seen[1] + 1] : [name || "—", 1]);
  }
  select.innerHTML = '<option value="">All brands</option>' + [...counts]
    .sort((a, b) => a[1][0].localeCompare(b[1][0]))
    .map(([key, [label, n]]) => `<option value="${esc(key)}">${esc(label)} (${n})</option>`)
    .join("");
}
// The category shown, kept in the address so the link to the other page keeps it too.
const TABS = DATA.tabs || [];
let TAB = decodeURIComponent(location.hash.slice(1)) || (TABS[0] && TABS[0].slug) || "";
if (!TABS.some(t => t.slug === TAB) && TABS[0]) TAB = TABS[0].slug;
const inTab = row => !TABS.length || row.tab === TAB;
const pct = (n, d) => d ? (100 * n / d).toFixed(1) + "%" : "—";
function header() {
  document.getElementById("tabs").innerHTML = TABS.map(t =>
    `<a href="#${esc(t.slug)}" class="${t.slug === TAB ? "on" : ""}" data-tab="${esc(t.slug)}">` +
    `${esc(t.name)} <span class="n">${t.listings}</span></a>`).join("");
  const t = TABS.find(t => t.slug === TAB);
  if (!t) return;
  document.getElementById("sub").innerHTML = SUB(t);
  document.getElementById("shops").innerHTML = t.shops.map(s =>
    `<span class="tag">${esc(s.shop)} <b>${s.placed}</b> / ${s.listings}` +
    ` · ${pct(s.placed, s.listings)}</span>`).join("");
  for (const a of document.querySelectorAll("a[data-other]"))
    a.href = a.dataset.other + "#" + encodeURIComponent(TAB);
}
document.getElementById("tabs").addEventListener("click", e => {
  const a = e.target.closest("a[data-tab]");
  if (!a) return;
  e.preventDefault();
  TAB = a.dataset.tab;
  history.replaceState(null, "", "#" + encodeURIComponent(TAB));
  header();
  draw();
});
__SCRIPT__
header();
draw();
</script>
</body></html>
"""


def page(path: Path, title: str, sub: str, data: dict, script: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    body = (
        SHELL.replace("__STYLE__", STYLE)
        .replace("__TITLE__", html.escape(title))
        .replace("__SUB__", sub)
        # `</script>` inside the payload would close the tag that carries it.
        .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
        .replace("__SCRIPT__", script)
    )
    path.write_text(body, encoding="utf-8")


STOREFRONT_JS = """
const main = document.getElementById("main");
main.innerHTML = `
  <div class="bar">
    <input id="q" placeholder="Search a product, a brand, a model…" autofocus>
    <select id="brand"></select>
    <select id="sort">
      <option value="shops">Most shops first</option>
      <option value="offers">Most listings first</option>
      <option value="low">Cheapest first</option>
      <option value="title">By name</option>
    </select>
  </div>
  <div id="list"></div>`;

function card(p) {
  const range = p.low == null ? "" :
    `<span class="price">${p.low === p.high ? money(p.low, "EUR")
      : money(p.low, "EUR") + " – " + money(p.high, "EUR")}</span>`;
  const variants = p.variants.map(v => `
    <div class="variant">
      <div>${esc(v.axes.join(" · ") || v.model)}</div>
      <table><tbody>${v.offers.map(o => `
        <tr>
          <td>${esc(o.shop)}</td>
          <td class="num">${money(o.price, o.currency_code)}</td>
          <td>${stock(o.availability)}</td>
          <td><span class="tag">${esc(o.method)}</span></td>
          <td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">open</a>` : ""}</td>
        </tr>`).join("")}</tbody></table>
    </div>`).join("");
  return `<div class="card">${range}
    <h2>${esc(p.title)}</h2>
    <div class="meta">${esc(p.brand)} · ${esc(p.category)} ·
      ${p.variants.length} variant${p.variants.length === 1 ? "" : "s"} ·
      ${p.offer_count} listing${p.offer_count === 1 ? "" : "s"} ·
      ${p.shops.map(s => `<span class="tag">${esc(s)}</span>`).join("")}</div>
    ${variants}</div>`;
}

// What the shop said, or what the matcher worked out when it said nothing. The second is
// marked, because a maker read off a title is a conclusion and a field is a statement.
function brand(r) {
  if (r.brand_raw) return esc(r.brand_raw);
  if (r.brand_read) return `<span class="read">${esc(r.brand_read)}</span>`;
  return '<span class="none">—</span>';
}

function draw() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const by = document.getElementById("sort").value;
  const maker = document.getElementById("brand").value;
  let rows = DATA.products.filter(p => inTab(p) && (!maker || brandKey(p.brand) === maker) && (!q ||
    (p.title + " " + p.brand + " " + p.category).toLowerCase().includes(q)));
  const order = {
    shops: (a, b) => b.shops.length - a.shops.length || b.offer_count - a.offer_count,
    offers: (a, b) => b.offer_count - a.offer_count,
    low: (a, b) => (a.low ?? 1e9) - (b.low ?? 1e9),
    title: (a, b) => a.title.localeCompare(b.title),
  }[by];
  rows = rows.slice().sort(order);
  document.getElementById("list").innerHTML =
    rows.length ? rows.map(card).join("")
                : '<div class="empty">Nothing matches that.</div>';
}
brandOptions(document.getElementById("brand"), DATA.products.map(p => p.brand));
document.getElementById("q").addEventListener("input", draw);
document.getElementById("brand").addEventListener("change", draw);
document.getElementById("sort").addEventListener("change", draw);
const SUB = t =>
  `<b>${t.placed} of ${t.listings} listings placed</b> · ${pct(t.placed, t.listings)} ·` +
  ` ${t.listings - t.placed} not placed · ${t.shops.length} shops · ${t.products} products ·` +
  ` ${t.variants} variants · ${esc(DATA.generated_at)} ·` +
  ` <a data-other="unmatched.html" href="unmatched.html">what did not match</a>`;
"""

UNMATCHED_JS = """
const main = document.getElementById("main");
main.innerHTML = `
  <div class="bar">
    <input id="q" placeholder="Search a title, a brand, a shop…" autofocus>
    <select id="brand"></select>
  </div>
  <div id="list"></div>`;

function group(key, rows) {
  return `<section>
    <h2>${esc(key)} <span class="axes">· ${rows.length}</span></h2>
    <p class="why">${esc(DATA.why[key] || "")}</p>
    <table>
      <thead><tr><th>Shop</th><th>Title</th><th>Brand</th><th>Barcode</th>
        <th>Part no.</th><th>Model</th><th class="num">Price</th><th></th></tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td>${esc(r.shop)}</td>
        <td>${esc(r.title || "—")}</td>
        <td>${brand(r)}</td>
        <td class="num">${r.gtin ? esc(r.gtin) : '<span class="none">—</span>'}</td>
        <td>${r.mpn ? esc(r.mpn) : '<span class="none">—</span>'}</td>
        <td>${r.model ? esc(r.model) : '<span class="none">—</span>'}</td>
        <td class="num">${money(r.price, r.currency_code)}</td>
        <td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">open</a>` : ""}</td>
      </tr>`).join("")}</tbody></table>
  </section>`;
}

// What the shop said, or what the matcher worked out when it said nothing. The second is
// marked, because a maker read off a title is a conclusion and a field is a statement.
function brand(r) {
  if (r.brand_raw) return esc(r.brand_raw);
  if (r.brand_read) return `<span class="read">${esc(r.brand_read)}</span>`;
  return '<span class="none">—</span>';
}

function draw() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const maker = document.getElementById("brand").value;
  const rows = DATA.queued.filter(r => inTab(r) &&
    (!maker || brandKey(makerOf(r)) === maker) && (!q ||
    ((r.title || "") + " " + (r.brand_raw || "") + " " + (r.brand_read || "") + " " + r.shop)
      .toLowerCase().includes(q)));
  const buckets = new Map();
  for (const r of rows) (buckets.get(r.missing) ?? buckets.set(r.missing, []).get(r.missing))
    .push(r);
  document.getElementById("list").innerHTML =
    rows.length ? [...buckets].map(([k, v]) => group(k, v)).join("")
                : '<div class="empty">Nothing matches that.</div>';
}
// The shop's word for the maker when it gave one, the matcher's when it did not — the
// same order the Brand column shows them in.
function makerOf(r) { return r.brand_raw || r.brand_read || ""; }

brandOptions(document.getElementById("brand"), DATA.queued.map(makerOf));
document.getElementById("q").addEventListener("input", draw);
document.getElementById("brand").addEventListener("change", draw);
const SUB = t =>
  `<b>${t.listings - t.placed} of ${t.listings} listings not placed</b> ·` +
  ` ${pct(t.listings - t.placed, t.listings)} of what ${t.shops.length} shops published ·` +
  (t.stale ? ` ${t.queued} queue rows, ${t.stale} of them for a listing placed since ·` : "") +
  ` ${esc(DATA.generated_at)} ·` +
  ` <a data-other="index.html" href="index.html">back to the storefront</a>`;
"""


async def main() -> None:
    data = await collect()
    totals = data["totals"]
    counts = ", ".join(f"{name} {count}" for name, count in data["missing_counts"].items())

    page(
        OUT / "index.html",
        "Storefront",
        f"<b>{totals['share']:.1f}% placed</b> — {totals['matched']} of"
        f" {totals['listings']} listings from {totals['shops']} shops ·"
        f" {totals['products']} products · {totals['variants']} variants ·"
        f" {data['generated_at']} · <a href='unmatched.html'>what did not match</a>",
        {"products": data["products"], "tabs": data["tabs"], "generated_at": data["generated_at"]},
        STOREFRONT_JS,
    )
    page(
        OUT / "unmatched.html",
        "Not matched",
        f"<b>{totals['queued']} of {totals['listings']} listings</b> —"
        f" {100 - totals['share']:.1f}% of what {totals['shops']} shops published ·"
        f" {counts} · {data['generated_at']} ·"
        f" <a href='index.html'>back to the storefront</a>",
        {
            "queued": data["queued"],
            "why": WHY,
            "tabs": data["tabs"],
            "generated_at": data["generated_at"],
        },
        UNMATCHED_JS,
    )
    print(f"{OUT / 'index.html'}\n{OUT / 'unmatched.html'}")
    print(
        f"placed {totals['matched']} of {totals['listings']} ({totals['share']:.2f}%)"
        f" from {totals['shops']} shops, queued {totals['queued']} ({counts})"
    )
    for tab in data["tabs"]:
        shops = ", ".join(f"{s['shop']} {s['placed']}/{s['listings']}" for s in tab["shops"])
        print(f"  {tab['name']}: {tab['placed']} of {tab['listings']} placed · {shops}")
    if data["orphans"]:
        print(f"variants with no product: {len(data['orphans'])}")


if __name__ == "__main__":
    asyncio.run(main())
