# judge

Asking an outside model a bounded question, and remembering what it said.

Backed by [TypeSafe](https://docs.typesafe.ai), whose System One models return a typed
answer and a probability rather than text. The judge here asks two kinds of question: which of several brands a listing means, and
which of several catalogue entries it is.

## Endpoints

| | |
|---|---|
| `GET /api/admin/judge/verdicts` | every answer bought, with what it was asked, filterable by `kind` |

Running the judge is deliberately **not** here. For brands that is
`POST /api/admin/matching/judge` and for entries `POST /api/admin/matching/judge/ambiguous`,
because deciding a question is worth asking belongs to whoever owns the work — this feature
only answers and remembers.

## How it works

**One question: `brand_choice`.** A `Choice` over the brands a listing's brand string
resolves to, plus `none_of_these`. It exists because an alias cannot settle this and never
will: `Delta` belongs to the tap company and the tool company equally legitimately, so which
one a listing means is decided per listing, not once for the string. That is the one gap in
brand resolution that more data does not close.

**The second question: `variant_choice`.** A `Choice` over the catalogue entries a listing
could be, plus `none_of_these`. It exists because the corpus was asked first and cannot
answer: a marketing colour name belongs to a maker, and `Canyon` is pink on a Google and
orange on an Oppo — both proved by two shops each — so no row in a registry keyed on the
word alone can hold it. Counting settles some names (`Obsidian` black on 97 of 97 across
seven shops, `Midnight` black on 61 of 70 across eight) and proves the rest unsettleable
that way.

**Its options are described by the axes that tell them apart** — `Colour: black` — and by
nothing else. The model string is identical on all of them, which is why the listing was
ambiguous, so any other description would describe every option the same way and decide
nothing. The brand is named in the state separately from the title, because the word being
judged belongs to a maker.

**A verdict here places the listing**, unlike a brand's, which goes into the store for the
ladder to resolve on its own. No rung consults this one: the model rung found the candidates
and the judge chose among them, so that is what the link records — `method` the rung that
fired, `decided_by` the judge.

**The options are described by what the catalogue already holds under each brand** — the
categories its variants sit in, and nothing else. That is the only true thing available
here. A brand with nothing under it gets no description at all, the answer comes back
unconfident, and an unconfident answer is one this refuses to act on. That is correct
behaviour rather than a gap: the judge is worth its cost once the catalogue has something
in it, and not before.

**Every Choice carries `none_of_these`.** Without a way out the model can only pick one of
the options it was handed, and it will do that as confidently as any other answer — the one
failure mode that produces a wrong match rather than no match. Answered "neither" is treated
as a decision: the listing moves to `brand_unknown`, which is different work.

**A verdict is an input to matching, never a match.** The matcher reads the verdict store
and cannot reach the network through it, so running the ladder stays offline, deterministic
and as fast as its indexes. Asking is a separate pass an admin starts.

## Decisions worth knowing before changing it

- **The store is keyed by the question, not by the offer.** `question_hash` covers the state
  and the options exactly as they will be sent, so a listing whose title changed, or whose
  candidates changed because a brand was added, is a new question and is asked again rather
  than answered from a stale row. Two shops wording a listing identically are one question.
- **It exists for retries, not for repeats.** The saving that matters is not the same
  listing twice — it is that the matcher retries the whole queue on every pass, because the
  catalogue it failed against keeps changing underneath it. Without a store, one stuck
  listing would be paid for again on every run, forever.
- **The configured model name is in the key; the one that answered is not.** Pinning a
  version is a deliberate act and deserves fresh answers. `jev-latest` moving underneath is
  not, and should not silently invalidate everything ever asked. Which model actually
  answered is stored on the row, so a change stays visible after the fact.
- **The key is the only switch.** There is no `JUDGE_ENABLED` flag, because a flag and a key
  can disagree and then the panel offers a button that cannot work. No `TYPESAFE_API_KEY`
  means `POST /api/admin/matching/judge` returns 422 `judge_disabled`.
- **`JUDGE_MIN_CONFIDENCE` is a starting point, not a measurement.** The TypeSafe docs are
  explicit that a threshold has to be evaluated against real data and this catalogue has
  none yet. An answer below it is still recorded and still not acted on — recording it is
  how the threshold gets chosen later.
- **A failure is reported and never stored.** A stored failure would read as an answer on
  the next pass. The report names the first one, because a pass that says "failed: 20" with
  no reason is a pass nobody can fix.
- **Writes use a savepoint**, unlike the other services, which handle a conflict by rolling
  the request back and returning 409. Here a conflict is harmless — another pass asked first
  — and the pass has to continue, so only the one insert is undone and the verdicts already
  written survive.
- **One listing is one request.** The state differs per listing, so they cannot share one,
  which is the case the parallel-questions advice does not cover. They are sent together,
  bounded by `JUDGE_CONCURRENCY`, and written afterwards one at a time on the request's own
  session.
- **The retry budget is tied to the configured timeout.** The SDK retries 5xx and timeouts
  on its own, which is wanted, but its default budget is a flat 30 seconds per question and
  a pass asks many. Tying them keeps one number predicting the worst case.
- **This feature knows nothing about offers or the match queue.** It takes a question,
  answers it once, stores it. That is what keeps an outside dependency from spreading
  through the matcher, and what leaves room for the next questions — attribute aliases and
  category mapping have the same shape.
