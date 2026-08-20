[← Watchlist monitor](../README.md)

# snapshot.json

The one component that publishes a **file** rather than a Discord post.

**Its consumer is not wired yet, and that is worth stating plainly**, because
this repository asserted the opposite in nine places until 2026-08-20. The
sibling `equity-research` project is the intended reader and carries a complete
instrument for it, `Get-Snapshot`, which guards stale, future-dated and empty
files. It takes a mandatory path and **nothing supplies one**; that project has
tracked the gap as open ledger item 4.18 since 2026-08-11 and says so in its
own halt-condition list.

**Treat this as a wire format anyway.** It is committed to a public repository,
rewritten every weekday, fetchable anonymously over `raw.githubusercontent.com`
right now, and the reader on the other side is already written and tested. The
contract also travels inside the payload as a `note` field, because a doc here
is not something a consumer can see.

The two projects ARE coupled today, just not through this file: `equity-research`
imports `watchlist.py` and `press_monitor.py` from a sibling working copy on
disk. That is a live dependency and a more fragile one, since it needs both
repositories checked out at fixed paths.

Written by [`build_snapshot.py`](../build_snapshot.py), committed to the repo
root by `snapshot.yml`.

## Schedule

`0 11 * * 1-5`, so 11:00 UTC on weekdays, before the US open. It posts nothing
and writes exactly one file.

**A scheduled run on this repo is never on time.** All 30 measured were 51 to
173 minutes late; today's landed at 11:18. So the file's `generated` stamp is
the only statement of when it was built, and a consumer must read it rather
than assume 11:00. On a Monday morning the newest committed file is from
Friday, which is three days of EDGAR the consumer has not seen.

A dry run fetches normally, prints what would change, and writes nothing:

```bash
gh workflow run "Build snapshot" -f dry_run=true
```

## Critical: this is a courier, not a source

The file says **what the index holds and where to look.** The filing is the
authority. Every entry under `filings` carries an accession number and a URL
precisely so a consumer opens the document before citing it, and the top-level
`note` says so in the payload itself, because a doc in this repository is not
something the consuming project can see.

Two kinds of field, and they must never be read the same way:

| under | means | trust |
|---|---|---|
| `filings` | **FILED.** This document exists at this accession. | It is a fact, subject to opening the filing. |
| `projection` | **ESTIMATE.** Derived from this issuer's own filing lags. | It is arithmetic over history, and carries its own sample and spread. |

## The shape

```
{
  "generated": "2026-08-20T11:18:14+00:00",   ISO 8601, UTC, seconds
  "schema": 1,                                 see below
  "note": "...",                               the contract, in the payload
  "issuers": { "ABTC": { ... }, ... }          keyed by TICKER
}
```

Keyed by ticker for the consumer's convenience, but **a ticker is a display
label.** Six of this roster's issuers have renamed inside eighteen months, and
one ticker on it previously belonged to a different company: `SPCX` was a SPAC
ETF until 2026-04-07 and SpaceX from 2026-06-15. `cik` is inside every issuer
block and is the thing to join on. See [watchlist.md](watchlist.md).

An issuer block is one of two shapes:

```
{ "cik", "name", "former_names", "filing_count",
  "latest_filing_date", "filings", "projection" }     the normal case

{ "cik", "error" }                                    the fetch failed
```

**The error shape has no `projection` key at all.** That is deliberate and is
not the same as a projection that says `available: false`; see below.

## `filings`: newest of each form family

Twenty keys always present, each either `null` or the block below. An
unenumerated `NT` sibling adds a key, so read the object rather than assuming
the list:

```
{ "form": "10-K", "filed": "2026-03-27", "period": "2025-12-31",
  "accession": "0001193125-26-127278", "count": 10,
  "url": "https://www.sec.gov/Archives/edgar/data/1755953/..." }
```

`count` is how many of that family the index holds; the rest describe the
**newest** one. `null` means the issuer has none, which for `20-F` and `40-F`
on a domestic filer is the normal case rather than a gap.

