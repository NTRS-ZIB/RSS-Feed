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

**Absence is reported, not hidden.** The SEC only includes securities with a
non-zero balance, so a ticker missing from the file had zero net fails on every
settlement date — a real and common result. Those tickers are listed under the
table rather than silently dropped, so a broken symbol match can't masquerade
as a clean period.

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

## Ticker renames and CUSIPs

This is the only component that reads *backwards* through several months of
history, so renames genuinely bite: a period from before a rename carries the
old symbol. Two defences:

1. **`ALIASES`** maps historical and pending symbols to the canonical one, the
   same map used by the two FINRA components. Keep the three in sync.
2. **CUSIPs are learned and persisted.** The file supplies a CUSIP per row, so
   once a ticker has been matched by symbol its CUSIP goes into
   `ftd_state.json` and later rows match on either. A rename mid-window is
   picked up without an edit.

Neither is bulletproof — a reincorporation can change the CUSIP too — so the
log prints how many of the eleven tickers matched in each period. A count that
drops without an obvious reason means a rename to add to `ALIASES`.

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
- **Absence of a period is not an error.** If the SEC is late, the run simply
  finds nothing newer and exits quietly.
