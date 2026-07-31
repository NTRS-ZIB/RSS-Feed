[← Watchlist monitor](../README.md)

# Shares outstanding

Tracks dilution: the share count each company reports on its own filing covers,
and how fast it is growing. Posts when a reported figure moves.

## Schedule

`0 15 * * 1-5` — 15:00 UTC weekdays. Counts change when a company files, so
this checks daily and posts only on a change. In practice that is roughly
quarterly per company, clustered around reporting season.

## Why this watchlist needs it

These companies fund themselves largely by issuing stock — at-the-market
programmes that sell continuously rather than in discrete raises. NUAI is
contracted to establish a $100M ATM against a company whose entire off-exchange
daily volume runs a few million shares.

The effect is that **share count erodes returns quietly**. A stock flat on the
year with 40% more shares outstanding has lost 40% of its per-share claim on
the business. Every price-based component in this repo — the
[recap](recap.md), the [spike alerts](volume-spikes.md) — shows the numerator.
This is the only one that shows the denominator.

## Data source

SEC's XBRL `companyconcept` API, keyed by CIK. One request per company.

Filers do not agree on which concept carries the number, so three are probed in
order and the one used is named per company in the log:

| Concept | Notes |
|---|---|
| `dei:EntityCommonStockSharesOutstanding` | The cover-page tag. Present on every periodic filing. |
| `us-gaap:CommonStockSharesOutstanding` | Balance-sheet fallback |
| `us-gaap:CommonStockSharesIssued` | Last resort — issued, not outstanding, so it counts treasury stock |

This is the same probing pattern
[short interest](short-interest.md#schema-discovery) uses, and for the same
reason: guessing one field name and getting silence is indistinguishable from
having no data.

**Amended filings supersede originals.** Several filings can report the same
as-of date; the one with the latest `filed` timestamp wins, so a 10-K/A
correcting a count replaces it rather than sitting beside it.

## Critical: reverse splits read as buybacks

**XBRL share counts are not split-adjusted.** Each filing reports the count as
of its own date, so a 1-for-10 reverse split drops the reported figure by 90%.

Untreated, that posts as a spectacular share reduction — the single most
misleading output this component could produce, and on a watchlist where it is
close to inevitable. ANY, BGDE, BKKT, SLNH and VIP have all done reverse
splits; the CUSIP issue numbers recorded in
[the watchlist](watchlist.md#cusips-what-they-survive) show it.

Any decrease steeper than `SPLIT_DROP_PCT` (35%) is therefore treated as a
corporate action, not a reduction:

- the step renders as `split` rather than a percentage
- trailing growth is **suppressed**, because a series spanning a split is not
  comparable across it
- a prose line says so explicitly
- the embed turns red

**A split anywhere inside the trailing year suppresses the year figure too**,
not only a split in the most recent step. A company that split six months ago
and has diluted since would otherwise report growth measured against
pre-split units.

Genuine buybacks are not the competing explanation. None of these companies has
the balance sheet for one, and a 35% reduction would be extraordinary even for
a company that did.

## Output

```
      Shares   Chg    1yr
-------------------------
NUAI   88.0M  +11%  +96%*
MARA   12.0M   +0%    +0%
ANY     4.1M split      -
WYFI    5.0M     -      -
```

| Column | Meaning |
|---|---|
| `Shares` | Latest reported count, as of that filing's own date |
| `Chg` | Change since the previous reported figure, or `split` |
| `1yr` | Change against the closest observation at least a year older |

`*` marks trailing growth at or above `NOTABLE_YEAR_PCT` (25%). A single step at
or above `NOTABLE_STEP_PCT` (10%) gets a prose line naming both figures.

**An absent `1yr` figure has two opposite causes, and they are shown
differently:**

| Shown | Cause | Means |
|---|---|---|
| `-~` | Fewer than a year of reported observations | The company has not been reporting long enough. Says nothing about dilution. |
| `split` | A reverse split inside the trailing year | The comparison is invalid, not unavailable. Growth may be large and is unknown. |

Both are also named in prose beneath the table. On the first live run these
split cleanly: BKKT and IREN had three observations each and WYFI four —
recent domestic filers — while ANY (30 observations) and BGDE (60) were
suppressed by splits. A single `-` for both would have made a young company
look identical to one whose history is uncomparable.

Rows sort by trailing growth, so the most diluted name leads. Percentages are
width-capped at `>999%` and `<-99%` — an extreme reading must not widen the
table past the mobile wrap point.

## What this number is not

**Not a float.** It includes insider and restricted holdings.

**Not fully diluted.** It excludes warrants, options and convertibles that have
not been exercised. Several companies here carry large warrant overhangs — the
true diluted count is higher than anything shown, sometimes substantially.

**Not synchronised across companies.** Each figure is as of that company's own
filing date, which is why the table prints those dates in the log. Comparing
two companies' counts compares two different moments.

## A partial fetch is not a partial post

If any company fails — a request error, or no share-count concept tagged at all
— the run **exits without posting**.

A company missing from the table would read as "no dilution", which is the
opposite of "unknown". The same reasoning as
[comment letters](comment-letters.md#a-partial-fetch-is-not-a-partial-post):
the output is an assertion about every company on the watchlist, so an omission
inverts a row rather than just dropping it.

## Known quirks

- **Silence is not stability.** A company that has not filed since its last
  report shows no change because there is no new data, not because the count
  held. Read `Shares` with the as-of date in the log.
- **Cover-page counts lag the balance sheet.** The cover figure is dated near
  filing and is usually the most current number in the document, but shares
  issued between that date and publication are not in it.
- **`CommonStockSharesIssued` is not `Outstanding`.** If a company falls
  through to the third concept, its figure includes treasury stock and is not
  comparable with the others. The log names the concept used per company —
  check it before comparing across the table.
