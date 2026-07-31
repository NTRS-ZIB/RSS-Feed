[← Watchlist monitor](../README.md)

# Reg SHO threshold list

Posts when a watchlist company is added to or removed from Nasdaq's Reg SHO
threshold list. Silent otherwise, which is almost every day.

## Schedule

`15 5 * * 2-6` — 05:15 UTC Tuesday to Saturday, which is 01:15 Eastern Monday
to Friday. Nasdaq publishes each settlement day's file before midnight Eastern,
so running after that picks up the completed file for the day just ended.
Running earlier only ever finds the previous day's.

## What a listing means

A security joins after **five consecutive settlement days** of fails-to-deliver
above 10,000 shares and at least 0.5% of shares outstanding. Appearing triggers
mandatory close-out obligations for broker-dealers.

Two things follow from that definition:

- **It is rare.** Most days no watchlist company is on it, and the component
  says nothing at all.
- **It is a persistence test, not a size test.** A single enormous fail does
  not qualify; five consecutive qualifying days does. That is precisely the
  distinction the `Dys` column in [fails to deliver](fails-to-deliver.md) is
  trying to surface, arriving here as a binary.

The same caveat as the FTD component applies and appears in every embed: a
listing reflects **settlement failures**, which are not the same thing as
short-seller pressure. Fails occur on long and short sales alike.

## Critical: Nasdaq's list, not FINRA's

Each SRO publishes its own list covering the securities for which it is the
primary market. It is tempting to reach for FINRA's `thresholdList` dataset,
since the two other FINRA components already prove out that API.

**That would never fire.** FINRA Rule 4320 defines threshold securities as
those of issuers that are **not** SEC reporting securities — it is the OTC
list. Every company on this watchlist is a Nasdaq-listed reporting issuer, so a
FINRA-based version would run indefinitely and report nothing, indistinguishable
from a genuinely quiet list.

Cboe and NYSE publish their own lists for their own listings. If a watchlist
company ever moves to NYSE, this component stops seeing it and stays silent —
another failure that looks exactly like good news.

## Source

```
https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{yyyymmdd}.txt
```

Pipe-delimited, no authentication, one file per settlement day:

```
Symbol|Security Name|Market Category|Threshold Flag|Rule 3210|Filler
```

Only rows whose Threshold Flag is `Y` count. The trailing `Filler` field means
every row ends with a pipe, so a naive field count is off by one.

**This is a plain web host, not an API.** Requests carry browser-like headers
for the same reason the press monitor's IR fetches do.

### HTTP 200 does not mean the file exists

For a date that has not published yet, Nasdaq serves a **placeholder page with
status 200** rather than a 404. Trusting the status code would parse an HTML
page as a threshold file, find no watchlist symbols, and conclude that everyone
had just dropped off the list — a false "removed" post.

`fetch_file()` therefore validates that the first line contains `Symbol` before
accepting the body. This is the same failure shape as the Stooq quota response
documented under [the recap](recap.md#data-sources--and-why): a provider
returning plausible content with a success status is more dangerous than one
that fails outright.

Weekends and holidays return a genuine 404, which is expected and silent.
`MAX_DAYS_BACK` (6) walks back far enough to clear a long weekend plus a
holiday.

## Output

The monospace block carries status and ticker only:

```
ADDED    BGDE
on list  MARA  day 12
REMOVED  VIP
```

Company names and market tier go in the embed description as prose, where
wrapping is harmless. They do not fit in a 28-character block — an earlier
version appended the market category and reached 36 characters, which would
have wrapped on mobile on the one day the component ever speaks.

`day N` counts consecutive published files listing that security, ending at the
current one. A missing file is a weekend or holiday, not a break in the run.
Counting costs one request per prior file, so it runs only when something has
changed, bounded by `RUN_LOOKBACK_FILES` (15).

Embed colour: red on an addition, green on a removal, amber otherwise.

## Silence must be provable

The normal output is nothing at all, which means a broken parse and a quiet day
look identical — and a layout change would fail that way silently and forever.

Every run therefore states the **file-wide** count, not just watchlist hits:

```
Settlement date 2026-07-30 — 412 securities flagged in the file (e.g. AACG, ABVC, ACON, ADTX)
```

A plausible total is proof the file was fetched, the header check passed, and
the pipe layout parsed. Zero flagged securities in an otherwise valid file
exits with an error rather than reporting a quiet day.

The sample symbols are also the easiest way to exercise the full add path: drop
one into `TICKERS` temporarily and the next run will produce a real addition
embed. Remove it afterwards.

## State and silence

`threshold_state.json` holds the set of watchlist companies on the list as of
the last check. A post fires only on a difference — an addition or a removal.

**If that file never persists, the component breaks in a way nothing reports.**
An empty state and an empty list both render as `previously: none`, so a run
looks identical either way — right up until a watchlist company lands on the
list, at which point `previous` is empty on every run and an addition posts
every single morning. The log therefore says explicitly when there is no state
file, and again when one is written:

```
previously: none  (no threshold_state.json — first run)
State written: threshold_state.json (on_list empty, last_date 2026-07-30)
```

Seeing the second line once, followed by a commit from the workflow, is the
confirmation that the diff has something to diff against.

**Silence is the normal output and means the check ran.** The log always names
the settlement date it read and what it found, so a run that posts nothing is
still distinguishable from a run that failed.

## Aliases

Shared with [short interest](short-interest.md#aliases) and
[short volume](regsho-volume.md#aliases), and in the same direction: canonical
ticker mapped to a list of former or pending symbols.

```python
TICKERS = watchlist.names()            # values used on removal lines
ALIASES = watchlist.alt_by_ticker()
```

The list is published per settlement day under the symbol in force that day, so
a rename splits history exactly as it does for the FINRA components.

[Fails to deliver](fails-to-deliver.md) needs the *opposite* direction — old
symbol to canonical — because it filters a bulk file rather than querying by
symbol. Both are generated from the same `alt_symbols` list in
[`watchlist.py`](watchlist.md#critical-the-two-alias-directions), so neither
can be written backwards.

## Known quirks

- **A false removal is the dangerous failure.** Anything that makes the parse
  return no watchlist symbols — a layout change, a placeholder page, a rename
  not in `ALIASES` — reads as "everyone dropped off" and posts a removal.
  Additions are self-evidently real; treat an unexpected removal as suspect
  until the file is checked by hand.
- **Market category is informational only.** `Q` Global Select, `G` Global,
  `S` Capital Market. It says nothing about the threshold listing itself.
- **The run count is a floor, not a total.** It stops at
  `RUN_LOOKBACK_FILES`, so a security listed longer than that reports the cap
  rather than the true figure.
