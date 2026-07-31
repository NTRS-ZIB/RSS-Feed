[← Watchlist monitor](../README.md)

# The watchlist

`watchlist.py` is the single source of truth for which companies are tracked
and how they are identified. Every component derives its own view from it.

Adding a company is one record.

## Why it exists

The watchlist used to be defined **eight times in five incompatible shapes** —
plain ticker lists, ticker → name dicts, ticker → (CIK, name) dicts, an
IR feed map keyed by display label, and two alias maps pointing in *opposite
directions*. Adding one company meant eight edits, and the alias maps could not
be copied between files because they were inverses of each other.

That is not a hypothetical cost. Writing an alias backwards merges two
companies' data under a plausible number with no error raised anywhere — see
the `GREE → SLNH` incident in [fails to deliver](fails-to-deliver.md#the-alias-collision-guard).

## The record

```python
{
    "ticker":      "VIP",
    "name":        "Vulcan Infrastructure and Power",
    "cik":         "0001844971",
    "cusips":      ["39531G308"],
    "alt_symbols": ["GREE"],
    "ir_feed":     "https://ir.vulcanip.com/rss/news-releases.xml",
}
```

| Field | Notes |
|---|---|
| `ticker` | Current symbol. The key everything else is joined on. |
| `name` | Display name. One spelling — BKKT was previously written three ways across the repo. |
| `cik` | Permanent. Ten digits, zero-padded. What EDGAR is keyed on. |
| `cusips` | `[0]` is current; later entries are retired. See below. |
| `alt_symbols` | Former **and** pending tickers — see the scope note below. |
| `ir_feed` | `None` for companies whose newsroom renders client-side. |

### Renames on the current watchlist

Every one confirmed from data by `audit_identifiers.py`, not from a filing:

| Was | Now | Ticker changed | Notes |
|---|---|---|---|
| `GREE` Greenidge Generation | `VIP` Vulcan Infrastructure and Power | 2026-07-24 | |
| `MIGI` Mawson Infrastructure | `BGDE` Big Digital Energy | 2026-04-30 | CUSIP also changed 2025-11, separately |
| `NEHC` New Era Helium | `NUAI` New Era Energy & Digital | 2025-08-13 | |
| `DGHI` Digihost Technology | `DGXX` Digi Power X | 2025-03-18 | `DGHIZZZZ` appears for one day mid-change |

`DGHIZZZZ` is not a ticker. NSCC uses a `ZZZZ` suffix as a placeholder while a
symbol change is processing, so it occupies a single settlement day between the
old symbol and the new one. It is listed because it occurs in the data.

### `alt_symbols` is scoped, not exhaustive

It covers renames recent enough to fall inside a component's lookback window,
not every rename in a company's history. The longest routine window is 180 days
([comment letters](comment-letters.md)); everything else is three months or
less, and the two EDGAR components are pinned by CIK and immune to renames
entirely. An older rename is invisible to all of them.

EDGAR records more history than this file does. NUAI was New Era Helium until
2025-07-29 and Roth CH V Holdings before that; only the first is listed here,
as `NEHC`, because only that one has been observed in data a component reads.

**What is recorded has been measured, not assumed.** `probe_cusips.py` swept
twelve months of SEC fails files and reported every CUSIP and every symbol each
company appears under. It found two things nobody had recorded — BGDE's retired
CUSIP `57778N307` and NUAI's former ticker `NEHC` — and confirmed the rest.
Re-run it with a larger `SWEEP_PERIODS` if a replay ever needs to reach further
back than a year.

**The exception is `FTD_REPLAY`, which is unbounded.** `FTD_REPLAY=24` reads a
year back, past renames this file does not record, and an unrecognised symbol
simply fails to match — the company under-reports with no error. If a replay
reaches further back than about six months, check `formerNames` in that
company's EDGAR submissions payload before trusting the result.

## Derived views

Nothing restates the roster. Each component asks for the shape it needs:

| Accessor | Returns | Used by |
|---|---|---|
| `tickers()` | `['MARA', ...]` | short interest, short volume, volume spikes, recap, FTD |
| `names()` | `{ticker: name}` | threshold list |
| `ciks()` | `{ticker: (cik, name)}` | press monitor, earnings calendar |
| `alt_by_ticker()` | `{'VIP': ['GREE']}` | short interest, short volume, threshold list |
| `symbol_to_ticker()` | `{'GREE': 'VIP', 'MARA': 'MARA'}` | FTD |
| `cusip_pins()` | `{cusip: ticker}` | FTD |
| `ir_feeds()` | `{ticker: url}` | press monitor |

`btc_context.py` is the one component that imports none of this — bitcoin
network data has no per-company dimension.

## Critical: the two alias directions

The last two rows of that table are the same data inverted, and the reason this
file exists.

| | Needs | Because |
|---|---|---|
| FINRA components, threshold list | canonical → `[former]` | They **query by symbol** and must ask for every symbol a company has traded under. |
| Fails to deliver | former → canonical | It **filters a bulk file** and must map any symbol it encounters back to one company. |

Both are generated from the same `alt_symbols` list, so they cannot disagree.
Hand-maintaining both is what produced the `GREE → SLNH` bug: GREE was assumed
to be a Soluna legacy symbol, so Vulcan's data was attributed to Soluna,
Soluna's series was inflated, and VIP reported a clean sheet in every period.

## CUSIPs: what they survive

A CUSIP survives a **rename**. It does not survive a **reverse split**.

That is why `cusips` is a list. ANY carries two — `84841L506` current and
`84841L407` pre-split — sharing the issuer prefix `84841L`, so they are one
company either side of a corporate action rather than two issuers. The retired
one is kept because historical files still carry it, and `FTD_REPLAY` reads
those.

Two entries are **CINS** rather than CUSIP: `Q4982L109` (IREN) and `G96115103`
(WYFI). The `Q` and `G` prefixes mark non-US issuers. The same check digit
applies.

## Identifiers are added from data, not from filings

One entry in this file was added from a document rather than from observation:
BKKT's `05759B107`, taken from an 8-K12B. The twelve-month sweep never saw it,
and it is marked unconfirmed in the source.

The distinction matters because the two failure modes are not symmetric. A
missing identifier loses a company's rows and shows up as an unexplained gap.
A *wrong* identifier silently attributes another security's rows to a company
that never had them — the same class of error as a backwards alias, and just
as quiet.

So: prefer an identifier observed in the data a component actually reads. Where
one comes from a filing instead, say so next to it and verify before relying on
it.

## Validation

`validate()` returns a list of problems; `python -u watchlist.py` prints the
roster and runs it. Components call it at startup and warn rather than exit.

It checks:

- duplicate tickers
- CIKs that are not ten zero-padded digits
- CUSIP check digits — a mistyped identifier never matches anything and never
  errors, so it is a silent, permanent no-op
- the same CUSIP claimed by two companies
- **the same symbol claimed as an alternate by two companies**
- a symbol that is both a live ticker and someone else's alternate

The last two are the point. **They are undetectable when the data lives in
eight files** — the `GREE → SLNH` bug took a live run and a wrong number to
find. Here it is a startup warning.

## Adding a company

Add one record. Nothing else changes, with two things worth checking:

1. **Is its IR newsroom a real feed?** Some render client-side and cannot be
   scraped — see [press monitor](press-monitor.md#coverage). Use `None`.
2. **Run `python -u watchlist.py`** before committing. A malformed CIK or a bad
   check digit is caught there rather than in nine workflow logs.

On a **rename**, move the old symbol into `alt_symbols` and update `ticker` —
do not replace one with the other. Both directions are needed, and the old
symbol persists in historical data indefinitely.

### Run the identifier audit, and expect two passes

`audit_identifiers.py` reports every CUSIP and every symbol each company
actually appears under in SEC data. Run it after adding a company, after any
reverse split or ticker change, and before trusting a deep `FTD_REPLAY`.

**A new company usually needs two runs**, because the two lookups bootstrap
each other:

1. **First run.** The company matches on its current ticker, so its CUSIPs are
   discovered and reported as `NEW`. Former symbols are *not* found yet —
   nothing links them to the company.
2. **Add those CUSIPs, then run again.** Now a former symbol trading under a
   pinned CUSIP resolves, and any earlier ticker appears.

An established company already carries both, so one run is enough.

Also watch for the `COLLISIONS` section. A row whose symbol names one company
while its CUSIP names another means the roster is wrong somewhere, and nothing
else in the output should be trusted until that is resolved.

## What does not belong here

Anything derivable. `daily_recap.py` previously carried a ticker → Stooq symbol
map, but every value was `ticker.lower() + ".us"` — a transformation, not a
fact about the company. It now lives in `stooq_symbol()` beside the fetch that
uses it.

Anything component-specific. Thresholds, schedules, webhooks and lookback
windows stay in the component that owns them.

If one company ever needs an irregular provider symbol, *that* is when it earns
a field.
