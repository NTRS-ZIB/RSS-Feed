[← Watchlist monitor](../README.md)

# Short interest

Posts consolidated short interest for the watchlist each time FINRA publishes a
new settlement period — roughly twice a month.

## Schedule

`0 22 * * 1-5` — daily on weekdays, but it **posts only when the settlement
date is newer than the last one recorded** in `shortinterest_state.json`.
FINRA's exact release time varies, so checking daily and deduping on the
settlement date is more reliable than trying to hit the publication calendar.

Expect about two posts a month and silence otherwise.

## Cadence and lag

Firms report twice monthly — mid-month and end-of-month settlement — with
positions due two business days later, and publication about eight business
days after that. The 2026-07-15 settlement, for example, published on 2026-07-27.

That two-week lag makes this **positioning context, not a signal**. It belongs
in the same mental category as the bitcoin network post: background that
explains moves rather than announcing them.

## Output

```
       Short    Chg   DTC
-------------------------
WYFI    5.8M   +44%*  1.6
IREN   93.7M   +23%*  2.3
MARA  110.3M    +3%   2.5
CLSK   78.0M    -1%   3.3
```

| Column | Meaning |
|---|---|
| `Short` | Shares held short at the settlement date |
| `Chg` | % change vs the previous settlement period |
| `DTC` | Days to cover — short interest ÷ average daily volume |

Sorted by change. A trailing `*` marks a move beyond `NOTABLE_CHANGE_PCT` (15%).

Three notes are appended to the embed when they apply, and all three are also
printed by dry runs:

- **Revised by FINRA** — the `revisionFlag` is set. A change computed against a
  revised prior figure is not quite comparable to one against an original.
- **Stock split flagged** — the `stockSplitFlag` is set. A reverse split shrinks
  the share count mechanically, so a large negative change may be an artefact
  rather than covering. Relevant here: several of these companies have done
  reverse splits.
- **Filed under a former symbol** — see Aliases below.

## Critical: dataset selection

The `otcMarket` group contains several short interest datasets and **only one
covers exchange-listed securities**:

| Dataset | Coverage |
|---|---|
| `consolidatedShortInterest` | **Correct.** All exchanges. |
| `equityShortInterest` | OTC only. Deprecated 2021-04-30. |
| `equityShortInterestStandardized` | OTC only, despite the name. |

Both `equityShortInterest*` datasets return **HTTP 200 with well-formed rows**.
They simply contain no Nasdaq-listed names. Nothing about the response says so.

The tell is a plausible-looking result whose newest settlement date is years
old. The diagnostic that cracked it: CleanSpark appeared with records stopping
dead in January 2020 — exactly when it uplisted from OTC to Nasdaq. A company
whose history ends on its uplisting date means you are querying an OTC dataset.

`STALE_WARN_DAYS` (60) exists solely to catch this. If the newest settlement is
older than that, the script exits rather than posting stale figures as current.

## Authentication

**Not required.** Confirmed 2026-08: this dataset returns full results for all
eleven companies anonymously.

OAuth2 client-credentials support is retained but unused — no secrets are set,
so `CLIENT_ID` is empty and the script queries anonymously. If FINRA ever
requires auth, add `FINRA_CLIENT_ID` and `FINRA_CLIENT_SECRET`; they are
already mapped in the workflow's `env:` block.

Credentials were tried during debugging and changed nothing, which is what
established that the earlier failures were a **content** limitation rather than
a permission one.

If you ever do set credentials, also set `CREDENTIAL_EXPIRY` to the expiry date
shown in FINRA's API Console. FINRA secrets expire, and an expired secret fails
the token exchange and falls back to *anonymous* — so if auth were ever
required, the failure would be silent. The expiry check warns 45 days ahead.

## Aliases

**This is the only component keyed by ticker rather than CIK.** FINRA files by
the symbol in force *on the settlement date*, so a rename splits a company's
history across two symbols.

This is not hypothetical. The 2026-07-15 settlement predates the GREE → VIP
change on 2026-07-24, so Vulcan is filed under `GREE` for that period and was
initially missing from the report.

`ALIASES` maps former and pending symbols back to the canonical ticker:

```python
ALIASES = {
    "VIP": ["GREE"],   # renamed from Greenidge, 2026-07-24
    "ANY": ["DRK"],    # pending change to DarkHorse Technologies
}
```

When a company renames, **add to `ALIASES` rather than editing `TICKERS`** —
keeping both preserves continuity across the changeover. Both symbols are
queried and results map to the canonical ticker, with a note in the embed
saying which was used.

Any ticker not found is named explicitly in the log and the embed. Treat that
as a maintenance alarm: it usually means a symbol change, not an outage.

## Schema discovery

Field names differ between datasets, and the symbol column in particular is
unguessable — the OTC datasets use
`securitiesInformationProcessorSymbolIdentifier` while
`consolidatedShortInterest` uses `symbolCode`.

Rather than hardcode one, `SYMBOL_FIELDS` is probed in order and the first the
API accepts is used. If none match, the script queries the `/metadata` endpoint
and prints the dataset's real field names, so a single run diagnoses any future
rename instead of needing a guessing round-trip.

## Known quirks

- **Absence is not always an error.** The dataset only carries securities with
  a reported short position for that period. A thinly shorted name can be
  legitimately missing.
- **Small absolute numbers make big percentages.** ANY showed −87% on 12.9K
  shares — a real move, but three orders of magnitude below MARA's 110M. Read
  `Short` alongside `Chg`.
- **Days to cover and average daily volume are separate columns.** Never fall
  back from one to the other; an early version did, and would have printed a
  raw volume figure in the `DTC` column.
