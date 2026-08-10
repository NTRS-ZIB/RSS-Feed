# The first live digest — 2026-W32

Reviewed 2026-08-09. Run 31269190556, posted 2026-08-08 17:21Z. **Nothing
changed.**

Two of the three checks pass cleanly. The third passes on the file and the
gate and **fails on the link — there isn't one.** Plus two rendering defects
found while reading, one of which inverts a convention in CLAUDE.md.

---

## 1. The five added mid-week — the premise does not apply, and that is the
## design working

**All nineteen companies have five sessions and eleven contributor verdicts.
There is no partial coverage to report.**

```
       sess  volmult  basewk basesess  svsess
ABTC      5        5      12       30      20   <- added 08-05
APLD      5        5      12       30      20   <- added 08-05
BTDR      5        5      12       30      20   <- added 08-05
GLXY      5        5      12       30      20   <- added 08-05
SPCX      5        5       7       30      20   <- added 08-05
MARA      5        5      12       30      20
...all others identical
```

**The reason is the re-derivation decision.** The digest queries Alpaca, FINRA
and EDGAR by symbol and CIK for the whole week; it does not accumulate from
what the repo saw. Alpaca had GLXY's Monday bar whether or not `watchlist.py`
did. So a company joining on Wednesday has a complete week, and the state you
were worried about — three of five reading as five — cannot arise for any
contributor.

I checked the two that could plausibly have depended on repo state. `ftd` and
`short_interest` published nothing this week for anyone, and both recorded that
as a basis string (`no new half-month period published this week`) rather than
as silence. Neither read `ftd_state.json` for a verdict.

**SPCX is the one genuinely short-history company and it is handled
correctly** — IPO 2026-06-12, so:

- price: `baseline_weeks: 7` against everyone else's 12, and the basis string
  says so — *"2.2x its own 7-week return SD of 10.6%"*
- crossings: `not-testable`, `34/60 bars minimum for a 52-week window`, listed
  under **Not measurable this week** with the count

That is the count-against-the-floor convention working on its first live week.

### One thing worth flagging, not fixing

**GLXY's notable verdict this week is a `SCHEDULE 13G/A`, and the digest
reports it for the full week including the days before GLXY joined the
roster.** That is correct for a weekly summary and it is now the exact
opposite of what `press_monitor` does — which, as of yesterday, suppresses
everything from before a company was added.

Two components, opposite rules on the same question, both defensible: the
monitor is an event feed where a backdated post is noise, the digest is a
summary of a week that happened. **Nothing is wrong. But it is not written
down anywhere**, and the next person to notice will reasonably think one of
them is a bug.

---

## 2. Convergence — printed, and the collapse earned its keep

**It printed.** Post: *"Nothing converged this week."* File: the same, plus the
line that makes an empty section legible:

> This section prints when it is empty. In the ten-week backfill six weeks
> landed here, so an empty convergence section is the ordinary case and means
> the filter worked — not that the digest found nothing to look at.

The distribution: **14 companies at 0 families, 4 at 1, 1 at 2.** Max is IREN.

**The families that did appear are genuinely distinct**, and the check you
asked for is answerable directly from the record:

| | count | families | components |
|---|---|---|---|
| IREN | 2 | filings, holders | filings, holders |
| CIFR | 1 | short_volume | short_volume |
| GLXY | 1 | holders | holders |
| SLNH | 1 | holders | holders |
| **SPCX** | **1** | **market** | **price, volume** |

**SPCX is the case the collapse was built for, and this is the first time it
has fired outside a backfill.** Two components — price and volume — collapse
to one family. Without `SOURCE_FAMILY` it would have read as 2 families and
sat beside IREN in the listed tier, on what is one Alpaca bar series read
twice.

The ≥2 tier is listed rather than promoted, as specified: *"At 2 families,
not promoted: IREN"*.

---

## 3. File, gate — pass. Link — fail.

**File:** `digest/2026-W32.md` and `.json` are both on `origin/main`, commit
`1148815` "Weekly digest [skip ci]".

**Gate, checked directly rather than inferred.** I dispatched the workflow
again:

```
Target week: 2026-W32
digest/2026-W32.md exists — 2026-W32 has already been produced. Nothing to do.
```

Tomorrow's 17:00 fire will do the same. The gate is closed.

### The post does not link to the file

