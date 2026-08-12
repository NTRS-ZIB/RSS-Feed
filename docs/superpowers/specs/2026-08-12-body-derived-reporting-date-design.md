# Reading a reporting date out of a release body

Design, 2026-08-12.

## What this adds

When a company announces its reporting date in the body of a release rather than
in the title, the calendar currently misses it and keeps showing a projection.
This stores the announced date instead, and marks it as one we read rather than
one the company put in its headline.

## The evidence, and its limits

`probe_body_dates.py` ran against all twenty undated announcements on 2026-08-12
(runs `31609856639` and `31610431541`). With the body's own dateline excluded,
the scheduled-event label separates cleanly:

| label | one | several | none |
|---|---|---|---|
| advance notice | 5 | 0 | 1 |
| scheduled + results | 2 | 2 | 2 |
| not scheduled | 3 | 1 | 4 |

An advance notice yields exactly one forward date and never several. That is the
result this rule rests on.

**It is thinner than the row counts make it look, and the spec says so because
the counts invite the opposite reading.** The rule fires only on a title naming
a scheduled event, so its population is the first two rows above: twelve
releases, of which seven yield exactly one date. **Those seven come from three
companies**: ABTC four times, BKKT twice, WYFI once. ABTC's four are the same
quarterly template, so they are close to one observation repeated, not four
independent ones. The population that matters is companies, not releases.

The sixth advance notice, HUT's, yields nothing for a reason no rule can fix:
`hut8.com` serves no release body to a plain fetch, only a headline, a posting
date and a signup form. It is not a counter-example to the rule; it is a source
that cannot be read. See `docs/press-monitor.md`.

**This should be re-measured once more companies have accumulated.** At roughly
one advance notice per company per quarter, a materially wider sample is months
away. The design is built to be safe at three companies rather than to wait.

## The rule

In `record_disclosed_dates`, fetch the body when an item is **all four** of:

- new this run
- a recognised announcement
- carrying no parsable date in its title
- naming a scheduled event

Then: **if `candidate_dates` returns exactly one date, store it. Otherwise store
nothing.**

"Exactly one" is the entire rule. With several candidates there is no basis to
choose between the call date, the replay expiry and the period end, and choosing
would be the guess this repo has paid for three times. With none there is nothing
to store. Both cases log their count so the next measurement has data.

The existing date guard still applies unchanged: a date before today is rejected.
That guard is on our reading, not on the company.

### The freshness gate returns, and this time it is right

That gate is why the old measurement produced nothing: the twenty announcements
had all been seen already, so none was ever fetched. **For a production rule it
is exactly right.** A new advance notice is fetched once, its date recovered, and
never fetched again. Without it the monitor would re-fetch the same dozen pages
about eight times an hour, indefinitely, for an answer that does not change.

The gate was not wrong. It was wrong for backfilling, which is what
`probe_body_dates.py` now exists to do.

### Fetching returns to the component that posts

This re-adds a network call to `press_monitor.py`, which the 2026-08-12 body-probe
work deliberately removed. That is not a reversal of it: what was removed was a
*measurement* that had never measured anything, and it was removed so a hand-run
tool could do the backfill the gate prevented. What returns is a *fetch with a
purpose*, on the gate that was always correct for production.

The exposure is bounded by the same `try`/`except` that already wraps
`record_disclosed_dates`, which exists so a failure writing a second file cannot
silence the press channel. `announcement_body` never raises, returns `None` on
any failure, and caps its download at `BODY_MAX_BYTES`. A source that stops
answering costs a date, not a post.

## What gets stored

The record gains one key:

```python
"source": "title" | "body"
```

**Records already on file have no `source` key, and its absence means `"title"`.**
That is correct rather than a default: every date stored before this change came
from a headline. Nothing needs migrating.

`upsert`'s existing rule is untouched. A later release wins, judged by the
release's own timestamp. A body-derived date and a title-derived date compete on
that timestamp alone, never on provenance. A company that moves its date issues a
second release, and which half of the release we read it from says nothing about
which is newer.

`apply()` carries the provenance onto the row alongside `r["disclosed"]`.

## What the reader sees

A body-derived row is marked `+` where a title-derived one is marked `!`, with
the key line `+ date read from body`.

`?` would be the natural character for "less certain" and is already taken by
thin history. The marker column stays one character wide and no column is added,
so the row stays at 25 characters against the 28-character ceiling.

The key line is added only when a `+` row is actually rendered, matching how
every other key line already behaves.

### Overdue grace: a `+` row keeps it, a `!` row does not

An `!` row gets `grace = 0` today, on the stated reasoning that a company's own
announced date has no projection spread to allow for. **A `+` row is still the
company's own date**: the company said it, and we simply read it from the body
rather than the headline. What differs is the reliability of *our reading*, not
of their statement.

So a `+` row keeps the normal `OVERDUE_GRACE` of 10 days. A misread date should
not put a company in Overdue on day one.

This deliberately repurposes a constant justified for projection spread, using it
for reading risk instead. The effect is right and the reasoning is different from
the one written where the constant is defined, so both places must say so.

## What is deliberately not built

- **No backfill.** The rule fires only on new items. The five recoverable dates
  the probe found are all in the past except WYFI's, and the existing guard
  rejects past dates anyway, so a backfill would store nothing today.
- **No rule for `several`.** Picking among candidates is the next question, and
  it needs evidence this measurement does not contain.
- **No route to HUT's body.** That is a per-source problem, not a rule problem.
- **No confidence score, no per-company allowlist.** Three companies is too thin
  to calibrate either, and both would be built on the same seven rows.

## Verification

- The rule's arms are testable without network by injecting the fetch, the way
  `probe_rows` already takes `fetch` as an argument. Each of the four gate
  conditions needs a case that fails it, and `several` and `none` each need a
  case proving nothing is stored.
- `"source"` absence meaning `"title"` needs a test over a record written before
  this change.
- The `+` marker, its key line and the retained grace each need a test; the grace
  one must demonstrate that a `+` row and an `!` row with the same past date fall
  on opposite sides of Overdue.
- A dry run must show the fetch firing on a new advance notice, or state plainly
  that no new advance notice occurred in that run. **A run that stores nothing is
  not evidence the rule works.** That was the failure of the measurement this
  replaces, and the log must distinguish "no candidate item this run" from
  "fetched and found nothing".