Three matching rules, and each exists because of a specific failure:

- **Prefix matched**, so `8-K` covers `8-K/A`.
- **`3` and `4` are matched EXACTLY**, plus `/A`. Prefix matching there would
  swallow `40-F` and `424`.
- **`NT` is matched as a family and emitted per form.** Hand-enumerating the
  members left `NT 20-F` missing for months, which is exactly the form IREN or
  DGXX would file. A sibling nobody enumerated is emitted under its own key
  rather than dropped, and amendments fold into their parent, so `NT 10-K/A`
  counts under `NT 10-K`. Collapsing the family into one key would break a
  downstream index silently, which is why the family is matched but the members
  are published separately.

**`filing_count` is the whole index and about half of it is not the company.**
It counts every row EDGAR returns, and a company's index carries filings made
by OTHERS about it: Schedule 13D/G by holders, Forms 3/4/5 by insiders, Form
144 by sellers.

Computed from this file on 2026-08-20, so a reader can reproduce it: 14,492
filings roster-wide, of which 11,106 fall into the twenty families published
here. Of those, **5,387 are the company's own and 5,719 are other people's, so
49%.** Per issuer it runs from **CRWV at 9%** to **DGXX at 83%**, with CIFR 33%
and IREN 79% in between.

So anything built on `filing_count` as a measure of company activity is
substantially measuring its shareholders instead, and for CRWV almost entirely.
The per-form `count` fields are the way to ask a narrower question.

## `projection`: the next report, and what the estimate is worth

**Ten keys, always present, in both the available and unavailable cases.** A
consumer reading `projection["expected"]` gets `None` rather than a raised
exception on an issuer that cannot be projected.

```
{ "available": true,
  "period_end": "2026-09-30",     the period the next report will cover
  "expected": "2026-11-13",       period_end + median lag, rolled off a weekend
  "kind": "quarterly",            or "annual"
  "median_lag_days": 44,
  "spread_days": 5,               HALF the observed range of lags
  "sample": 8,                    how many lags the median covers
  "fiscal_year_end_month": 12,
  "confidence": "normal",         or "low"
  "reason": null }
```

**`spread_days` is half the range**, not the range. `2 * spread_days` recovers
the range only up to the parity bit, because the halving floors.

**`confidence` is `"low"` when any of three things hold**, and the first one
reads the RANGE rather than the published half:

| condition | |
|---|---|
| `range > 30` days | the issuer files too erratically for the date to mean much |
| `sample < 2` | too few observations to call a median a measurement |
| the lag came from the other form family | annual date, quarterly lag, or the reverse |

**It changed on 2026-08-19 and the note records that.** The range test used to
compare 30 against the halved figure, an effective threshold of 60 days, so
`confidence` disagreed with the Discord post's `~` marker about the same
issuer on the same day. CLSK and WYFI read `normal` before that date and
`low` after it, on unchanged filing history. As of 2026-08-20 the `low` set is
**BTDR, CLSK, WYFI**, and it is the same three the calendar marks `~`.

**There is no `degraded` field.** The third condition above folds into
`confidence`, so a consumer cannot distinguish "the lag came from the wrong
pool" from "this issuer is erratic" the way the Discord post's `?` marker can.
Cheap to add and nobody has asked.

## Absence is a measurement, and there are three kinds

They look similar in JSON and mean entirely different things. **None of them
means zero.**

| shape | means | what a consumer should do |
|---|---|---|
| `filings["20-F"] == null` | the issuer has never filed one | nothing; usually the normal case |
| `projection.available == false` | too little history to project from, and `reason` gives the **count against the floor**: `"1/2 quarterly and 0/2 annual filings"` | treat as a young or thin filer, not an error. It resolves on its own. |
| issuer block has `error` and **no** `projection` key | the fetch failed this run | retry, or fall back to the previous file. This one is a fault. |

