# Measuring what a release body offers, outside the component that posts

Design, 2026-08-12.

## The problem

`press_monitor.py` fetches the body of a recognised announcement that carried no
date in its title, parses candidate dates out of it, and logs them. It stores
nothing. The point is to find out whether a reliable rule exists for picking a
reporting date out of a body. As of the 2026-08-12 11:53Z run, every run reports
the same population:

```
earnings dates: 2 recorded, 20 announcement(s) with no parsable date,
                4 rejected as past, 2 on file.
                Bodies fetched 0, 0 carried at least one forward-looking date.
```

**Twenty of the twenty-six recognised announcements carry no usable date, and the
probe meant to recover them has fetched nothing at all.** The fetch is gated on
items new in that run, and new items are rare: across the five most recent
successful runs (twenty polls in total) the sweep saw 354 items and **2 new
ones**. A new item that is *also* a recognised announcement, *also* carrying no
title date, *also* naming a scheduled event is rarer still. The twenty undated
announcements are all already seen, so they are never fetched. `Bodies fetched 0`
in every run since the probe shipped.

That the gate is the cause, rather than a broken parser, is what the counts show:
the twenty are recognised and counted every run. Only the fetch skips them.

That is the failure this repo already records one layer up, in the `FORM_TYPES`
trap: **a gate that fires on nothing looks exactly like a probe that has stopped
working.**

## The decision

The probe moves out of the scheduled component and becomes a maintenance tool run
by hand, in the shape `calibrate_staleness.py` already established. That script
closes its docstring with exactly the contract this one needs: *"Read-only.
Fetches the same feeds the monitor already fetches, posts nothing, writes
nothing, and needs no secrets."* It is also organised the way a hand-run tool
should be, under headings that say what it answers, when to run it, and how to
read the output. The probe follows that layout.

Three reasons, in order of weight.

**It takes a measurement out of the path that posts.** `press_monitor.py` writes
to a live Discord channel and is the component this repo's docs treat as most
fragile. Its date-recording call already needed a `try`/`except` wrapped around
it precisely because a measurement failing there could silence the channel.
Adding network calls to that path, for data nobody reads in real time, moves the
wrong way.

**It answers the question today rather than over weeks.** A hand-run sweep needs
no freshness gate and no tried-set. Take every recognised undated announcement,
fetch it, print the candidates, stop.

**The duplication objection does not survive contact with the code.**
`calibrate_staleness.py` already does `import press_monitor as pm` and calls
`pm.parse_feed`, `pm.scrape_hut8` and the rest. The probe imports the same module
and reuses every rule. There is no second copy of anything.

The honest cost: a hand-run sweep is a snapshot, not a monitor. It stops sampling
as new phrasings arrive. That is the right trade for a probe whose purpose is to
settle one question, and if it later needs to be ongoing, that decision can be
made **on** the data instead of before it.

## `probe_body_dates.py`

Read-only. No webhook, no state file, no commit, no schedule, no secrets.

**It reads the company-published sources only**, via `pm.collect_ir()`, which
despite its name covers the two scrapers and the two CMS readers as well as the
sixteen feeds. That distinction is load-bearing rather than pedantic: HUT has no
`ir_feed` at all and is reached by `scrape_hut8()`, and HUT is one of the
companies in the undated list. A probe that read only the feed sources would
have missed it and looked like it had covered everything.

What it does not read is EDGAR, and that exclusion is measured rather than
assumed. An EDGAR item's title comes from `filing_title()`, which joins entries
from `ITEM_LABELS` or falls back to `FORM_LABELS`. All 37 of those strings were
run through `looks_like_announcement` and **none matched**: the labels are noun
phrases like "Results of Operations and Financial Condition", carrying no
announcing verb, and a join of two of them carries none either. The company-authored
titles that do match look like "MARA Schedules Conference Call for Second Quarter
2026 Financial Results".

One residual path exists: `filing_title()` falls back to SEC's own `description`
field when no label applies, and that string is not drawn from a fixed set. It has
never produced a match in the counts above, but it is the reason this is stated as
measured-so-far rather than impossible. If the probe's population ever comes up
short of the logged no-date count, that fallback is the first place to look.

So the probe never touches `data.sec.gov` and needs no `SEC_USER_AGENT`, which is
why it takes no secrets at all.

**It reuses every rule rather than restating one**: `pm.ed.extract` to find the
undated announcements, `pm.announcement_body` to fetch, `pm.ed.candidate_dates` to
parse, and `pm.ed.names_a_scheduled_event` / `pm.ed.also_reports_results` to label.

### It deliberately does not apply the scheduled-event gate

In production that gate keeps date-dense results-release bodies out of the
measurement. **Whether it is the right discriminator is itself unmeasured**, and
applying it here would make the measurement unable to answer that.

