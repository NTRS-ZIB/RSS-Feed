# A company with no quarterly history, and the announcements we were missing

Design, 2026-08-11.

## The problem, as it appears

BTDR's row in the earnings calendar reads `BTDR? est 20 Jul  22d ago` and has
climbed by one day every day since 20 July. It cannot clear.

The projection behind it was built from nothing that describes BTDR. Its
`upcoming` period end is 31 March 2026, produced by `next_period_end()`
advancing the last period by one quarter, and the lag applied to it is 111
days, the median of its five annual 20-F filings. A quarterly period end it
never reports on, plus an annual lag. Neither half is wrong on its own; the
combination describes no company.

## What the measurement found

Dispatched 2026-08-11 against the live roster.

**BTDR is the only company of nineteen with no 10-Q.**

```
        total  10-K  10-Q  20-F  40-F   6-K   8-K
BTDR      272     0     0     5     0   102     0   NO 10-Q
IREN      312     1     3     3     0   123    29   has 10-Q
ANY       807     7    19     3     2   150   138   has 10-Q
DGXX      242     1     1     3     1   132    21   has 10-Q
```

IREN, ANY and DGXX file 6-Ks in volume as well, but they have quarterly
history, so they project from it and are unaffected by any of this.

**Projecting BTDR's quarterly results from EDGAR is not reachable.** Two
findings close it off independently:

- Every one of its 102 6-K descriptions reads exactly `REPORT OF FOREIGN
  PRIVATE ISSUER`. That is the form's title, not a description of contents.
  A results 6-K cannot be told from a financing announcement without fetching
  and reading the document.
- Every 6-K has `reportDate == filingDate`. A 6-K carries no period covered,
  and the projection method is period end plus median lag. There is no period
  end in the data to start from.

The filing indexes were checked too and carry no usable document names.

**But BTDR pre-announces, nine days ahead, with the date in the title.**

```
Sat, 01 Aug 2026   Bitdeer Announces Second Quarter 2026 Earnings Conference
                   Call for August 10th 2026
Mon, 10 Aug 2026   Bitdeer Reports Unaudited Financial Results for the Second
                   Quarter of 2026
```

`DATE_RE` already parses "August 10th 2026". The reason that announcement was
never picked up is narrower than any of the above: `ANNOUNCE_VERBS` carries
"announces date" and "announces the date" but not bare "announces", so the
title fell through as `no-match`.

That reframes the whole problem. This is not a missing capability. It is a
one-entry recognition gap, plus a projection that should never have been
attempted.

## The predicate

Everything below keys on **"has no 10-Q history"**, read from filings the
component already fetches. Not "is a foreign private issuer", which is a legal
status we would be inferring rather than observing, and which this repo's
conventions say to avoid: a wrong inference is silent, and the observable
version is free.

Today it selects exactly one company. If another arrives it is handled with no
roster edit.

## Three changes

### 1. A company with no quarterly history gets no quarterly projection

`project()` currently pools whatever it can find when the natural pool is thin,
which is how an annual lag ends up applied to a quarter end. When a company has
no 10-Q history at all, that fallback stops: it projects its **annual** cycle
only, from its 20-F/40-F history, which is a real cadence the data supports.

**The period step changes with it, and this is the part most easily missed.**
`next_period_end()` advances by three months unconditionally. An annual-only
projection must advance by twelve, or it produces the same fabricated quarter
end by a different route. For BTDR: last annual period 31 December 2025, next
31 December 2026, plus its measured annual lag of 111 days, landing around 21
April 2027 and shown under "later".

**It is also never reported overdue.** Marking something overdue asserts that
it should have arrived and has not, and this component cannot observe a 6-K
filer arriving at all. A claim we cannot check does not belong in the post.

**This is a real loss and is not being papered over.** If BTDR goes genuinely
silent for two quarters, nothing here will say so. The alternative on offer was
a row that has been wrong for 22 days and would go on being wrong, and between
a false claim and no claim the honest choice is no claim. Its releases still
reach the press channel, so silence remains visible elsewhere.

A passed *disclosed* date is deliberately not made to trigger overdue either,
tempting though it is, because the company said the date itself. The row would
go overdue on a better number and stay there permanently: the same failure,
better dressed.

### 2. Recognition gains bare "announces"

One entry in `ANNOUNCE_VERBS`. BTDR's advance notice is then recognised and its
date parses from the title unchanged.

This also makes a results release recognisable — "Galaxy Announces Second
Quarter 2026 Financial Results" now matches the verb and the results word. That
is safe for storing: such a title carries no date, so it is a `no-date` miss,
and if one ever carried a date it would be in the past and the guard rejects
it. **The two-stage design always intended the date guard to be the real
filter**, with recognition as the cheap first pass, and this widening leans on
exactly that.

### 3. The body-fetch gate narrows

Task 10 fetches the body of a recognised announcement that carried no title
date, to measure whether bodies carry usable dates. Change 2 makes results
releases recognised and undated, so without a guard their bodies would enter
that measurement — and **a results release body is dense with dates**: the
period covered, prior-year comparatives, the figures themselves. That would
poison the measurement the feature's next decision rests on.

So body fetching additionally requires a scheduling word in the title. An
advance notice names a future event; a results release does not. **The list is
pinned rather than left to judgement** — "conference call", "webcast", "call
for", "schedules", "to be held" — and it is a gate on fetching only, never on
storing, so a word missing from it costs a measurement sample and nothing else.

## Failure handling

- A company with no 10-Q and fewer than two annual filings projects nothing,
  and is named with a count against the floor, as the component already does
  for SPCX.
- The disclosed-date overlay is unchanged and continues to apply to any row,
  including an annual-only one, whenever an announcement exists.
- Nothing here fetches anything new. Change 1 and 2 are pure logic over data
  already retrieved; change 3 only narrows an existing fetch.

## Verification

- Unit tests over `project()` for the no-10-Q case: annual projection produced,
  no quarterly projection attempted, not marked overdue at any date.
- A recognition test that BTDR's real headline matches and that "Bitdeer
  Announces June 2026 Production and Operations Update" still does not.
- A body-gate test that a results-release title is recognised but not fetched.
- A dispatch of the earnings calendar with `--ref`, confirming BTDR leaves the
  Overdue section and that the other eighteen rows are unchanged. The last
  point is the one that matters: change 1 touches the path every company flows
  through.

## Out of scope

Identifying a results 6-K, and projecting BTDR's quarterly reporting. The
metadata cannot support either, and the press release arrives nine days ahead
regardless, which is earlier than any projection would have been.
