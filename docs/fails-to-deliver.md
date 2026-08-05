[← Watchlist monitor](../README.md)

# Fails to deliver

Posts each watchlist ticker's peak fails-to-deliver balance for a half-month
settlement period, against its own trailing median.

## Schedule

`0 13 * * *` — daily, posting only when a period newer than the one in
`ftd_state.json` appears on the SEC's index page. About two posts a month.

Daily rather than twice-monthly, and every day rather than weekdays, because
the SEC states it cannot guarantee publication by a particular date and the
release does not align to weekdays. Checking cheaply and deduping on the
period identifier is more reliable than predicting the window.

## Critical: this is the slow one

Every other component in this repo is same-day or next-day. This one is not.

| Component | Lag |
|---|---|
| [Press releases](press-monitor.md) | minutes |
| [Volume spikes](volume-spikes.md) | 15 minutes |
| [Short sale volume](regsho-volume.md) | ~1 day |
| [Short interest](short-interest.md) | ~2 weeks |
| **This** | **2–6 weeks** |

The first half of a month publishes at month end; the second half publishes
around the 15th of the following month. So a fail on the 2nd of a month is
visible about four weeks later, and one on the 16th about four weeks later
again. Worst case is roughly six weeks.

**This is context, not a signal.** Nothing here is tradeable by the time you
read it. Its value is retrospective: when a company had an unexplained move
six weeks ago, this says whether settlement was also stressed at the time.

## Critical: what the number is not

**Not evidence of naked shorting.** The SEC says so directly on the source
page: fails occur on both long and short sales for many reasons, and are not
evidence of abusive or naked short selling. Most are ordinary settlement
friction. This dataset is probably the most over-interpreted one in retail
market data, which is the reason for the caveat on every post.

**Not a daily flow.** Each figure is the *cumulative net balance outstanding*
on that settlement date: everything still unsettled, plus new fails that day,
less fails that cleared. Consecutive days are not additive and summing the
column produces a meaningless number. The SEC also notes that the age of a
fail cannot be recovered from the series, and that today's balance may have
no relationship to yesterday's.

That is why the table reports a **peak**, not a total.

**Not a position measure.** Compare with the two FINRA components:

| | [Short interest](short-interest.md) | [Short volume](regsho-volume.md) | This |
|---|---|---|---|
| Measures | Shares held short | Shares sold short per session | Shares undelivered at settlement |
| Kind | Position | Flow | Balance |
| Frequency | Twice monthly | Daily | Twice monthly |
| Lag | ~2 weeks | ~1 day | 2–6 weeks |

## Output

```
       Peak  xMed  Dys
----------------------
SLNH   415K  7.8x*   9
MARA   559K  1.0x    9
WYFI    68K  1.0x~  11
DGXX    31K  0.9x   10
```

| Column | Meaning |
|---|---|
| `Peak` | Largest single-day fail balance in the period |
| `xMed` | That peak as a multiple of the ticker's median peak over prior periods |
| `Dys` | Settlement days in the period with a non-zero balance |

`>99x` in the `xMed` column means the median is **zero** — every prior period
was clean and this is the first time the name has failed at all. That is the
most interesting row the table can produce, so it sorts to the top. It is also
the display for any ratio genuinely above 99x.

| Marker | Meaning |
|---|---|
| `*` | Peak is ≥`FLAG_MULTIPLE` (3x) the median **and** ≥`MIN_FLAG_SHARES` (50,000) |
| `~` | Fewer than `MIN_FLAG_PERIODS` (4) prior periods — ratio shown, but cannot flag |
| *(none)* | Ordinary |

Rows sort by `xMed`, so the largest deviation leads. Flagged tickers get a line
beneath the table naming the peak date and the median it is measured against;
the raw median never appears in the grid, where there is no room for it.

**`Dys` carries more than it looks.** A 5x peak on one day is a single failed
block. A 2x peak sustained across every settlement day in the period is a
different situation. Read the two columns together.

## Absence is a zero, not a gap

The SEC only lists securities with a non-zero balance, so a ticker missing from
a file had zero net fails on every settlement date in it. That is a
measurement, not missing data, and the script stores it as a literal zero.

This matters more than it sounds. Computing the median over only the periods
where a ticker *appeared* would take the median of its non-zero periods —
understating every ratio, and erasing the single most informative case: a name
that never fails suddenly failing. Under that treatment a company with five
clean periods and one 700K period reads as ordinary. Stored as zeros, its
median is 0 and it goes straight to the top of the table.

Absent tickers are also named under the table and in the log for every period,
rather than silently dropped, so a broken symbol match cannot masquerade as a
clean period. That distinction is the whole diagnostic — see below.

