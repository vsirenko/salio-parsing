# prices

Two records of a listing over time: what it cost, and whether it could be bought. The only
tables in the system that are pure record.

## Endpoints

| | |
|---|---|
| `GET /api/admin/price-history` | newest first, by cursor — `offer_id`, `variant_id`, `condition`, `since`, `until` |
| `GET /api/admin/availability-history` | the same filters, its own series |

Read-only. Rows are written by ingestion; nothing edits or deletes one. A price that was
charged was charged, and a history that can be edited stops being evidence of anything.

## How it works

**A row is about the offer, not the variant.** "SKU-1 at RD cost 1179 on the first of
January" was true then and stays true whatever that listing later turns out to be.

That is the whole design decision, and it exists because of what the alternative does:

```
1 Jan    record "iPhone 15 Pro 256GB cost 1179"
         ...three months of rows saying the same variant...
1 Apr    the match turns out to be wrong — it was the 512GB
```

With the variant written into the row, three months of history keep asserting a variant
those prices never belonged to, and correcting the match means finding and rewriting every
one of them. An error in an *opinion* has permanently damaged a *fact*.

Keyed by the offer, nothing needs rewriting: the rows stayed true, and the chart — "the
prices of every listing currently matched to this variant" — changes the moment the match
does.

It is the same rule that makes `offer_match` a row rather than a column on the offer: a
fact must not carry an opinion inside it.

`variant_id` is carried alongside as a hint for queries and is rewritten when a match
changes. That touches one listing's rows rather than the table, and the row itself never
moves.

**Two series, not one table with two columns.** Availability arrives through channels that
carry no price — a stock ping, a webhook, a faster poll of the same page. Recording one of
those as a price event would mean repeating the last known price and calling it an
observation, which asserts something nobody quoted at that moment.

They also move at different rates: stock can flip several times a day where a price changes
in a week, so keeping them together would multiply the larger table by the churn of the
smaller fact.

**Changes, never snapshots.** A million offers photographed daily are some 365 million rows
a year, almost all repeating the row before. A price row is written when the price moves, a
stock row when the stock state does, and neither writes for the other.

**`source_id` says which channel reported it.** Two channels of one shop can disagree about
both a price and a stock state, and a series that cannot say which one said what is a series
nobody can explain.

**Partitioned by month from the first migration**, with a default partition so an insert
never fails for a range nobody created. Retrofitting partitioning onto a table this size is
its own project, which is why it is not left for later.

## Decisions worth knowing before changing it

- **The write rule lives here, not in ingestion.** When a change counts is the same
  knowledge as what the table means. `offers` calls `record`; it does not decide. That is
  the one cross-feature import in the offers feature, and it is listed with its reason in
  `tests/test_architecture.py`.
- **No foreign keys out of this table.** A partitioned table cannot be referenced anyway,
  and these rows are facts that should outlive anything that might be deleted.
- **Read by cursor, not offset.** An append-only feed read by position repeats rows as new
  ones arrive — the same reason the audit trail is paged this way.
- **Nothing rolls new partitions yet.** The default partition catches anything outside the
  declared range, which keeps inserts working and piles rows somewhere awkward. See
  `TODO.md`.

See also `docs/parser-design.md`.