The middle case is the one worth being careful about. A name in a list is an
excuse; a count is a measurement, and it tells the reader both that nothing is
wrong and roughly when it resolves. SPCX has read
`1/2 quarterly and 0/2 annual filings` since it was added.

If **every** issuer fails, the run still writes the file and then exits
non-zero, so the workflow's commit step never runs and the previous committed
file stands. The local write is discarded with the runner. Worth knowing
precisely, because "not committing a snapshot of nothing" is what the error
says and "did not write" is what it sounds like.

## `schema`, and what raises it

`schema: 1`. **Raise it when a consumer would have to alter code, not when a
value moves.**

By that rule the 2026-08-19 `confidence` change did **not** raise it: the key
set, the types and the plausible ranges were all unchanged, and only the
verdict moved. That is a deliberate reading of the rule and it has a cost,
which is that nothing in the file signals a semantic change except the `note`.
The `note` was rewritten to say so in the payload for exactly that reason.

Adding `available` and `reason` in the same release also did not raise it,
because the shape is a strict superset: every key a consumer already read is
still present.

## The rule is shared, not copied

`period_end`, `expected`, `kind`, `median_lag_days`, `sample`,
`fiscal_year_end_month` and the range behind `spread_days` all come from
[`filing_cadence.py`](../filing_cadence.py), which
[`earnings_calendar.py`](earnings.md) also imports.

Until 2026-08-19 these were two implementations and they published **different
answers about the same issuers, every day**: this file rolled three months for
an annual-only filer, accepted a single 10-Q as a cadence, and took its roll
base from the newest quarterly period rather than the newest periodic filing.
None of the three errored, and this file had no test suite at all.

What stays here is presentation: the field names above, and the halving of the
range into `spread_days`.

## Stdlib only, which is not a style preference

`build_snapshot.py` imports `urllib`, not `requests`, and `snapshot.yml` has
**no pip install step**. Importing `earnings_calendar` from here to reuse the
projection rule pulled in `requests` transitively and would have killed the
11:00 UTC run with `ModuleNotFoundError` before it read a single filing,
freezing the file on exactly the values the change was correcting.

The absent pip step is the only thing that catches such an import: `tests.yml`
installs `requests`, so CI is blind to it. Never add a third-party import to
`build_snapshot.py` or to `filing_cadence.py`.

## Known quirks

**The file is an output. Never hand-edit it.** It is rewritten and committed by
the workflow every weekday and a local edit races the next bot commit, usually
losing quietly. See [local-workflow.md](local-workflow.md).

**A reportDate is not always a period end.** EDGAR carries forms from the
periodic families whose `reportDate` is a transaction date. Across the roster
618 of 619 periodic reportDates land exactly on a calendar month end; the
exception is BTDR's SPAC-listing 20-F. `filing_cadence.covers_a_period`
excludes those from the projection, so a filing visible under `filings` may not
have contributed to `projection`. That is intentional, and the counts in
`reason` describe the filings the decision actually used.

**`expected` is rolled to a business day**, so it is never a Saturday or
Sunday. The underlying `median_lag_days` is not rolled, and
`period_end + median_lag_days` will disagree with `expected` on those rows.

**Ordering is stable.** Written with `sort_keys=True` and two-space indent, so
a diff between two days shows only what actually moved.

**`former_names` comes from EDGAR**, not from `watchlist.py`, and the two are
maintained independently. `watchlist.py` is the roster's authority on
identifiers; this field is a convenience.

## See also

- [earnings.md](earnings.md) for the projection rule, its markers and the
  reasoning behind the lag pools.
- [watchlist.md](watchlist.md) for why a ticker is not an identifier.
- [rejected.md](rejected.md#a-median-based-half-width-for-the-published-spread)
  for why `spread_days` is half the range and not a median-based half-width.
- [`probe_cadence_corpus.py`](../probe_cadence_corpus.py) to see what a change
  to the projection rule would move before shipping it.
