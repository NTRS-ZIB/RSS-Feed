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
| *(none)* | Projection from ≥2 same-form filings. Treat the date as real. |
| `~` | Historical spread exceeds 30 days. Indicative only; named in a footnote. |
| `?` | Had to fall back to a different form type — e.g. a foreign issuer with no 10-Q history. Weakest case. |

Expected dates falling on a weekend roll forward to Monday.

## Sections

**Expected in the next 45 days** — the actionable list.

**Past estimate** — a company more than 10 days beyond its own typical lag with
nothing filed. This corroborates the `NT 10-Q` / `NT 10-K` late-filing notices
the press monitor watches for; seeing both is a strong signal.

**Later** — one-line summary of everything beyond the horizon.

## Known quirks

- **These are estimates, not announced dates.** Companies announce actual dates
  by press release, which the [press release monitor](press-monitor.md)
already catches. This fills
  the gap before that announcement lands.
- **Recent listings have thin history.** WYFI had 4 periodic filings at time of
  writing, giving ±35d. Accurate reporting of low confidence, not a bug.
- **Validate against reality.** When a company actually files, compare to the
  projection. If established filers are consistently off by a fixed amount, an
  old restatement or late filing is likely skewing the 8-sample window — reduce
  `LAG_SAMPLE` to 4.