**Zero URLs in the posted embed.** The footer carries the text
`FTD 2-6wk · digest/2026-W32.md` — a bare path, not a link, and not resolvable
from Discord. There is no `github.com` URL anywhere in `digest_render.py`.

So the dual output exists but the two halves are not connected: a reader in the
channel has no way to reach the file the post is a summary of. That is the one
outright miss against the design.

---

## Two defects found while reading

**The `close` column is mislabelled and has never held a close.** The header
promises one and the cell renders a session count, so every row reads
`close: 5 sessions`:

```
| **MARA** | -10.9% | 1.2x | · | 5 sessions |
```

`bar_figure()`'s docstring says *"Close, week return and volume multiple"* and
the dict it returns has no close key. **There is no absolute price anywhere in
the file or the record** — only percentages and multiples.

**The `~` marks the wrong company on 52w, and it inverts the CLAUDE.md
convention.** The rule is `~` on the affected column when a figure is computed
over a short window. What happens instead:

| | crossings verdict | 52w cell |
|---|---|---|
| **WYFI** | routine, measured on **247 bars** | `~` / "(short window)" |
| **SPCX** | **not-testable, 34/60 bars** | `·` — *measured, routine* |

`bar_figure()` reads `short_window` out of the crossings detail, and a
not-testable verdict has an **empty** detail — so the company that genuinely
could not be tested is the one that reads as routine, while the company that
was tested gets the caveat.

It is not invisible: **Not measurable this week** lists SPCX crossings with its
count, so the file contradicts itself rather than hiding anything. But the grid
column is exactly where CLAUDE.md says the mark belongs.

---

## Is the post worth reading?

**Half. The filter worked and the post buries the week's actual news.**

What it says: nothing converged, IREN at two families, two persistence findings
(CIFR short volume, SPCX volume), two silent companies, two not-measurable with
counts. All correct, all defensible.

What the week actually was:

```
CIFR  -23.0%  2.6x
SPCX  +22.8%  3.5x
HUT   -17.7%  1.7x
ABTC  +17.2%  1.2x
```

**CIFR down 23% and SPCX up 22.8% are the story, and they appear only as rows
in the monospace block.** A reader scanning the headed sections sees "nothing
converged" and two persistence lines, and has to read the table to find that
two names moved more than a fifth in five sessions.

That is a design consequence rather than a bug, and it is worth naming
precisely: **the digest answers "what converged" and "what persisted", and a
large single-name move that does neither falls between them.** CIFR's -23% did
not converge because only short volume flagged; SPCX's +22.8% did appear, but
as *volume* persistence rather than as the price move.

So it is not a table of nothing much — it has two real findings and an honest
empty section. But it under-sells its own week, and the fix is not more
filtering.

---

## Is the markdown usable as article source?

**Mostly yes, and the density landed in the right half** — 147 lines, 8,079
characters, against a post that fits on a screen. That was the point of the
dual output and it worked.

What it carries that the post does not: the provenance table with per-source
request counts and timings, the full contributor table with cadence and
persistence eligibility, the never-fired warning with its measurement (dilution
0 of 190 ticker-weeks, HUT's +9.50% against a 10.0% threshold), the complete
19×9 grid including the routine cells, and the roster.

**Three gaps for article use, in order:**

1. **No absolute prices anywhere.** Not in the file, not in the record. An
   article says "CIFR fell 23% to $X" and the second half is unavailable. This
   is the same root as the broken `close` column.
2. **One URL in the whole file** — IREN's 424B7. Every other finding is
   unlinked, including all three holder disclosures, so a writer has to go
   find each source.
3. **No absolute volumes**, only multiples. "3.5x its 30-session median" needs
   the median to become a sentence.

None is fatal and all three are additive rather than structural.

---

## Summary

| | |
|---|---|
| Five added mid-week | **pass** — full coverage, and genuinely so; SPCX's short history correctly flagged |
| Convergence printed when empty | **pass** — and the market collapse fired live for the first time, on SPCX |
| File on main | **pass** — both files, commit `1148815` |
| Gate | **pass** — verified by dispatch, not inferred |
| Post links to the file | **FAIL** — no URL in the post at all |
| `close` column | mislabelled; renders session counts, no price exists |
| `~` on 52w | marks WYFI (measured) and not SPCX (not-testable) — inverts the convention |
| Worth reading | half — correct, but the week's two biggest moves are only table rows |
| Usable as article source | yes, with no prices, no volumes and one link |
