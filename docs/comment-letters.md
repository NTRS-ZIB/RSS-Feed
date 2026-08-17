[← Watchlist monitor](../README.md)

# SEC comment letters

Posts when the SEC's Division of Corporation Finance has an open review of a
watchlist company's disclosure. Silent when nothing changes.

## Schedule

`30 13 * * 1-5` — 13:30 UTC weekdays. Nothing here is urgent; the SEC releases
correspondence at least 20 business days after completing a review, so a letter
is already weeks old when it appears.

## What it reports

Two EDGAR form types make up a review:

| Form | Direction |
|---|---|
| `UPLOAD` | SEC staff → company |
| `CORRESP` | company → SEC |

A review is **scrutiny of disclosure, not an enforcement action**. Most close
with no change. The caveat is on every post.

This **pairs with the `NT 10-K` / `NT 10-Q` late-filing notices** the
[press monitor](press-monitor.md) watches for. An open review alongside a late
filing is a much stronger signal than either alone.

## Critical: why this is not a press monitor form type

The obvious implementation adds `UPLOAD` and `CORRESP` to `FORM_TYPES` in
`press_monitor.py`. It was proposed as a one-line change. **It produces
nothing.**

Measured across the watchlist on 2026-07-31:

| | |
|---|---|
| Comment-letter filings found | 424 |
| Inside `RETAIN_DAYS` (30) | **0** |
| Inside `MAX_AGE_DAYS` (7) | **0** |
| Age of the newest letter on the entire watchlist | **86 days** |

That is a property of the data rather than bad luck. Correspondence publishes
long after the fact, and it arrives in **bursts** — several exchanges over a
few weeks, then silence for a year or more:

```
SLNH   6 letters   07 Apr – 06 May 2026
NUAI   6 letters   28 Jan – 17 Apr 2026
DGXX   2 letters   13 Apr 2026
MARA   nothing since June 2024
```

A seven-day window will essentially always miss them. `LOOKBACK_DAYS` is 180.

**The lesson generalises.** Before adding a form type, check whether its filing
dates fall inside the windows that already exist. A form type that never
matches is indistinguishable from a form type that never fires.

## LOOKBACK_DAYS is not a posting filter

It defines what "currently under review" means. Every letter inside the window
is described in every post; the window is not deciding what is fresh enough to
mention.

180 days is roughly two review cycles — long enough that a burst stays visible
after it ends, short enough that a review closed a year ago drops off.

It is also deliberately generous for a reason that cannot be resolved from the
data. EDGAR's `filingDate` is the **submission** date, not the publication
date, and the submissions API does not expose the latter. So the gap between
when a letter was written and when it became visible is unknown — it may be one
day or three months. A window this wide works correctly either way.

## Output

```
      Ltrs    Last From
-----------------------
SLNH     3  06 May   co
NUAI     2  17 Apr   co
DGXX     2  31 Jul  SEC
```

| Column | Meaning |
|---|---|
| `Ltrs` | Exchanges inside the window |
| `Last` | Date of the most recent one |
| `From` | Who sent it — `SEC` or `co` |

**`From` is the column to read.** `SEC` means a staff comment is outstanding
and the company has not yet replied. `co` means the ball is back with the SEC.
Rows sort by most recent letter, so an active conversation leads.

Companies with `NOTABLE_EXCHANGES` (3) or more get a prose line beneath the
table with a direct link to the newest filing.

## One post, not one per letter

The unit is the **review**, not the letter. Six posts saying "SLNH filed a
CORRESP" is noise; one line saying "SLNH, 6 exchanges since 7 April, company
replied" is the signal.

This also bounds the output by watchlist size — eleven rows at absolute worst —
which is why the component **posts on its first run** rather than bootstrapping
silently the way the [press monitor](press-monitor.md#testing) does.

**That reasoning is sound about the POST and was wrong about the flood**, and
the sentence that used to end this paragraph said there was none to guard
against. One post per run is indeed the ceiling. But the same argument was
read as covering a company ADDED to an existing roster, and there the ceiling
is not the issue: every letter inside a 180-day window is unseen for such a
company, which is the widest window in the repo and so the largest possible
backlog. See *adding a company* below.

## A partial fetch is not a partial post

If any company's submissions request fails, the run **exits without posting**.

A company missing from the table would read as "no open review", which is the
opposite of "unknown". That distinction matters more here than elsewhere: the
whole output is an assertion about which companies are and are not under
review, and a silent omission inverts the meaning of a row.

## State

`letters_state.json` holds the accession numbers seen inside the window. A post
fires only when an accession appears that was not there before.

Retention is bounded by the window rather than by count — anything outside
`LOOKBACK_DAYS` can never appear again, so remembering it is dead weight. The
file is rewritten on every run, including runs that post nothing, so the set
tracks the window as it slides.

## Adding a company, or a form type

**A company added to the roster contributes nothing on its first run.** For a
company absent from `letters_state.json` every letter inside `LOOKBACK_DAYS`
is new, and at 180 days that is the widest window in the repo. The accessions
are still recorded by `save_state`, so the next genuine letter posts normally.

This component escaped the incident that established the rule. On 2026-08-14
`holder_events` sent 86 messages from exactly this shape; the three companies
added that week simply had no correspondence in window. **That is luck, not a
guard**, and it is the reason the rule was applied here rather than only where
it had already gone wrong.

The `first_run` variable already in `main()` is NOT this rule. It asks whether
the state FILE exists, is used only to annotate a log line, and suppresses
nothing. Even as a guard it would cover a cold start and not a company added
to a roster this component has watched for months.

**The same rule runs over `FORMS`**, in its own namespace, matched exactly
rather than by prefix — neither `UPLOAD` nor `CORRESP` has amendment variants.
A third entry would otherwise post every such filing on the roster at once.

**The backfill announces itself** with a `FIRST-RUN RULE:` line on the one run
where a namespace is absent. Without it, a component that ran the rule and one
where it was never wired produce identical logs.

The decision lives in [`first_run.py`](../first_run.py); what suppression
means stays here, because it differs in every component that has the rule.

## Known quirks

- **Not timely, by construction.** Comparable to
  [fails to deliver](fails-to-deliver.md#critical-this-is-the-slow-one) in
  latency, though the delay is disclosure policy rather than a publication
  schedule. Do not read a post as news.
- **A closed review looks like an open one** until it slides out of the window.
  The SEC's final letter — staff confirming the review is complete — is itself
  an `UPLOAD`, so a `From: SEC` row may mean "comment outstanding" or "review
  closed". Follow the link to tell.
- **Form matching is exact, not prefix.** Neither form has amendment variants,
  and prefix matching would be a liability rather than a feature here.
- **The count is exchanges, not distinct issues.** One review may generate
  several rounds on the same point.
