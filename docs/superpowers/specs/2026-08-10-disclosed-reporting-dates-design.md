# Showing the disclosed reporting date instead of the estimate

Design, 2026-08-10.

## The problem

`earnings_calendar.py` projects when each company will next report, from its own
EDGAR filing history: next period end plus that company's median filing lag.
The projection is good. On the 2026-08-10 run BGDE projected Friday 14 August
with a historical spread of ±6 days over 8 filings, and the company had
announced Wednesday the 12th. Two days out, well inside its own spread.

**The projection is not the problem. The problem is that it keeps being shown
after the answer is known.** Once a company announces its date, the estimate is
strictly worse information, and the post gives the reader no way to tell that a
better number exists.

Nothing in the repo closes that gap today. `earnings_calendar.py` imports
`watchlist` and `requests` and reads nothing but the SEC submissions API. It
has no input for an announced date and no knowledge that the press monitor,
which already fetches every IR release on the roster, has almost certainly seen
the announcement.

## Decisions, and what settled them

| Decision | Choice |
|---|---|
| Source of the disclosed date | The press monitor extracts it from release titles |
| Storage | Its own file, `earnings_dates.json`, written by the press monitor |
| Display | Announced date replaces the projection, marked, spread blanked |
| Guard | One hard test: the parsed date must be in the future |
| Overdue | A passed announced date goes overdue with no grace |

The guard was argued to a different answer than the one first proposed, and the
reasoning is worth keeping.

**There is no plausibility window, and no period test.** The first proposal
rejected a parsed date that fell outside the fiscal period the calendar was
projecting for. That is backwards. It lets our arithmetic veto the company's
own statement, and our arithmetic is known to be wrong: BTDR is a foreign
private issuer with no 10-Q history, `next_period_end` advances its period by
one quarter regardless, and the 2026-08-10 run projected 20 July from a 31
March period end that BTDR never reports on. A correct BTDR announcement would
have failed the period test and been discarded in favour of a date already 21
days stale. So a period mismatch now believes the announcement and logs the
disagreement, which turns it into a signal about the projection rather than a
reason to throw away good data.

A numeric window was rejected for a different reason: the constant has no
derivation. Choosing one by feel is what rule 1 exists to catch, and deriving
it honestly means first measuring announcement-to-report gaps across nineteen
companies, which is a probe standing in front of a feature that does not need
it.

**The guard is not a trust check.** We trust the company. What is not trusted
is our reading of a headline, and those are different claims. Three ways a
correct company statement becomes a wrong stored date, none of which involve
the issuer being unreliable:

- A release carries several dates. "Second Quarter 2026 Results on August 12,
  2026", a call on the 13th, and "for the quarter ended June 30, 2026" sit in
  one text, and a regex picks one of them.
- The results release itself looks like an announcement. "Reports Second
  Quarter 2026 Results" contains a date describing the period covered.
- A stale item re-reads as new. Both documented here: DGXX's feed served
  nothing newer than 2025-12-24 at HTTP 200, and a default sort that is not a
  date sort put an eight-month-old item at `rows[0]`.

The future test kills the second and third outright. Provenance handles the
first, by making a wrong extraction diagnosable instead of mysterious.

## Architecture

Three pieces, each independently understandable.

```
press_monitor.py     recognises an announcement, extracts a date, writes
        |
        v
earnings_dates.json  one record per company: date + where it came from
        |
        v
earnings_calendar.py reads, applies over its own projection, never writes
```

The extractor runs over items the press monitor has already built, so it adds
no fetching and cannot fail in a way that stops a press post. `project()` in
the calendar is untouched and stays a pure projection; a separate step applies
disclosures to its output. The two are testable apart.

## The extractor

**Recognition is two stages, deliberately.** The title must first look like an
advance notice: a "to report", "to announce", "schedules" or "announces date
of" shape combined with a results or earnings word. Only then is a date parsed
out of it. Running a date parser over every title finds dates in results
releases, financing releases and anything else carrying a quarter end.

**It reads titles only, and that is a real limit.** Announcement headlines come
in two shapes. "X to Report Second Quarter 2026 Results on August 12, 2026"
carries the date. "X Announces Date of Second Quarter 2026 Earnings Release and
Conference Call" does not, and the date is in the body. Across the four source
shapes on this roster, feeds, EDGAR, the two scrapers and the Sanity read, the
title is the only field that can be relied on to be present and clean.

**A miss is not a regression and must be counted.** A company whose
announcement is not parsed keeps the estimate it has today, which is current
behaviour. The extractor logs every title that matched an announcement shape
but carried no parsable date, and that count is what decides whether fetching
release bodies is worth building. Building it now would be guessing at a
population nobody has measured.

**The guard**: the parsed date must not be before today. The calendar's own
upcoming test is `today <= expected`, so a stricter test here would discard a
same-day announcement the calendar would display.

**Every accepted date records its provenance**: the item uid, the title, and
the release's own published timestamp.

## The store

`earnings_dates.json` at the repo root, beside `state.json` and
`snapshot.json`. It is an output file, written by the press monitor workflow
and committed the same way, and it inherits the standing rule that nobody edits
one by hand.

