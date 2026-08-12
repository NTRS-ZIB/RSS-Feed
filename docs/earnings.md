[← Watchlist monitor](../README.md)

# Earnings calendar

Projects when each company will next report, so you know what's coming rather
than only reacting to what already happened.

## Schedule

`30 12 * * 1` — Mondays 12:30 UTC (8:30am ET summer, 7:30am winter), ahead of
the week's first open.

## Method

No external data provider. SEC's submissions API
(`data.sec.gov/submissions/CIK##########.json`) returns every filing with both
the period it covers (`reportDate`) and the date it was filed (`filingDate`).
The gap between them is stable per company, so:

```
expected = next period end + that company's median lag
```

The lag is the median of its last 8 periodic filings, and the `±` shown is the
spread across those. That spread is the honesty indicator: `±0d` means
metronomic, `±35d` means don't plan around it.

## Critical: annual and quarterly lags must never be pooled

Annual reports are filed 60–90 days after fiscal year end; quarterlies around
40. Averaging them produces a median fitting neither and a spread spanning the
difference.

The first working version pooled them. Real output: MARA ±33d, BGDE ±46d,
ANY ±52d, DGXX ±215d — spreads so wide the dates were meaningless. After
separating by form type the same companies read ±14d, ±6d, ±10d.

`ANNUAL_FORMS` and `QUARTERLY_FORMS` exist for this reason. Do not merge them.

## Fiscal year ends are detected, not assumed

Several companies here are not calendar-year filers — IREN's year ends in June,
CleanSpark's in September. The script infers the fiscal year end from the most
common month among past annual reports, then decides whether the next period
end is a year end (use the annual lag) or a quarter (use the quarterly lag).

Getting this wrong produces a plausible-looking date that is 30+ days out. IREN
correctly projects an `annual` filing for its June period, not a 10-Q.

## Output markers

| Marker | Meaning |
|---|---|
| `!` | The company announced this date. Not a projection, so no spread is shown. |
| `*`/`~` on a 2027-ish date | Projected annually, because the company files fewer than two quarterly reports. It gets no quarterly estimate and is never marked overdue. Which of the two shows is decided the same way as any other row — `marker()` checks the wide-spread `~` before the annual `*`, so an annual-only company whose few samples also spread widely (BTDR, DGXX both do) renders `~`, not `*`. There is no dedicated symbol for "annual-only"; read the year, not the marker, to spot it. |
| *(none)* | Projection from ≥2 same-form filings. Treat the date as real. |
| `~` | Historical spread exceeds 30 days. Indicative only; named in a footnote. |
| `?` | Had to fall back to a different form type — e.g. a foreign issuer with no 10-Q history. Weakest case. |

Expected dates falling on a weekend roll forward to Monday.

## Sections

**Expected in the next 45 days** — the actionable list.

**Overdue** — a company past its own announced date with nothing filed, or
more than 10 days beyond its typical lag. An announced date gets no grace,
because the grace exists to allow for the spread in our projection and an
announced date has none. This corroborates the `NT 10-Q` / `NT 10-K`
late-filing notices the press monitor watches for; seeing both is a strong
signal.

**Announced** — a company-announced date that falls at or before the period
end the company's own row is projecting, rather than after it, so it describes
a different report than that row (`apply()` only overlays a date that falls
after the period end being projected — see its docstring). It is never placed
onto the row instead. The reason is measured, not stylistic: the upcoming
table's header prints a `P/E` line only when every row shares one period end,
and every row keeps its weekday only when periods don't differ. Overlaying an
announced date that belongs to a different period would make the table
mixed-period on that account alone — stripping the header's `P/E` line and
every row's weekday — and the row carrying it would print, on its own line, a
date from one period next to the period end of another: DGXX's row projects
its next annual filing, period end 2026-12-31, while the date it announced
(2026-08-14) belongs to some earlier report; shown together the row would
read as a December filing due in August, contradicting itself. Rows in this
section carry no marker and no spread column: they are neither a projection
nor the current estimate for any row, so `!`, `~`, `?` and `*` all describe
something these dates are not.

**Later** — one-line summary of everything beyond the horizon.

## Known quirks

- **Most rows are estimates; a `!` row is not.** Companies announce actual
  dates by press release, the [press release monitor](press-monitor.md) reads
  the announcement out of the release title, and `earnings_dates.json` carries
  it here. A company whose announcement puts the date in the body rather than
  the title is still an estimate; the press monitor logs a count of those.
- **Recent listings have thin history.** WYFI had 4 periodic filings at time of
  writing, giving ±35d. Accurate reporting of low confidence, not a bug.
- **Validate against reality.** When a company actually files, compare to the
  projection. If established filers are consistently off by a fixed amount, an
  old restatement or late filing is likely skewing the 8-sample window — reduce
  `LAG_SAMPLE` to 4.
- **The write path is exercised only by a live run that finds an
  announcement.** A press monitor dry run saves no state, so it logs what it
  would record and writes nothing. Until a scheduled run has actually written
  `earnings_dates.json` and pushed it, the store side of this feature has
  never executed. Do not read the surrounding work looking finished as
  evidence that it has.
- **The persist half of the workflow change has never executed either.**
  `persist_state` in `monitor.yml` copies `earnings_dates.json` aside before
  `git reset --hard`, restores it after, then commits and pushes — the same
  shape as the `state.json` handling next to it, added for the same reason.
  But every run since it landed has been a dry dispatch, which saves no state
  and returns before `persist_state` is ever called. Only the refresh half,
  which reads `earnings_dates.json` from origin if present, has actually run —
  it logged `No earnings_dates.json on origin yet.`, because no live run has
  written one. The push side of that function is reasoned about, not
  observed.
- **A company below the quarterly filing floor is never reported overdue, and
  that is deliberate.** Marking something overdue claims it should have
  arrived and has not. For a company that reports interim results on a 6-K,
  this component cannot see it arrive at all: a 6-K is not in `PERIODIC_FORMS`
  and carries no period covered, since `reportDate` equals `filingDate` on
  every one of them. BTDR's row read "est 20 Jul" and climbed for 22 days on
  exactly that. The cost is real — if such a company goes genuinely silent
  nothing here will say so — and it is preferred to a claim that cannot be
  checked. Its releases still reach the press channel.
- **Two branches in `main()` still have no witness.** The `status == "ok"`
  line, printed when `earnings_dates.json` loads with at least one record, and
  the split further down that tells a company on the roster with too little
  filing history to project from a CIK that carries a stored date and isn't on
  the roster at all — both only run when `earnings_dates.json` is non-empty.
  Every local test constructs that file directly; nothing has driven it
  through `main()` itself. A live press-monitor write is the only thing that
  populates it for a real run to read.

When the next scheduled press monitor run reports a non-zero `earnings dates:
N recorded`, this is the check that closes the gap — nothing before it does:

```bash
git pull
python -c "import json;print(json.load(open('earnings_dates.json'))['companies'])"
```

Expect at least one record, with `source_title` naming a release you can open
and read. Verify the date in the file against the date in that release by
eye.
