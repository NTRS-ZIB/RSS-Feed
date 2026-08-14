# A first-run rule in every component that keeps per-company state

Design, 2026-08-14. Written after a flood.

## What happened

`holder_events` posted **86 messages in one run** on 2026-08-14 at 14:39. Three
companies had been added the previous day — RIOT, CORZ and CRWV — and for a
company absent from `holder_state.json` every 13D/G filing on record is a first
appearance, which is exactly what that component exists to report. `CORZ: 39
structured, 39 new`. `CRWV: 32 structured, 30 new`.

**The guard existed and did not apply.** `press_monitor.baseline_companies`
suppressed the same three companies correctly in the same window — its log for
that morning reads *"FIRST RUN for CRWV — everything they have is marked seen
and NOTHING posts"*, 79 items suppressed, 0 posted. It is a rule inside one
component, and `holder_events` keys on its own state and has no equivalent.

The audit table in `docs/press-monitor.md` covers a different failure —
irreversibly marking an item handled and then filtering it out — and concludes
"one at risk, eleven not". **`holder_events` is not in that table at all.** The
roster-addition failure was never audited across components.

## The shape, and who has it

**A component with per-company state treats an unseen company's history as
news.** Five have it:

| Component | On a new company | Severity |
|---|---|---|
| `holder_events` | every 13D/G filing is a first appearance | **flood — 86 posts, measured** |
| `comment_letters` | every letter in a 180-day window is new | **flood — escaped 2026-08-14 only because all three had "none in window"** |
| `crossings` | starts `armed_hi`/`armed_lo` True, so a company at a 52-week extreme fires at once | one unearned post |
| `dilution` | no prior share count, so the first observation counts as changed | one |
| `threshold_list` | a company already on the list appears as an addition | one |

Bounded and not at risk: `volume_spike`, `short_interest`, `regsho_volume`,
`ftd_monitor` — each posts only the latest period or day, so an unseen company
contributes one current reading rather than a history.

`comment_letters` has `first_run = not STATE_FILE.exists()`, which is the right
idea at the wrong granularity: it is per FILE, is used only to annotate a log
line, and suppresses nothing.

## The second axis: new functionality, not just new companies

Adding a form type has the same shape rotated. When `144` joined
`INSIDER_ALLOWED_FORMS` on 2026-08-13, every Form 144 across all 22 companies
was unseen. **It did not flood only because `press_monitor`'s 7-day age floor
happened to cover it** — a protection that is incidental, not designed.
`holder_events` has no age floor, which is why it was the component that broke.

So the rule must be expressible over a capability as well as over a company.

## The design

`baseline_companies` is correct and its docstring already argues the parts that
are easy to get wrong. Extract the DECISION and leave the APPLICATION where it
belongs.

**A new shared module**, alongside `page_text.py` and `earnings_dates.py`:

```
baseline(state, keys, namespace="companies", today=None) -> new_keys
```

- Records `state[namespace]` as `{key: date}`.
- **Self-backfilling.** If `state[namespace]` is ABSENT this is the first run
  under the rule, every key is recorded and **nothing is new** — the companies
  already running are established by definition. Only a key missing from a
  PRESENT dict is new.
- **Absent and empty are different.** An empty dict means everything is new; a
  missing key means nothing is. Getting these the wrong way round either floods
  or silently suppresses a real backlog forever.
- Returns the new keys, sorted. Mutates `state`.
- Prints nothing. The caller logs, because only the caller knows what its
  suppression means and how many items it covered.

Each component then applies its own suppression, because "record as seen"
genuinely differs: accessions for holders, letters for correspondence, armed
flags for crossings, a share count for dilution, list membership for the
threshold list.

**Why a shared module now, when `CLAUDE.md` says a population of one does not
want a framework.** That judgement was made when the population WAS one, and it
was right then. It is five now, one of them has cost 86 messages, and the
semantics above are the part that is subtle rather than the application. The
new module quotes that line and says what overtook it.

## What the singles should do

`crossings`, `dilution` and `threshold_list` produce one unearned post each
rather than a flood, and there is a real argument that announcing a new
company's threshold listing once is useful.

**They suppress, and the spec records that as a decision rather than an
oversight.** A company added today did not cross its 52-week high today; the
crossing predates the watch. Announcing it asserts an event that did not happen
while we were looking, which is the same class of error as a backdated press
release. The state still records the position, so the next GENUINE change
posts normally.

## Verification

Every component here posts to a live Discord channel, and the failure mode of a
wrong change is silent suppression of real events — the opposite of the flood
and harder to notice.

- A check per component that a company absent from its state is suppressed AND
  recorded, and that an established company is untouched.
- A check that the absent-key backfill suppresses NOTHING, per component.
- **A dry run of every one of the five before merge**, confirming the log names
  what it suppressed and that established companies still produce their normal
  output.
- The mutation standard applies: name the one-line change that turns each check
  red, make it, watch it fail.

## Verification, as carried out

**Offline.** `test_first_run.py`, 57 checks. Every one demonstrated red by a
named one-line mutation — 51 of them, applied one at a time with
`__pycache__` cleared between each and the mutated file read back before the
run. Three checks were rewritten rather than kept, because no mutation could
redden them: one asserted what the shared module already proved, one asserted
what its neighbour asserted, and one deletion crashed the harness instead of
failing a check.

Each component's suppression is a named function so a check can reach it —
`drop_newly_watched` (holder_events, comment_letters), `initial_flags`
(crossings), `fold_newly_watched` (threshold_list), `is_change` (dilution).
`main()` is unreachable offline, so ten source-level checks pin that each
component passes its state to `baseline` and prints the summary, and five more
that it asks `backfilled()` **before** `baseline()` — asked afterwards it is
always False and the note never prints.

**Live, 2026-08-14.** All five dry-run on the branch, twice.

The first round was the finding: five green runs, five normal outputs, and
**nothing at all about the rule in any log**. The backfill records every key
and returns nothing new, so it cannot be distinguished from a rule that was
never called. `backfilled()` and `backfill_note()` were added for that.

The second round prints, in each of the five, `FIRST-RUN RULE: 22 companies
recorded as established in <component>, nothing suppressed`, with normal
output beside it — `dilution` reported 3 of 18 changed and rendered its table,
`comment_letters` and `threshold_list` reported no change, `crossings` nothing
crossed.

**What has NOT been exercised, and cannot be yet.** No component has
suppressed a real company, because every state file still lacks the
`companies` key: the first live run of each is the backfill. Suppression can
only be demonstrated after that, and only by adding a company. This is the
same shape as the push-retry loop recorded in `CLAUDE.md` — do not read the
surrounding work looking finished as evidence that this part ran.
