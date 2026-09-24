# pipeline

The path from a channel to the catalogue, counted — what a canvas in the admin panel draws.

## Endpoints

| | |
|---|---|
| `GET /api/admin/pipeline` | every step from a channel to the catalogue, with what reached it; `?category=` or `?source=` narrows it |
| `GET /api/admin/pipeline/runs/{run_id}` | one run through the same steps, filling in while it runs |
| `GET /api/admin/pipeline/history` | the key numbers as they stood, day by day — `?days=`, `?scope=` all or a category |

## How it works

**Seven nodes, in the order a listing passes them**: the channels, what their last full pass
collected, what the shops still list, what was read, then placed or queued, and the catalogue
entries the placed ones are on. Each node carries its parts — the runs by their last status,
the readings with a model, a barcode and every axis their category requires, the placements
by method, the queue by reason — and each edge the count that passed, so what stopped at a
node is the difference.

**The read node says which axis is missing, by name**: `missing_axes: {color: 300,
storage_mb: 40}` beside `parts`, and on every channel's row. One count of "not every axis"
did not say whether the colour or the capacity was in the way. Each node leads to its
listings: `GET /api/admin/offers` takes `source_id`, `has_gtin`, `has_model`, `has_all_axes`
and `missing_axis`, counted by the same test as here. A channel's row carries `shop_id`,
`category_id`, `category_slug` and `last_run_id` — its last full pass — to link to.

**Yesterday is kept, because it cannot be recomputed.** Everything else here is counted from
the tables as they are now: a listing read, placed or taken down since has moved. So the
scheduler keeps the key numbers once a day, for everything and for each category, in
`pipeline_snapshots` — the only write this feature has — and `GET /history` reads them back.
A day the scheduler was not running is missing, not zero. The whole count answers in about
0.2 s on 18 660 listings, so nothing else is cached.

**A listing is counted by its newest full observation**, the rule the matcher reads by: a
cheap pass carries a price and nothing else. **Listed means seen by its channel's newest
full pass that ended ok.** A card the shop took down, or one a channel's filter now leaves
out, keeps its history and stops counting — bigbox's mouse mats were 41 of the tablets "not
placed" after its filter had already left them out.

**Read-only, and it imports no other feature.** It reads `runs`, `raw_offers`,
`normalized_offers`, `offer_matches`, `match_queue` and the catalogue directly — every model
lives in `app/db/models.py` — so it can count what the others did without calling them.

**One run is its own flow.** Asked for, found on the shop, read by the worker, handed over,
read by us, then placed or queued, and the catalogue entries it made. The first four come
from what the worker reported onto `runs.progress` while it runs and from the run's own
counts once it has finished; the rest are counted from the listings whose stored bytes the
run delivered, changed or not, between its start and its finish — an unchanged page only
moves `last_seen_at`, and it was seen all the same. What settling did (`renamed`, `matched`,
`promoted`, `matched_after`) rides on the last node. A placement is "by this run" when it
was decided after the run began, and an entry is new when it was created after that. Only a
full pass and a reparse are settled: a quick pass that ended ok reads `phase: done`, and a
settling that failed reads `unsettled` with its error, so nothing watching waits forever.

**The path of one listing is not here.** It is `GET /api/admin/offers/{id}/trace`, in
`offers`: the reading recomputed rule by rule, the match and the entry. This is the same
path for everything at once.
