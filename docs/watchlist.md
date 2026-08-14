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
| `ir_feed` | `None` where no usable feed exists — a client-side newsroom, or a site that publishes none. See [press monitor](press-monitor.md#coverage). |

### Renames on the current watchlist

Every one confirmed from data by `audit_identifiers.py`, not from a filing:

| Was | Now | Ticker changed | Notes |
|---|---|---|---|
| `GREE` Greenidge Generation | `VIP` Vulcan Infrastructure and Power | 2026-07-24 | |
| `MIGI` Mawson Infrastructure | `BGDE` Big Digital Energy | 2026-04-30 | CUSIP also changed 2025-11, separately |
| `GRYP` Gryphon Digital Mining | `ABTC` American Bitcoin | 2025-09-03 | Third name on one registrant — `KERN` Akerna before it. New issuer prefix each time |
| `NEHC` New Era Helium | `NUAI` New Era Energy & Digital | 2025-08-13 | |
| `DGHI` Digihost Technology | `DGXX` Digi Power X | 2025-03-18 | `DGHIZZZZ` one day mid-change; CUSIP issuer prefix changed too |
| `MKTY` Mechanical Technology | `SLNH` Soluna Holdings | 2021-11-04 | Oldest on the roster; outside every lookback window |

`DGHIZZZZ` is not a ticker. NSCC uses a `ZZZZ` suffix as a placeholder while a
symbol change is processing, so it occupies a single settlement day between the
old symbol and the new one. It is listed because it occurs in the data.
`ANYZZZZ`, `MIGIZZZZ`, `HUTZZZZ` and `ABTCZZZZ` are the same marker on four
other changeovers.

**`HUTXXXX` is a different marker and means something else.** It runs
2023-12-05 to 2023-12-14 — ten days, not one — against the *retired* CUSIP
`44812T102`, whose description still reads `HUT 8 MNG CORP (CANADA)`. So `ZZZZ`
marks the transition itself while `XXXX` is the tail draining off the old line
after the successor has taken over. They are not interchangeable, and a reader
who assumes both are one-day placeholders will date the changeover wrongly.

**The `D` suffix is a third thing, and this file does not claim to know what.**
`HSSHD` (DGXX, 2021-10-28 to 2021-11-12) and `MIGID` (BGDE, 2021-08-17 to
2021-09-13) both carry their company's own pinned CUSIP and description, so
identity is not in question. Duration is: eleven and six rows over weeks,
against the single day a `ZZZZ` occupies.

The tempting reading is "an earlier symbol" — `HSSHD` does sit immediately
before `DGHI` first appears. **That reading fails on the parallel case**:
`MIGID` runs *while `MIGI` is trading*, so it cannot be a predecessor symbol.
Whatever the suffix marks, it is a settlement line rather than a listing. Both
are recorded because they occur in the data and an unrecognised symbol
under-reports a company; neither is explained, because nothing here has
explained it.

### Critical: a ticker that did not change, over a CIK that did

Every row above is a ticker change over a stable CIK. HUT is the inverse, and
it is the harder case because nothing in this file can catch it.

`0001731805` is **Hut 8 Mining Corp**, a British Columbia company that filed
6-Ks as a foreign private issuer. It is now dormant. In November 2023 it
combined with US Bitcoin Corp under a newly formed Delaware parent, **Hut 8
Corp**, which files 10-Ks under `0001964789`. That is the CIK recorded here.

**The ticker did not change.** Both entities traded as `HUT`, so there is no
former symbol to record and `alt_symbols` is empty. The mechanism this file
uses to track corporate identity does not fire, because from a symbol's point
of view nothing happened.

Pinning the old CIK fails **silently**. EDGAR returns an empty filing list for
a dormant registrant, not an error — so the press monitor and the earnings
calendar would report nothing for HUT indefinitely, and read as a company that
simply never files. That is the same failure shape as a missing identifier:
an unexplained gap rather than a raised exception.

The general rule:

| Event | CIK survives |
|---|---|
| Name change | yes |
| Ticker change | yes |
| Reverse split | yes — a CUSIP does not, but a CIK does |
| Rule 12g-3 succession (holdco reorganisation) | yes — the successor continues the registrant |
| **Combination creating a new registrant** | **no** |

The last row is the exception, and BKKT sits on the row above it: its November
2025 reorganisation was a 12g-3 succession and changed no identifier at all.
A combination that forms a genuinely new parent is a different event, and HUT
is the one on this roster that took that path.

When a company's structure changes, check the CIK against a recent **10-K or
10-Q accession**, not against the ticker. A ticker that stayed put proves
nothing.

**The data corroborates this independently.** A 120-period sweep found HUT
trading under `44812T102` until 2023-12-04 and `44812J104` from that same day,
with `HUTZZZZ` — the NSCC placeholder for a symbol change in progress —
occupying that single settlement date. The issuer prefix moves `44812T` →
`44812J`, an issuer-level reassignment rather than a new issue number, which
is what a *new registrant* looks like in CUSIP space. Compare DGXX, whose
`25381D` → `25380B` change was read the same way.

So three independent records agree — a new CIK, a new CUSIP issuer prefix, and
a changeover placeholder — while the ticker alone reports nothing happened.
`HUTZZZZ` is the only symbol-side trace of the event and is listed for that
reason.

### Critical: a ticker that is not a rename at all

HUT above is one company across two identifiers. `SPCX` is the inverse — **two
companies across one ticker** — and it is the harder of the two to see, because
every signal a rename produces, a recycled ticker produces identically.

`SPCX` belonged to a SPAC ETF issued by Collaborative Investment Series Trust
until **2026-04-07**. Space Exploration Technologies had no security of any
kind until its `8-A12B` on 2026-06-10, and IPO'd on 2026-06-12. In the SEC
fails files the two run consecutively under one symbol:

| CUSIP | Description | Seen |
|---|---|---|
| `19423L672` | `COLLABORATIVE INVT SER TR SPAC` | 2021-07-16 to 2026-04-07 |
| `84615Q103` | `SPACE EXPL TECHNOLOGIES CORP C` | 2026-06-15 onward |

Read through the three columns `audit_identifiers.py` parses — date, CUSIP,
symbol — that is **exactly** the shape of DGXX or HUT changing identifiers: one
ticker, two CUSIPs, one ending where the other begins. The audit duly proposed
`19423L672` as a retired CUSIP for SPCX.

**Nothing in this repo flagged it, and the reason is structural.** The
`COLLISIONS` check fires when a row's symbol and CUSIP resolve to *different*
companies, so it needs a pinned CUSIP to collide with. A newly added company
sits at `"cusips": []` by design — this file says so two sections down — so
there is nothing to collide with. And a new listing is precisely where a
recycled ticker is most likely, because a symbol only becomes available once
its previous holder gives it up. **The check is blind in the one case that most
needs it.**

What settled it was the **`DESCRIPTION` column**, which the audit does not
read. The files name the issuer outright.

Two things follow, and both are now mechanical rather than advisory:

1. **A proposed identifier that predates the company's own listing is suspect
   until its description is read.** Not "probably a retired CUSIP" — the
   BKKT case proves an identifier can legitimately predate the filing that
   quotes it, so age alone decides nothing. The description does.
2. **The refusal is recorded, not remembered.** `REFUSED` in `watchlist.py`
   carries the CUSIP, whose security it really is, the handover date and why.
   `audit_identifiers.py` prints it as `ref` rather than `NEW`, so the next
   reader sees a decision already taken instead of a fresh proposal. Without
   that, the roster is defended only by whoever reads the verdict most
   carefully, on every future run, forever.

`symbol_handover()` derives the date from the same record, and
`ftd_monitor.py` uses it to refuse symbol matches on rows dated at or before
it. See [fails to deliver](fails-to-deliver.md) for the three guards.

### `alt_symbols` is scoped, not exhaustive

It covers renames recent enough to fall inside a component's lookback window,
not every rename in a company's history. The longest routine window is 180 days
([comment letters](comment-letters.md)); everything else is three months or
less, and the two EDGAR components are pinned by CIK and immune to renames
entirely. An older rename is invisible to all of them.

EDGAR records more history than this file does. NUAI was New Era Helium until
2025-07-29 and Roth CH V Holdings before that; only the first is listed here,
as `NEHC`, because only that one has been observed in data a component reads.

**What is recorded has been measured, not assumed.** `audit_identifiers.py` swept
three years of SEC fails files and reported every CUSIP and every symbol each
company appears under. It found five things nobody had recorded — retired
CUSIPs for BGDE, SLNH and DGXX, and former tickers `NEHC` and `DGHI` — and
confirmed every remaining identifier. Re-run it with a larger `SWEEP_PERIODS`
if a replay ever needs to reach further back than three years.

**And a deeper sweep found more, on companies already thought settled.** The
first sweep to run **120 periods across the whole roster** — 2026-08-05, when
GLXY, APLD, BTDR, SPCX and ABTC were added — turned up four retired CUSIPs
(`84841L308` for ANY, `57778N109` and `57778N208` for BGDE, `39531G100` for
VIP) and five symbols (`MKTY`, `HSSHD`, `ANYZZZZ`, `MIGIZZZZ`, `HUTXXXX`) on
companies that had been on the roster for months. None of them was new
information about those companies; all of them were **outside the window that
had been swept**. The 120-period run of 2026-08-03 covered only WULF, HUT and
CIFR, so everyone else was still sitting on a three-year result.

That is the same lesson as the table further down, arriving from a different
direction: an identifier absent from a window has not been shown to be absent,
and *a company already on the roster is not a company already swept deeply*.

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

Every CUSIP and symbol here has been observed in SEC data by
`audit_identifiers.py`. That is a deliberate standard, and one case shows why.

BKKT's `05759B107` was originally added from an 8-K12B, described as the
pre-reorganisation identifier. A twelve-month sweep never saw it and it was
nearly deleted as unverifiable. A three-year sweep found it: in use from
2023-07-17 to 2024-04-29, retired at the 1-for-25 reverse split of 29 April
2024 — **eighteen months before the filing that quoted it.**

So the value was right and my reasoning was wrong, and the filing was quoting a
long-stale number. Neither the filing nor the inference established anything;
the sweep did.

The two failure modes are not symmetric, which is why this matters. A
missing identifier loses a company's rows and shows up as an unexplained gap.
A *wrong* identifier silently attributes another security's rows to a company
that never had them — the same class of error as a backwards alias, and just
as quiet.

**Prefer an identifier observed in data a component actually reads.** Where one
comes from a filing, treat it as a lead to verify rather than a fact to record.

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

## What belongs on the roster

**There is no test, and this section exists to say so rather than to leave the
question looking answered.** Membership is a judgement, made case by case. Ask
before adding, and expect the answer to be about the specific company rather
than about a category it falls into.

That is a real position, not an omission. Every candidate rule that was
considered fails against the roster as it stands, and the failure is always
the same shape: a rule tight enough to be useful excludes something already
here, and a rule loose enough to admit everything here admits far more.

### The composition, 2026-08-13

Twenty-one companies. The grouping below is one reader's, offered so the shape
is visible — it is **not** a taxonomy anything in the code uses:

| | |
|---|---|
| Bitcoin miners | ABTC, ANY, BGDE, BTDR, CIFR, CLSK, CORZ, DGXX, HUT, IREN, MARA, RIOT, WULF |
| Power or energy alongside digital | NUAI, SLNH, VIP |
| Datacentre and HPC, no mining heritage | APLD, WYFI |
| Crypto financial infrastructure | BKKT, GLXY |
| Space and satellite | SPCX |

**`SPCX` is the case that defeats every tidy rule.** SpaceX is on a roster
described in the README as "digital infrastructure and bitcoin mining", and its
entry runs to forty lines about identifiers without a word on why it is here.
Any criterion narrow enough to exclude, say, an AI-datacentre operator also
excludes SpaceX — and an AI-datacentre operator is a closer fit to the stated
description than a launch company is.

### Do not reverse-engineer a rule from the list

This is the failure this section is written to prevent, and it is the one a
careful reader is most likely to commit: reading the composition above,
inferring the criterion that best fits it, and then applying that criterion
confidently to the next candidate. The composition does not imply a rule. It is
the record of a series of decisions, several of which would have gone the other
way on a different day, and **an inferred rule would be this file's own
`inferred` basis tag** — a reading presented with more confidence than its
derivation supports.

If a rule is ever wanted, it should be written down first and the roster
reconciled against it, not extracted from the roster afterwards.

### What can be required instead

A criterion is a judgement; the work below is not, and applies to every
addition however the judgement goes:

- **Identifiers come from data a component reads.** CIK from EDGAR, CUSIP from
  the SEC fails files with its `DESCRIPTION` column read. `probe_candidates.py`
  does both and validates its own instrument against the existing roster.
- **The feed is measured, never assumed.** Every `None` in `watchlist.py` is a
  measured absence. And a company can have two live feeds where one is a
  marketing blog: CORZ's site-wide feed was seventeen months stale while its
  investor newsroom was three days old, and both answered 200.
- **A dry run confirms the backlog is suppressed.** RIOT arrived with 17 items
  and CORZ with 27, all recorded as seen rather than posted.
- **Every addition costs a row.** Monospace blocks are capped at 28 characters
  and the ceiling has no slack; one more company is one more line in every
  table that lists them.

### What is known about the calls already made

- **RIOT and CORZ, 2026-08-13.** Both unambiguous by any reading — a top-tier
  US miner and the archetype of the miner-to-HPC pivot. RIOT's absence until
  then had no recorded reason and is more likely to have been an oversight than
  a decision.
- **CRWV was considered and not added** on the same day, precisely because the
  question it raises is this one. It is resolved and identifier-swept, so it
  can be added in twenty minutes whenever the judgement is made.
- **BITF was rejected** on evidence: its ticker does not resolve in EDGAR's
  index, against a control showing all existing roster tickers do.

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

#### A new company sits with `"cusips": []` until the sweep returns

That is the intended state, not an omission. `validate()` will report:

```
WULF: no CUSIP
HUT: no CUSIP
CIFR: no CUSIP
```

**That warning is correct and should be left alone.** It means an identifier has
not been established yet — which is a true statement about what this repo
knows. Components warn rather than exit, and all seven derived views handle an
empty list, so a pending company is carried safely: `cusip_pins()` simply has
no entry for it, and the FTD component under-reports that one name until the
sweep fills it in.

**It is not a licence to copy a CUSIP out of a filing.** That is exactly the
move the [BKKT case](#identifiers-are-added-from-data-not-from-filings) argues
against, and the failure it invites is the asymmetric one: a wrong identifier
attributes another security's rows to this company, quietly and permanently.
An empty list loses rows visibly. A wrong one gains rows invisibly. Wait for
the sweep.

**But know what the empty list costs while you wait.** It disables the
`COLLISIONS` check for that company — the check needs a pinned CUSIP to
collide with, and there isn't one. So the first sweep after adding a company
is the one run where the roster's own cross-check is switched off, on the
company most likely to need it. Read the descriptions on that pass; see
[the SPCX case](#critical-a-ticker-that-is-not-a-rename-at-all).

**WULF, HUT and CIFR were added on 2026-08-03 in this state**, and both
sweeps that cleared them ran the same day. The pair is worth reading together,
because the shallower one was confidently wrong.

A **48-period** sweep (2024-07 onward) found exactly one CUSIP per company,
each unbroken across the whole window. Read alone, that says three companies
with stable single identifiers.

A **120-period** sweep (2021-07 onward) said something different:

| | 48 periods | 120 periods |
|---|---|---|
| WULF | `88080T104` throughout | `88080T104` from **2021-12-16** — starts at the IKONICS merger |
| CIFR | `17253J106` throughout | `17253J106` from **2021-08-30** — starts days after the GWAC combination |
| HUT | `44812J104` throughout | **`44812T102` until 2023-12-04**, then `44812J104` |

**The 48-period sweep missed a retired identifier entirely.** Not ambiguously —
it showed an unbroken series that was not unbroken. HUT's earlier CUSIP ended
seven months before that window opened.

This is the BKKT lesson a second time. There, a 12-month sweep saw nothing and
a 36-month sweep found `05759B107` in continuous use. Here a 24-month sweep saw
nothing and a 60-month sweep found `44812T102`. **An identifier absent from a
window has not been shown to be absent — only unswept.** Match the depth to
the company's history, not to habit.

For WULF and CIFR the deeper sweep converts an unexamined absence into a
measured one: nothing trades under either company before its combination date,
so there is no retired identifier to carry, and `IKNX` and `GWAC` were never
seen against them at a depth that reached both events.

Also watch for the `COLLISIONS` section. A row whose symbol names one company
while its CUSIP names another means the roster is wrong somewhere, and nothing
else in the output should be trusted until that is resolved.

## Grid operators and sites

A sweep read the most recent annual report of every company on the roster for
the grid operators and the states each one actually names. It lives here rather
than in `watchlist.py` on purpose: no component reads site data, and a field
nothing reads goes stale with nothing to notice. This is reference for deciding
what to build, not input to anything running.

### The basis tags

**The basis column is the point**, and it used to carry two values — *stated* and
*inferred* — with *inferred* doing far too much work. It covered a filing that
names states but no operator, a reading taken off keyword frequency, and a
reading that contradicts the company's own dateline. Those are three different
things and only one of them is a guess.

The tags below are the equity-research repo's convention. **Three of its six
earn a place here; the other three are deliberately not imported**, because a
tag that never appears is a taxonomy being cargo-culted rather than adopted.

| Tag | Means | Sole basis for a claim? |
|---|---|---|
| `FILED` | the annual report says it plainly, in prose or a labelled table | yes |
| `ESTIMATE` | derived rather than read — **the derivation is shown in the cell**, so the arithmetic can be disagreed with | yes, marked |
| `OPEN` | unresolved. The filing was read and does not answer this | never — it is the absence of a claim |

**Dropped, and why:** `MARKET` — nothing here comes from price or trading data.
`PRESS` and `SOCIAL` — nothing here rests on a release or a post, and by the
convention's own rule neither could be a sole basis anyway. `PRESS` is the one
most likely to be needed first: sites now arrive by press release well before
the 10-K, so the next row added may well need it.

**One tag is local and is not from the six:** `UNSWEPT`. See below for why
`OPEN` is wrong for that case.

**`UNSWEPT` resolves by doing the work, not by waiting for anything.** It clears
when someone reads that company's annual report — the same sweep that produced
every other row in the table, and nothing more than that. **The five rows
carrying it were added to the roster on 2026-08-05.** That date is recorded
because the tag alone cannot distinguish *added last week and pending* from
*nobody has got round to it in a year*, and those warrant different responses:
the first is the roster working normally, the second is the table quietly
decaying.

**Tags attach to a claim, not to a row.** Where a company's sites and its grid
sit at different levels — and MARA is exactly that case — the cell carries both.
That separation is the whole reason for the change.

| | Grid | Where | Basis |
|---|---|---|---|
| VIP | NYISO | New York | `FILED` — and it **sells** |
| IREN | ERCOT | Texas: Childress, Sweetwater | `FILED`; expects to participate in the ERCOT wholesale spot market |
| BGDE | PJM | Pennsylvania, Ohio | `FILED`: "all strategically located in locations served by the PJM Energy Market" |
| DGXX | NYISO | New York, two sites; Alabama | `FILED` |
| WYFI | none — Duke Energy Carolinas | North Carolina, Greensboro | `FILED`; a capacity agreement, not a market |
| CLSK | none — Georgia Power | Georgia, Wyoming, Mississippi, Tennessee | `FILED`; an electrical services agreement |
| WULF | NYISO; SPP | New York: Lake Mariner (Barker), Cayuga; Texas: Abernathy | `FILED`: Lake Mariner sits "within the single-state NYISO market", on NYISO Zone A |
| HUT | ERCOT; AESO; NYISO | Texas: Vega, Salt Creek, King Mountain; Alberta: Medicine Hat, Drumheller; New York: Niagara Falls | `FILED`, in a labelled asset table with each site's grid footnoted |
| CIFR | ERCOT; PJM from 2027 | Texas: Barber Lake, Black Pearl, Stingray, Reveille; Ohio: Ulysses | `FILED`: "agreements necessary to participate in the ERCOT market" |
| BKKT | n/a | New York | `FILED` — the 10-K describes a business that does not mine |
| MARA | **none named** | Texas, Nevada, Nebraska, Ohio, North Dakota | grid `OPEN` · sites `FILED` — the 10-K names five states and **no operator anywhere** |
| SLNH | ERCOT? | Texas, New York, Kentucky | grid `ESTIMATE` · sites `FILED` — ERCOT appears 19 times, **every one in a glossary definition** |
| ANY | MISO? | Iowa | `ESTIMATE` — read off hosted-capacity mentions, nothing else |
| NUAI | **none named** | New Mexico? | sites `ESTIMATE` · grid `OPEN` — New Mexico 50x against Texas 44x, which **contradicts its own Midland, Texas dateline** |
| GLXY | ERCOT | Texas: Helios campus, West Texas panhandle | `FILED`: "ERCOT has approved over 1.6 GW of gross power capacity at our Helios campus" |
| APLD | MISO? | North Dakota: Ellendale, Harwood, Jamestown; Louisiana | grid `ESTIMATE` · sites `FILED` — MISO appears **only** via the Base Electron generation partnership, never against a campus |
| BTDR | **none named** | Texas: Rockdale; Ohio: Massillon, Clarington, Niles; Tennessee: Knoxville; Washington: Pangborn; Alberta: Fox Creek; Norway, Bhutan, Ethiopia, Malaysia | grid `OPEN` · sites `FILED` — a labelled capacity table, and **no US operator named**; so is MARA's 10-K, see below |
| ABTC | n/a — hosted at HUT's sites | Hut 8's Alpha (Niagara Falls NY), Medicine Hat (AB), Salt Creek (Orla TX), Vega (Amarillo TX) | sites `FILED` · grid `OPEN` — **owns and leases no real property.** Do not assign it grids; see below |
| SPCX | — | — | `UNSWEPT` — **nothing to read yet**, not unread. No annual report exists |

Rows are grouped by tag rather than by the order they were swept in, so the
shape is visible at a glance: **eleven `FILED`, four `ESTIMATE`, three rows
whose grid is `OPEN` with sites `FILED`, one `UNSWEPT`.**

WULF, HUT and CIFR were swept separately, on 2026-08-03, having been added to
the roster after the first sweep ran. All three name their operators outright,
so all three are `FILED`. GLXY, APLD, BTDR, SPCX and ABTC were swept on
2026-08-06 by [`probe_sites.py`](../probe_sites.py), two days after being added.

#### Critical: two Texas Panhandle sites, two different grids

This is the strongest statement of *state is not grid* the table can make,
because **both cases now sit in it**:

| | Site | Panhandle | Grid, per its own annual report |
|---|---|---|---|
| WULF | Abernathy | yes | **SPP** |
| GLXY | Helios | yes | **ERCOT** |

Neither the state nor the region determines the operator. Anyone tempted to
infer a grid from a location has a counter-example two rows away, and the
inference is wrong for one of the two whichever way it is made.

#### `UNSWEPT` now means two different things, and SPCX has the second

SPCX has **no annual report on file at all** — Form D, Form 3, 8-K, FWP,
CORRESP and UPLOAD, and nothing else. Its first 10-K is due around February
2027.

So it cannot be swept by this method, and that is not the same state as the
other four were in. Both read `UNSWEPT`, but:

| | Means | Resolves |
|---|---|---|
| GLXY, APLD, BTDR, ABTC — until 2026-08-06 | the filing exists and nobody has read it | by doing the work |
| SPCX | there is nothing to read | on a known date |

The second needs no chasing and no reminder. Recording only the tag would have
left someone re-checking a company whose answer cannot exist yet.

#### Critical: ABTC owns nothing, and assigning it grids would double-count

ABTC is a category this table has not had before. Its Item 2 Properties, in
full substance:

> "We do not own or lease any real property for our corporate offices. We
> currently operate out of facilities provided by Hut 8... We use Hut 8's
> facilities for our Bitcoin mining operations pursuant to a MCSA... Pursuant to
> an Exclusivity Agreement, Hut 8 is the exclusive provider of hosting and
> colocation services."

Its miners run at four Hut 8 sites, and **HUT is on this roster**. Alpha is
Niagara Falls; Medicine Hat is Alberta; Salt Creek and Vega are Texas — the same
physical facilities already counted in HUT's row.

**Do not "complete" this row by giving ABTC NYISO, AESO and ERCOT.** That is the
tempting edit, it looks like filling a gap, and it would count Hut 8's
facilities twice in every count taken off this table — including the grid tally
below, which is what a region decision rests on. The row is not incomplete. A
company whose entire footprint is another roster company's footprint has no
grid exposure of its own to record.

The filing names no operator in any case, so the grid claim is `OPEN` on the
ordinary evidence standard as well.

#### ABTC's 10-K is its own, not Gryphon's

Worth recording because the opposite was the reasonable expectation. ABTC went
public by reverse merger in September 2025, and the CIK carries the chain MTech
→ Akerna → Gryphon Digital Mining → American Bitcoin. A predecessor's annual
report sitting as the most recent one on a successor's CIK is a real hazard, and
its properties would be the predecessor's.

It is not this case. The 10-K filed 2026-03-27 for FY2025 is `American Bitcoin
Corp.`, audited by KPMG, describing the Mergers and "Historical ABTC". Checked
before its properties were read, which is the order that matters.

#### MARA is `OPEN`, not `ESTIMATE`, and the distinction is the point

MARA's 10-K names five states plainly and names **no grid operator at all**.
Nothing was derived, so there is nothing to call an estimate; the question was
asked of the filing and the filing does not answer it.

That is a slightly wider reading of `OPEN` than the research repo's *expected
but unconfirmed, nothing filed either way* — here something **was** filed, it
just does not reach the question. The reading that carries across is the part
that matters: **`OPEN` marks the absence of a claim, and an absence must never
be quoted as a weak version of one.** Under the old column MARA read `inferred`
alongside NUAI, which said MARA had been guessed at when in fact it had been
looked up and found silent.

`OPEN` also correctly refuses to be a sole basis. `grid_context.py` cannot place
MARA on a grid from this table, and that is the honest state rather than a gap
to be filled with the most likely answer.

#### `UNSWEPT` is not `OPEN`, and adding a seventh tag is the smaller error

GLXY, APLD, BTDR, SPCX and ABTC were added on 2026-08-05 and **their annual
reports have not been read**. Tagging them `OPEN` would assert that a filing was
consulted and did not answer — a measurement nobody made.

That is this repo's oldest rule in a new place: a window that found nothing has
shown only that it did not sweep far enough, and **an unswept absence is not a
measured one**. The same distinction separates BKKT's `FILED` "not a miner"
from these five: one was established, the others were never looked at. Two of
the five may well end up with empty rows rather than merely unfilled ones —
that has not been established either.

So `UNSWEPT` is local to this table and is flagged as such rather than passed
off as part of the imported six.

#### Why the excerpts are read rather than the counts

Two of the WULF, HUT and CIFR rows contradict what a state name would have
implied — which is why an `ESTIMATE` built on frequency alone is marked as one:

- **WULF's Texas site is not on ERCOT.** Abernathy is in the Panhandle and the
  10-K places it in the Southwest Power Pool. Texas is not a synonym for ERCOT.
- **CIFR's New York count is an office**, not a site. Item 2 lists leased office
  space in New York, Charleston and Denver; every data centre it describes is in
  Texas or Ohio.

HUT's single `Duke Energy` hit is a third instance: it appears in a list of the
companies its executives previously worked at, not as a power supplier.

**NUAI's row is still the one to distrust most, and the tag is meant to keep it
that way.** New Mexico outranking Texas 50 to 44 contradicts the Midland, Texas
dateline that put ERCOT into `grid_context.py` in the first place, and nothing
has been done to resolve which is right. `ESTIMATE` is not a softer word for
*stated* — it is a claim carrying its own derivation so the derivation can be
attacked, and this one has a contradiction sitting inside it.

Four rows carry `ESTIMATE` — SLNH, ANY, NUAI and APLD. **None should be quoted
as though a filing said it.** MARA is deliberately not among them: it is `OPEN`,
which is a different and more honest failure.

APLD is the newest and its derivation is this: MISO is named three times and
every one attaches to the Base Electron partnership — an independent power
producer developing 1.2 GW of front-of-the-meter generation "anticipated to
expand power and capacity supplied to the grid and utility customers in the
MISO region". That places a related party's generation project in MISO. It does
not place Polaris Forge on MISO, and no utility is named anywhere: Otter Tail 0,
Basin Electric 0, Montana-Dakota 0. Same shape as SLNH — the operator is in the
document, just not about the company's own load.

#### A count floor and a count ceiling are both wrong

Worth recording together, because either alone teaches half the lesson: **a
mention count is not evidence in either direction.**

| | Count | What it was worth |
|---|---|---|
| SLNH, ERCOT | **19** | nothing — every one a glossary definition |
| APLD, Louisiana | **1** | the whole answer — an owned data centre |

APLD's business section only ever calls Delta Forge "a strategic southern U.S.
market". The state appears exactly once, in Item 2: "We own our Polaris Forge
and Delta Forge data centers... located in North Dakota and Louisiana."
Meanwhile its Texas count is 27 and every one is a Dallas office or an Irving
warehouse.

A high count cannot be trusted and a low count cannot be dismissed. **The count
says where to look; the excerpt says what is there.**

#### The state to ignore is derived, not listed

This rule used to read *ignore Delaware and California — incorporation and
counsel addresses*. A fixed list, and it failed on the fifth company swept:
**APLD is Nevada-incorporated, and Nevada is its top state at 39 mentions** —
the cover page, the Nevada Revised Statutes, its control share law, and not one
of them a site.

The rule is now derived per filing: **exclude the jurisdiction the cover page
names as the state of incorporation.** `probe_sites.py` reads it out of the
"(State or other jurisdiction of incorporation or organization)" line rather
than carrying a list.

Same shape as `"NT "` replacing four hand-enumerated late-filing forms in
`press_monitor.py`. A list of the cases seen so far is an assumption that no
further case exists, and here the further case was two companies away rather
than years. For BTDR the derivation finds nothing and excludes nothing, which
is the correct answer rather than a fallback: there is no US incorporation
state to discount.

**Not because a 20-F has no such line.** This said so until 2026-08-08 and it
was wrong — BTDR's cover page carries "(Jurisdiction of incorporation or
organization)", verified by `filer_regime.py`. The pattern requires "State or
other jurisdiction", the 10-K wording, so it misses on phrasing rather than on
absence. The outcome is unchanged and the distinction still matters: relaxing
the pattern would make the derivation return "Cayman Islands", which is not a
US state and not a site anyone would confuse for one — so it would be a bug
dressed as a generalisation, and the current miss is load-bearing.

It is the second thing this repo assumed a 20-F lacked and measured as
present; the other is BTDR's operational detail, in the footprint table below.
**Both were reasoned from the form type rather than read off the filing**, and
that is the pattern rather than either instance.

Counsel and auditor cities do not generalise the same way and are still read
rather than filtered. ABTC's single Illinois mention is a former auditor's Deer
Park address; most of its five New York mentions are KPMG's signature block.

### How many companies sit on each grid

Counted from the table above, so a region choice can be made against the roster
rather than against habit. A company appears under every grid its filing names.

**Over the eighteen swept companies** — SPCX has no annual report and
contributes to nothing here. **ABTC contributes to nothing either, and that is a
decision rather than an omission:** its four sites are HUT's, already counted in
HUT's row, so adding it would count the same facilities twice.

**So the denominator is a judgement, not a count, and re-deriving it from the
roster will not reproduce it.** Nineteen companies, eighteen swept, and the
eighteenth excluded on a reading of what ABTC's footprint *is* rather than on
whether it was read. Anyone recomputing these tallies from the table's nineteen
rows will get different numbers and reasonably conclude the tally is stale. It
is not — it is answering "how many companies have grid exposure here" rather
than "how many rows are there", and those differ by exactly one.

| Grid | `FILED` | Also claimed, unverified |
|---|---|---|
| NYISO | VIP, DGXX, WULF, HUT — **4** | SLNH has a New York site, grid unnamed |
| ERCOT | IREN, CIFR, HUT, **GLXY** — **4** | SLNH, NUAI, MARA's Texas sites, BTDR's Rockdale |
| PJM | BGDE — **1** operating | CIFR's Ulysses energizes Q4 2027; MARA has Ohio sites; **BTDR has three Ohio sites, ~991 MW** |
| SPP | WULF — **1** | |
| AESO | HUT — **1** | Alberta; outside any US data source. BTDR's Fox Creek site is also Alberta |
| MISO | none | ANY and **APLD**, both `ESTIMATE` |
| No RTO | WYFI, CLSK — **2** | vertically integrated utilities; BTDR's Pangborn is hydro-supplied |

`grid_context.py` reads **ERCOT, PJM and NYISO**. That set was chosen when the
roster was fourteen, and NYISO was added on the evidence of four `FILED`
companies.

#### The 2026-08-06 sweep does not make a case for a fourth region

The test was whether it put two or more of the five on a grid the component
does not read. It did not. **One of the five landed on a grid at all, and it
landed on ERCOT**, which is already read — moving ERCOT from three companies to
four and tying NYISO.

Nothing changed for SPP, MISO or AESO on the evidence standard the existing
three met. MISO gained a second `ESTIMATE` and still has **zero** `FILED`, and
by this table's own rule an `ESTIMATE` is a claim carrying its derivation, never
quotable as though a filing said it. Two of those are not the four `FILED`
companies NYISO cleared on. Applying the bar loosely once would make the tag
mean nothing everywhere.

**MISO is the strongest candidate for a fourth region.** APLD's estimate is
better evidenced than ANY's — ANY's was read off hosted-capacity mentions, while
APLD's comes from a named generation partnership placed in the MISO region —
and APLD's North Dakota campuses carry 1,410 MW of contracted portfolio. It is
still two estimates.

**BTDR is the highest-leverage unknown on the roster.** Its US footprint is the
largest of the five swept and among the largest anywhere here — Rockdale at 563
MW, three Ohio sites totalling ~991 MW, Knoxville at 86 MW — and its annual
report names no US operator at all, which is what MARA's and CLSK's 10-Ks also
do. Establishing its grids would plausibly move PJM from one
company to two and ERCOT from four to five, which is the single change most
likely to alter a region decision.

**Its annual report does not answer it, and that is a boundary rather than a
task.** This table takes filings. Resolving BTDR needs a source that is not
one.

**The form type is not the reason, and this said otherwise until 2026-08-08.**
The obvious inference from a 20-F is that a foreign private issuer discloses
less, and it is wrong here in both directions. Measured against domestic peers
over the same vocabulary, BTDR's 20-F runs **1,041,504 characters against
419,979 for MARA's 10-K and 570,790 for CLSK's**, and carries **more** capacity
and hashrate figures than any of them. And on the thing this table actually
wants — a named grid operator — **MARA's 10-K and CLSK's 10-K name zero, the
same as BTDR's 20-F.** Only CIFR names any.

So the finding is about the roster rather than about BTDR: **miners do not
generally name their RTO in an annual report.** The table already carried the
counter-evidence without drawing on it — the MARA row above says its 10-K
names five states and no operator.

That matters because of what the wrong reason invites. *The 20-F is why* points
a future reader at a better form type, or at the home-jurisdiction record
behind it, and neither exists to be found; SEDAR+ was probed on exactly that
reasoning and rejected — see [`rejected.md`](rejected.md). *Miners do not name
their RTO* points at interconnection queues and operator registries, which is
where the answer actually is. The tag was right and the reason was not, which
is the harder failure to notice.

**If that boundary is ever relaxed, it must be decided as a change to what this
table accepts — not as an exception for one row.** The distinction is the whole
protection. An exception is granted once, for the case that seemed to warrant
it, and leaves no rule behind; the next reader sees a row sourced from
somewhere the table does not otherwise accept and has nothing to tell them
whether that was a considered widening or a lapse.

And **BTDR is precisely the case that will make the exception tempting**, which
is the reason to say this in advance rather than when it comes up. It is the
largest unresolved footprint on the roster, it would move PJM from one company
to two, and it is the single row most likely to change a region decision.
Relaxing a standard for its most valuable case is exactly how the standard
stops meaning anything — the tag survives, and stops carrying information.

The `FILED` / `ESTIMATE` / `OPEN` tags are only worth the reading discipline
they impose. `OPEN` on BTDR is not a gap waiting to be filled by a better
source; it is the accurate statement that this table's evidence standard does
not reach the answer.

### Critical: VIP's exposure runs the opposite way

Vulcan owns and operates a **106 MW generation facility** connected to NYISO and
sells electricity into it at prevailing wholesale prices, varying its output
with demand. Its 10-K names NYISO 36 times.

So a rising power price is **revenue** for VIP and **cost** for everyone else on
this roster. Any future component that treats power price as a cost input has
VIP backwards — not approximately, but in sign. See the caveat in
[grid context](grid-context.md#the-cost-framing-has-one-exception).

### Why there is no per-company power price

The ISO price plan was closed on this table, and it is recorded so nobody
reopens it from scratch.

**Three of the fourteen have no ISO node at all.** WYFI buys from Duke Energy
Carolinas and CLSK from Georgia Power — vertically integrated Southeast
utilities outside any RTO. They pay a tariff. There is no locational marginal
price to look up, because there is no market. BKKT is the third, and simply has
no mining load to price.

Of the remainder only IREN states wholesale spot exposure, MARA spans several
grids under one ticker, and one company sells rather than buys.

The blocker is not access. PJM Data Miner 2 and the ERCOT public API both offer
free keys and both publish LMPs; the data exists. The problem is that an LMP is
priced **at a node**, so choosing one means deciding where a company draws its
power — and this table does not support that decision for most of the roster.
Two API registrations to serve three companies, while getting a fourth
backwards, is not worth it.

`grid_context.py` uses gas and grid demand instead. That is a proxy, but it is
wrong in the same direction for everybody, which a mis-chosen node would not be.

## What does not belong here

Anything derivable. `daily_recap.py` previously carried a ticker → Stooq symbol
map, but every value was `ticker.lower() + ".us"` — a transformation, not a
fact about the company. It now lives in `stooq_symbol()` beside the fetch that
uses it.

Anything component-specific. Thresholds, schedules, webhooks and lookback
windows stay in the component that owns them.

If one company ever needs an irregular provider symbol, *that* is when it earns
a field.