Shape, with an illustrative record. The CIK and ticker are BGDE's real
identifiers from `watchlist.py`; the title and uid are stand-ins for whatever
the release actually carried, not a transcription of it.

```json
{
  "schema": 1,
  "companies": {
    "0001218683": {
      "ticker": "BGDE",
      "date": "2026-08-12",
      "source_uid": "<the item uid press_monitor already assigns>",
      "source_title": "<the release title, verbatim>",
      "source_published": "2026-07-29T13:00:00Z"
    }
  }
}
```

**Keyed by CIK.** Six of nineteen companies have renamed in eighteen months and
one ticker on the roster previously belonged to a different company, so the
ticker rides along for readability and the CIK is what the calendar matches on.

**A later announcement wins, judged by the release rather than the run.** A
company that moves its date issues a second release, and the writer overwrites
only when the incoming release was published after the stored one. That
ordering is what stops an old item resurfacing in a feed from clobbering a
newer announcement.

**Nothing is pruned.** The store is keyed by CIK and `upsert` overwrites in
place, so it is bounded by the roster. Pruning a passed date would delete the
entry the Overdue section is built on.

## The calendar side

**Reading rule.** A stored date is used when it falls after the period end
being projected. A report date is always after the period it covers, so this
holds while the company has not yet reported, and keeps holding once the date
has passed, which is what puts the row in Overdue. It stops holding by itself
the moment the company files: `upcoming` moves to the next period end and the
stored date is now before it. There is no expiry to run and no constant to
choose.

**Display.** The announced date replaces the projected one. The row takes a new
marker `!`, which outranks `*`, `~` and `?`, because all three of those
describe a projection that has been superseded. The spread column goes blank
for that row rather than showing a spread that no longer describes anything;
the blank is itself the signal. The key line reads `! announced by company`, 22
characters, inside the 28-character ceiling. Row width is unchanged, since the
marker occupies a slot that already exists.

**Overdue.** A company that announced the 12th and has not filed by the 13th is
definitively late, where an estimate three days out is noise. A passed
announced date goes into the overdue section with no grace. This is not a new
constant to derive but the absence of one: `OVERDUE_GRACE` exists to allow for
the spread in our own projection, and a company's own date has no spread to
allow for.

The section is renamed from "Past estimate" to "Overdue", which stops being a
lie once a row can be past an announced date rather than past an estimate.

## Error handling

**Missing and empty are different measurements and get different log lines.**
No file at all means the press monitor has never written one, expected on the
first run and a fault later. A file with zero live entries means nothing is
currently announced. Sharing a label between those two is the failure this repo
records under "too little history yet and the source failed are different
measurements".

A malformed record is skipped and named. A CIK not on the roster is skipped and
named. Neither aborts the run: the calendar posts its projections either way.

## Verification

**The guard is validated by removing it.** A test that has never failed proves
nothing, so the future test is confirmed by taking it out and demonstrating
that a results-release title and a stale re-read both yield a date, then
putting it back. Same technique that validated the drift detector by taking
`SCHEDULE 13D` back out of `FORM_TYPES`.

**Recognition** gets positive cases from real headline shapes on this roster
and negative cases from financing and operational releases carrying quarter
ends.

**The calendar side** is driven through a fixture `earnings_dates.json` and
`build_message`, asserting three things: the announced row shows the announced
date, its spread column is blank rather than zero, and a passed announced date
lands in the overdue section with no grace applied.

**One path cannot be dry-run, and this must not be allowed to look verified.**
A press monitor dry run saves no state, so it will never write
`earnings_dates.json`. The write path can only be exercised by a live run that
actually finds an announcement. That is the shape of the push retry loop, which
sat in the repo for weeks looking finished without having executed once. The
mitigations are a unit test on the writer against a temporary path, and
watching the first live write deliberately rather than assuming it.

Dry runs are dispatched, never run locally:

```bash
gh workflow run "Earnings calendar" -f dry_run=true
```

## Docs

`docs/earnings.md` needs the new marker in its table, the renamed section, and
its known-quirks entry rewritten, since "these are estimates, not announced
dates" stops being true for some rows.

## Out of scope

**Foreign private issuers are invisible to this component, and that is not an
arithmetic bug.** BTDR reported results on 2026-08-10. A dry run dispatched
immediately afterwards showed its periodic filing count unchanged at 5, while
BKKT went from 23 to 24 and GLXY from 5 to 6 and both dropped out of the
upcoming list on the same run. `PERIODIC_FORMS` is 10-K, 20-F, 40-F and 10-Q,
and a foreign private issuer reports interim results on a 6-K, so the calendar
cannot observe BTDR reporting at all and the row cannot clear. Separately, it
derives BTDR's lag from 20-F annual filings, 111 days, and applies it to a
quarter end, which is the annual-versus-quarterly pooling `docs/earnings.md`
forbids, arriving through the degraded path rather than through a merged
constant.

The consequence is that BTDR sits under Overdue until its next 20-F whatever it
reports in between. This design does not fix that, and the fix is not the
single branch in `next_period_end` first supposed. It does mean a disclosed
date is the only source that will ever be right for a foreign private issuer,
which makes this feature worth more for BTDR and DGXX than for anyone else on
the roster.

**Fetching release bodies stays out**, gated on the miss count the extractor
will produce.