## Critical: the download URLs are not constructible

The obvious implementation builds the filename from the date. Do not. The
SEC has moved these files repeatedly, and the path prefix is not stable:

| Period | Path | Differs by |
|---|---|---|
| June 2026 | `/files/data/fails-deliver-data/cnsfails202606b.zip` | — |
| May 2026 | `/files/data/other/fails-deliver-data/cnsfails202605a.zip` | extra `other/` |
| Aug 2023 | `/files/data/other/fails-deliver-data/cnsfails202308b_0.zip` | `_0` suffix |
| Apr 2020 | `/files/node/add/data_distribution/cnsfails202004a.zip` | entirely different |
| pre-2017 | `/files/data/frequently-requested-foia-document-fails-deliver-data/` | legacy FOIA path |

Four prefixes and two filename shapes, one of the prefixes introduced within
the last three months. A constructed URL would have broken at least four times
and would fail as a 404 that looks identical to "not published yet".

`fetch_index()` therefore scrapes the index page for any href matching
`cnsfails<yyyy><mm><a|b>*.zip` and takes the URL as given. If the page layout
ever changes so no links match, the script says so explicitly rather than
reporting no new data.

## Ticker renames are the main failure mode

This is the only component that reads *backwards* through months of files, so
renames bite here in a way they do not elsewhere: a period predating a rename
carries the old symbol throughout. Seven on the current watchlist — the full
list, with dates, is in [the watchlist docs](watchlist.md#renames-on-the-current-watchlist).
The two most recent:

| Was | Now | Effective | Notes |
|---|---|---|---|
| `GREE` Greenidge Generation | `VIP` Vulcan Infrastructure and Power | 24 Jul 2026 | GREE traded through the close on 23 Jul |
| `MIGI` Mawson Infrastructure | `BGDE` Big Digital Energy | 30 Apr 2026 | CUSIP changed separately, Nov 2025 |

Note the dates against the publication schedule. The 2026-07a file covers
1–15 July, entirely *before* the VIP change — so Vulcan's fails are filed under
`GREE` in a period that publishes after the ticker no longer exists.

Three defences, in order of durability. All three read from
[`watchlist.py`](watchlist.md):

1. **CUSIPs** — `CUSIP_PINS = watchlist.cusip_pins()`. A CUSIP survives a
   *rename* but **not a reverse split**, which is why `cusips` is a list and
   ANY carries two. See
   [what CUSIPs survive](watchlist.md#cusips-what-they-survive).

   The script prints every CUSIP it finds in the data that is **not** in the
   roster, so the block stays silent once complete and speaks up the moment a
   ticker turns up under a new one — itself the signal worth having.

### Critical: a recycled ticker, and the three guards against it

A rename is one company under two symbols. The opposite also happens — **two
companies under one symbol** — and this component is where it does damage,
because it is the one that reads backwards past the handover.

`SPCX` belonged to a SPAC ETF until 2026-04-07 and to Space Exploration
Technologies from 2026-06-15. The full case is in
[the watchlist docs](watchlist.md#critical-a-ticker-that-is-not-a-rename-at-all);
what matters here is what `fetch_period()` did with it before this changed:

```python
ticker = CANON.get(symbol.upper()) or cusips.get(cusip)   # symbol wins
...
if cusip and cusip not in cusips:
    learned[cusip] = ticker                               # and is remembered
```

Symbol matching comes first, so every pre-handover `SPCX` row was attributed to
SpaceX. Then the learning step wrote the **ETF's CUSIP into `ftd_state.json` as
SPCX**, after which CUSIP matching was poisoned too — permanently, and for
every later run, including ones that never read a contaminated period.

**The live path was safe by about three weeks of luck.** `BASELINE_PERIODS` is
6, which reaches roughly 2026-05, and the ETF's last fail is 2026-04-07. An
`FTD_REPLAY` of 8 or more crosses it, and `FTD_REPLAY` is unbounded by design.

Three guards now stand in the way, and the order matters because they fail
differently:

| | Guard | Stops |
|---|---|---|
| 1 | A CUSIP in `watchlist.REFUSED` is never matched, whatever symbol it carries | The rows, and the learning |
| 2 | A symbol matches only *after* its `symbol_handover()` date; CUSIP matching is unaffected | The rows, where the CUSIP is unrecorded |
| 3 | An unrecorded CUSIP is learned only if it shares `STEM` leading characters with one already ours; otherwise it is **reported and not learned** | Only the learning |

**Guard 3 alone is not enough, and that was measured rather than assumed.**
Removing 1 and 2 while leaving 3 in place still attributed the ETF's 31 fails
to SPCX for the 2026-03a period — it merely declined to remember the CUSIP.
Guards 1 and 2 keep the rows out; guard 3 limits the blast radius when
something new appears.

`STEM` is 4 because DGXX's genuine `25381D` → `25380B` reassignment shares
exactly four characters and must not be quarantined; HUT's `44812T` → `44812J`
shares five. **It is a reporting heuristic, not a truth test**, and ABTC is the
standing counter-example: its chain runs `00973W` → `400510` → `02462A`, three
unrelated prefixes on one continuous registrant. Those are pinned in the
roster, so guard 3 never sees them — which is the design. An identifier a human
has checked is recorded; one that merely turned up is not adopted on its own
say-so.

The asymmetry is the point, and it is the same one the roster is built on: an
unlearned CUSIP under-reports one company, visibly, in the log. A wrongly
learned one gains another security's rows, invisibly, forever.

### The roster is validated at startup

A mistyped CUSIP raises no error. It simply never matches a row, so the ticker
falls back to symbol matching and the entry does nothing for as long as it sits
there — a silent, permanent no-op. Identifiers are edited by hand immediately
after a rename, exactly when a transcription error is likely and least likely
to be noticed.

Every run calls `watchlist.validate()` and prints whatever it returns:

```
WARNING: watchlist.py — ANY: CUSIP '84841L400' fails its check digit
```

It warns rather than exits, because a bad identifier degrades to symbol
matching, which still works. See
[validation](watchlist.md#validation) for everything it covers — including the
symbol-claimed-by-two-companies check that would have caught the bug below.
2. **Symbol mapping** — `CANON = watchlist.symbol_to_ticker()`, old or pending
   symbol to canonical. This is the **inverse** of what the FINRA components
   need, and both are generated from the same `alt_symbols` list so they cannot
   disagree. Only works for renames someone has recorded.
3. **Learned CUSIPs** — every matched row's CUSIP is written to
   `ftd_state.json`, so once a ticker matches by symbol it also matches by
   CUSIP thereafter. Catches a rename mid-window without an edit, but cannot
   help a company that was never matched in the first place.

### The alias collision guard

A wrong alias is far worse than a missing one. A missing alias loses a
company's data; a wrong one **merges one company's fails into another's**, and
both the source and the destination end up misreported with no error anywhere.

Two symbols mapping to one canonical ticker within a single period has two very
different causes, and the count alone cannot tell them apart:

| | Cause | Verdict |
|---|---|---|
| One symbol's range ends **before** the other begins | A rename mid-period | Benign — merging them is correct |
| The ranges **overlap or interleave** | Two live companies merged by a bad alias | Corrupting |

CUSIP is not the discriminator either. Renames in this sector frequently arrive
alongside a reverse split, which changes the CUSIP too, so "two CUSIPs" would
condemn a perfectly good rename.

**Time is the discriminator, but test intervals, not exact dates.** The first
version of this check looked for settlement dates appearing under both symbols
and found none in a case that was obviously wrong:

```
MARA 07-01..07-13, CLSK 07-10..07-10
```

Two unrelated companies, plainly interleaved, sharing no exact date — because
MARA's five fail days happened not to include the 10th. **This dataset is
sparse.** Only days with a non-zero balance appear, so two live tickers
routinely miss each other's dates by coincidence, and exact-date intersection
produces false negatives on precisely the merge this guard exists to catch.

A rename is the strict case: one symbol's entire range ends before the other's
begins. Anything else is concurrent trading. The log reflects that:

```
note: VIP spans a rename — GREE 07-16..07-23, VIP 07-24..07-31

WARNING: CLSK matched 2 symbols, 6 shared settlement date(s):
         MARA 06-16..06-26, CLSK 06-16..06-26
  Concurrent trading means these are different
  securities. Check alt_symbols in watchlist.py.

WARNING: CLSK matched 2 symbols, ranges interleave:
         MARA 07-01..07-13, CLSK 07-10..07-10
  Concurrent trading means these are different
  securities. Check alt_symbols in watchlist.py.
```

Both warning forms were produced against real SEC files by temporarily
mis-aliasing MARA onto CLSK, which reproduces the original bug deliberately.

The warning case is real. An early version mapped `GREE` to Soluna rather than
Vulcan, on the assumption that GREE was a Soluna legacy symbol. Vulcan's fails
were attributed to Soluna, Soluna's series was inflated, and `VIP` reported a
clean sheet in every period. The two visible tells were a `Dys` count higher
than the number of settlement days in a period, and one ticker reporting zero
balance every single period — which is why the per-period absentee list prints
at all.

The note case is real too, and predictable: 2026-07b covers 16–31 July and
straddles the 24 July ticker change, so Vulcan appears under both symbols in
one file. That merges correctly and the peak is right.

A ticker flagged for same-day overlap is skipped by the reverse-split check
below, since two merged securities also produce two CUSIPs and clearing the
history would be the wrong remedy for it.

## Reverse splits break the baseline

**This dataset carries raw share counts and is not split-adjusted.** The recap
requests `adjustment=all` from its provider; there is no equivalent here.

A reverse split inside the baseline window divides every subsequent peak by the
split ratio. A 1-for-10 leaves the trailing median ten times too high, so every
later reading lands near `0.1x` — a permanent, silent understatement that looks
exactly like a stock that has gone quiet. Nothing else in the output hints at
it.

Most of this watchlist is exposed. CUSIP characters 7-8 are the issue number,
which increments on corporate actions, and as of the first live run ANY sits at
`50`, BGDE at `40`, and BKKT, SLNH and VIP at `30`. Only CLSK, DGXX, MARA and
NUAI are still on their original issue.

The split announces itself in the data: **the CUSIP changes too.** The script
tracks every CUSIP each ticker appears under across the run and warns when
there is more than one:

```
WARNING: MARA appears under 2 CUSIPs: 565788106, 565788205
```

The fix is to delete that ticker's entries from `ftd_state.json` so the
baseline restarts after the split rather than spanning it. The ticker will show
`~` until it has rebuilt `MIN_FLAG_PERIODS` of history — correct, since it
genuinely has no comparable history.

Do not rescale the old peaks by the split ratio. That ratio is not in this
dataset, and a wrong guess produces a plausible number rather than an obvious
error.

## xMed is a property of the window, not the ticker

`BASELINE_PERIODS` is 6, so `xMed` divides by the median of up to five prior
periods — roughly three months. That choice materially changes the output, and
the first live period is the evidence. Same file, same peaks, baseline widened
from 6 periods to 12:

| | 6 periods | 12 periods |
|---|---|---|
| NUAI | **27.0x** | 4.3x |
| DGXX | 0.4x | **3.4x** |
| SLNH | 0.5x | 1.4x |
| WYFI | 5.8x | 6.3x |

NUAI falls sixfold; DGXX crosses the flag threshold from below. Both readings
are correct — NUAI genuinely is 27x its last three months and 4.3x its last
six. Neither is the "true" number.

The footer therefore names the window on every post. Without it the ratio reads
as a fact about the company rather than a comparison against a specific span.

**Six was kept deliberately**, for two reasons. A three-month window answers the
more useful question for a twice-monthly signal — is this period out of line
with the recent norm — and, more importantly, a longer window is more likely to
span a corporate action. ANY's reverse split sits between the 6-period and
12-period windows: at 6 its baseline is clean, at 12 it is contaminated and
would need clearing. Length is not free.

When a number looks surprising, `FTD_REPLAY=12` shows the longer view without
touching state. Treat a large gap between the two as information about the
baseline, not about the company.

## Cold start

With no `ftd_state.json`, the first run downloads `BASELINE_PERIODS` (6, i.e.
three months) of files to build the median, then posts the newest. Later runs
download one file. The step timeout is sized for the cold start, not the steady
state.

Unlike the press monitor, the first run **does** post. There is no flood risk
here: one period is one post.

## Known quirks

- **Thin history reports as thin.** A median over two points is not a
  baseline, so `MIN_FLAG_PERIODS` stops recent listings flagging on their
  second reading. They show `~` and are named under the table.
- **Field widths are capped, not trusted.** A ratio above 99x renders as
  `>99x` and share counts roll into `B`. Without the caps an extreme reading
  would widen the table past the mobile wrap point — on precisely the day the
  table is worth reading.
- **The price column is ignored.** It is the previous day's close where
  available and a literal `.` where not, and nothing here needs it.
- **Rows are parsed defensively.** Header, trailer and any malformed line are
  skipped, and the count of unparsable rows prints when non-zero. The files
  have historically contained scanning artefacts.
- **The half-month boundary is approximate.** The SEC describes the files as
  first half and second half, but a `b` file has been observed carrying a
  settlement date of the 15th. Nothing depends on the boundary — dedupe is on
  the period identifier, not on dates — but do not assume 1-15 and 16-end when
  reading a span.
- **Absence of a period is not an error.** If the SEC is late, the run simply
  finds nothing newer and exits quietly.
- **The index lists every period back to 2004** — around 400 links. Only the
  newest `BASELINE_PERIODS` are ever downloaded; the pre-2009 quarterly
  archives use a different filename and do not match the pattern at all.
- **A ticker reporting zero in every period deserves suspicion.** For a genuinely
  illiquid name it is plausible. For anything that trades, it usually means a
  rename the symbol match is missing.
