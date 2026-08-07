[← Watchlist monitor](../README.md)

# Holder events

`holder_events.py` reads Schedule 13D/G and posts **events**, not a
concentration measure.

| event | trigger |
|---|---|
| **arrival** | a filer group's first filing on this company, at or above 5% |
| **change** | an amendment moving the percentage by ≥0.5 points |
| **declared exit** | a final amendment reporting 0% |
| **below 5%** | a first sighting already under the threshold |
| *silence* | a holder who stops filing — **never** reported as a departure |

Daily, weekdays 13:45 UTC, to `WEBHOOK_URL_INSIDER`. Posts only on an event.

## Why it is not a concentration measure

Anyone below 5% never files, so a sum of disclosed holders has a floor it
cannot state and invites a cross-company comparison it cannot support.

**And it never counts holders**, which is not modesty. Over 233 structured
filings, **184 distinct reporting-person names collapse to 70 filer groups**
once co-filing is taken into account — 83% of names sit inside a group. A
count would overstate by that much without a grouping rule.

An event feed needs none: **a group filing is one event with several
signatories**, and the filing carries its own signatory list.

## Filer groups are matched by co-filing, not by name

Two entities on one filing are one filer. A name-stem rule was tested and
fails in both directions:

- it merges **`BANK OF AMERICA CORP` with `BANK OF NOVA SCOTIA`**, and
  `David E. Shaw` with `David F. Craver`
- it misses **36 real groups** whose members share no word — WULF's nine span
  Beowulf, Heorot Power, Lucky Liefern, Riesling Power, Stammtisch Investments
  and Paul B. Prager personally

Signatory *overlap* rather than an exact set, so a group that gains one entity
between amendments does not read as a new arrival.

## Latency is measured, not quoted

Measured over 233 filings, 2026-08-07:

| | `dateOfEvent` | lag |
|---|---|---|
| **13D** | 77 of 77 — **100%** | median 3 days, 83% within 5, two over 45 |
| **13G** | 0 of 156 — **0%** | n/a |

**The absence is substantive, not a gap.** A 13D reports an *event* — crossing
5% with intent — so it carries the date that happened. A 13G reports a
*position as of a date* on a periodic schedule; there is no event to date, and
the schema omits the field.

```
13D  crossed 2025-06-24 · filed 2025-07-03 · 9 days
13G  filed 2025-06-04 · a 13G reports a position as of a date rather than an
     event, and files no event date — measured absent in 156 of 156
```

Neither quotes a statutory deadline. The 2024 amendments already changed those
once; a component asserting a rule goes stale when the rule changes, one
measuring the gap does not.

**The field is US-formatted.** `dateOfEvent` reads `09/03/2025` while
`filingDate` in the same payload is ISO. The first measurement pass reported
all 77 13D filings unparseable for that reason — a clean zero rather than an
error.

## The arrival caveat

A holder appearing for the first time in a short record may have arrived, or
may have held for years and filed legacy until the schema changed. Those read
identically and one is not news.

The structured era runs from **10.8 months (HUT) to 30.3 (IREN)**, and SPCX has
none at all. So an arrival states the record's length as a count against the
floor rather than a bare marker, and where the record begins on the same day it
says there is barely any record to have been absent from.

## Two schema variants, one per form family

Measured: every filing carries blocks of exactly one kind and none of the
other.

```
SCHEDULE 13D, 13D/A  ->  reportingPersons/reportingPersonInfo
SCHEDULE 13G, 13G/A  ->  coverPageHeaderReportingPersonDetails
```

A pass reading only the first found zero blocks in **156 of 233** filings and
reported an answer about two-thirds of nothing.

## Relationship to the press monitor

`press_monitor.FORM_TYPES` already posts every 13D/G to the main filings
channel. **It announces that a filing exists; this component reads it.** Same
source, different question — the relationship `regsho_volume.py` and
`short_interest.py` already have. Different channels, so the pair never reads
as a double post. The cross-reference is in both files; removing either leaves
a real gap.

## Why it cannot report a departure

Ageing a holder out was tested and refused. The gap between consecutive
filings has a **median of 92 days for holders still filing against 91 for
those gone silent** — the same distribution. No threshold separates them, and
`calibrate_staleness`'s formula applied to it yields 426 days, longer than the
structured era for most of the roster.

29 **declared** exits exist and are unambiguous. Silence is reported as
silence, or not at all.

## In the weekly digest

A `holders` contributor at cadence `event`, so `weekly_digest.mk()` refuses any
persistence claim about it — a holder position is not a daily measurement and
"filed on three of five sessions" would be meaningless. It reuses the
submissions payload the filings contributor already fetches.

## Known limits

- **Legacy `SC`-spelling filings are not read.** They predate the structured
  schema and carry no parseable holder record. The count per company is printed
  so their absence is a measurement rather than a gap.
- **The first run posts nothing** — every filing is new on a cold start. A dry
  run still shows them, because it saves no state.