So the probe fetches every recognised undated announcement and labels each with
both signals. The output then shows what an advance notice's body looks like
beside what a results release's body looks like. If advance notices carry one
clean forward date and results releases carry six, the gate is vindicated with
evidence. If they look alike, the gate is doing nothing and the rule has to come
from somewhere else.

Twenty fetches is nothing for a tool run by hand, and it is the only way to learn
whether the gate earns its place.

### Output

A table read by a person, one row per undated announcement: ticker, release date,
the labels, the candidate dates found, and the title. Then the counts that decide
the rule: how many bodies carried exactly one forward date, how many carried
several, how many none, split by label.

A single forward date in the advance-notice population is the result that makes a
rule possible. Several is the result that makes it a judgement call. None means
the bodies do not carry it either and the twenty stay unrecoverable, which is
itself a finding worth having, because it closes the question instead of leaving
it open indefinitely.

### `probe-body-dates.yml`

The probe runs on a runner rather than locally, because `press_monitor`'s
dependencies are not installed here and this repo's convention is not to run
component code locally at all. `calibrate.yml` is the template and it is short:

- `on: workflow_dispatch` only. No `schedule`.
- `permissions: contents: read`. **Read, not write**. The probe has no business
  committing, and the permission block is what makes that true rather than
  merely intended.
- `pip install feedparser requests`, then `python -u probe_body_dates.py`.
- No `env` block carrying secrets, because it needs none.
- A header comment stating it is a maintenance tool and not a component, in the
  form `calibrate.yml` uses: *"Read-only ... No webhook, no state, no commit, no
  schedule, no secrets."*

A `timeout-minutes` is worth setting. Twenty body fetches against IR hosts, each
bounded by `BODY_TIMEOUT`, should finish in well under a minute, so `10` matches
`calibrate.yml` with room to spare and still bounds a hung host.

## What comes out of `press_monitor.py`

The fetch gate inside `record_disclosed_dates`, the `body_seen` /
`body_with_dates` counters, the `BODY` log line, the `Bodies fetched` clause on
the summary, and the `fresh_uids` parameter with the set comprehension the caller
built to feed it.

That takes the network call and the gate out of the run path of the component
that posts. **The gate was only ever needed because the measurement lived there.**

**`announcement_body` itself stays**, with `BODY_TIMEOUT` and `BODY_MAX_BYTES`.
An earlier draft of this spec listed it for removal while also saying the probe
reuses `pm.announcement_body`, which cannot both be true; the Task 4 implementer
stopped on the contradiction rather than guessing. Keeping it is the right half
to keep, and not only because the probe calls it: it depends on `headers_for`,
and that is where this repo's per-host header knowledge lives. Moving the fetch
into the probe would either duplicate that knowledge or force a module-level
`press_monitor` import, and fragmenting it is exactly what caused the 22-hour
BGDE outage. `press_monitor` no longer calls the function; it only defines it,
beside the header logic it depends on.

`names_a_scheduled_event`, `also_reports_results` and `candidate_dates` stay in
`earnings_dates.py` with their tests, because the probe uses them. The no-date
count and its examples stay too: they are what showed the problem in the first
place.

## Verification

- The probe's parsing is already covered: `candidate_dates`,
  `names_a_scheduled_event` and `also_reports_results` have tests in
  `test_earnings_dates.py` demonstrated to fail without their implementations.
- Removing the body path from `press_monitor.py` must leave the suite passing and
  must not change what is stored. The `earnings dates:` summary must still report
  `2 recorded, 20 ... no parsable date, 4 rejected as past, 2 on file`, the same
  figures as before the change, since only the fetch is going away.
- A press-monitor dry run after the removal must show that line unchanged and no
  `BODY` lines, and must not report `Bodies fetched`.

**Two constraints limit how far this can be checked before merge, and they
compound.**

`workflow_dispatch` only registers on the default branch, so a brand new workflow
cannot be dispatched from a branch: `gh workflow run` returns *could not find any
workflows named*. The script and its workflow must be merged before they can be
run at all. `calibrate.yml` was handled exactly this way; `docs/local-workflow.md`
records it.

Local checking is thinner than it looks, too. The probe does `import press_monitor`,
and `press_monitor` imports `feedparser`, **which is not installed in this working
copy**, so the probe cannot even be imported locally, let alone run. Local
verification is therefore limited to `python -m py_compile` on the probe and the
full `test_earnings_dates.py` suite on the rules it calls.

That is acceptable only because of what the probe is: it posts nothing, writes
nothing, commits nothing and takes no secrets, so merging it unrun risks a
traceback in a hand-run tool and nothing else. The same reasoning would not
justify merging an unrun change to a component that posts.

## Out of scope

Deciding the rule. This produces the table; the rule is written afterwards, from
it, and only if the numbers support one.
