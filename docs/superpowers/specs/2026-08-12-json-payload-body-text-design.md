# Reading the release text a site ships as JSON

Design, 2026-08-12.

## What this fixes

`announcement_body()` strips `<script>` blocks before extracting text. On a site
that server-renders its article into a JSON payload rather than into markup, that
strip deletes the article and keeps the furniture. HUT is such a site, and the
reporting date the body-date rule exists to find was in the part being deleted.

## This corrects a claim already committed to the repo

`docs/press-monitor.md:918-930` currently says, of HUT:

> **It is not a parsing failure and not a fixable one: hut8.com serves no release
> body to a plain fetch.** ... The release text is rendered client-side, so
> `announcement_body` is not losing the date; the date was never in the response.
> ... **No rule reading bodies will ever recover it from this source**, and the
> fix, if one is wanted, is a route to the content rather than a better parser.

**Every one of those sentences is false, and the last is exactly backwards.** The
date was in the response, `announcement_body` is precisely what loses it, and a
better parser is exactly the fix. That passage must be replaced as part of this
work. Leaving it would be worse than never having investigated, because it reads
as settled and would stop the next reader from looking.

The error is instructive enough to keep the shape of. Two checks agreed that the
body was absent: the probe's own fetch, and a WebFetch of the same URL. Both
render to text before anyone sees them, and both therefore drop script content
for the same reason. Two confirmations drawn from the same blind spot are one
confirmation, which is a trap `CLAUDE.md` already records in another form.

## The evidence

Measured 2026-08-12 against the live pages, following probe runs `31609856639`
and `31610431541`.

HUT's release page returns **121,286 bytes**. It contains
`<script type="application/json" id="__NUXT_DATA__">`, 7,535 characters holding a
flat 225-element array with 112 strings, and those strings carry the release
prose, including *"will release financial results for the second quarter of 2026
before the market opens on August 4, 2026"*.

**The decisive measurement is not that the payload exists but that production
already receives it.** Running `announcement_body`'s exact pipeline over that
document (strip `<script|style>`, strip tags, collapse whitespace) yields
**1,227 characters**, which is precisely the figure the probe logged for HUT. The
production fetch was never short-changed by the server. It downloaded the date
and deleted it.

The payload holds exactly two dates: `July 13, 2026` and `August 4, 2026`. July
13 is the release's own dateline, which `candidate_dates` already drops as a date
equal to `released`. What remains is **exactly one forward date**, which is what
the existing rule requires. No change to the rule is needed.

### Why this is additive for everything else

The other two advance-notice sources were measured the same way:

| source | visible text | matches probe | JSON script tags |
|---|---|---|---|
| HUT | 1,227 | yes | 1, holding the article |
| ABTC | 2,637 | yes | **none** |
| WYFI | 4,474 | yes | **none** |

ABTC and WYFI have no JSON script tags at all, so their extracted bodies are
byte-identical before and after this change. HUT is the only source in the
population the rule fires on that is affected.

## The change

In `announcement_body`, after building the visible text as it does now,
separately find every `<script type="application/json">` block in the same HTML,
`json.loads` each, walk the parsed structure collecting **string values only**,
and append those to the visible text.

**Strings only, not the raw payload.** Keys, structure and punctuation are
dropped, so what reaches the date parser is prose rather than JSON. Appending the
raw block instead would feed it URLs, class names and escaping, which is the
noise this design exists to avoid.

### The join must not be a space

Concatenating unrelated strings with whitespace can MANUFACTURE a date across a
boundary that exists in neither string. `["Revenue grew in August", "4, 2026 was
a record"]` joined with a space matches `August 4, 2026`, a date nobody
published. A page-state payload is full of adjacent unrelated strings, so this is
not a hypothetical shape.

**Join recovered strings, and the visible half to the recovered half, with a
separator containing a non-whitespace character** such as `" | "`. `DATE_RE`
allows `\s+` between the month and the day, so a newline would not prevent this;
a literal `|` cannot appear inside a match and ends it.

Measured on HUT: joining its 112 strings with `" | "` yields exactly the same two
dates as joining with a space, because both dates sit inside single strings:
`"MIAMI, July 13, 2026 "` and `"Date: Tuesday, August 4, 2026\nTime: 8:30 a.m.
ET"`. The separator costs nothing on the one source this exists for.

The residual trade, stated plainly: a site that splits a date across two strings
for formatting will now be missed. That fails toward storing nothing rather than
storing something invented, which is the direction the rule already chooses
everywhere else.

Order is visible text first, then recovered text. Nothing depends on it today,
since the rule fires only on exactly one date, but a deterministic order keeps
`candidate_dates`' "document order" contract meaningful.

### What string-only does not need to handle

None of HUT's 112 strings contains an HTML tag, so recovered text needs no second
tag-stripping pass. Were a site to store markup in a payload, tags would arrive as
noise that `DATE_RE` cannot match, so the failure is cosmetic rather than wrong.

A payload embedding a "related releases" list would contribute those releases'
dates and push the body to several candidates, where the rule stores nothing.
That is the safe direction and needs no special handling.

### `application/ld+json` is deliberately excluded

Schema.org metadata is the other place a site can ship article text. HUT does not
use it for this, and no roster source is known to. Its dates are ISO-formatted
and so invisible to `DATE_RE` anyway. Including it would be a guess about a
source nobody has measured, and today has already cost one such guess. If a
future source needs it, the measurement comes first.

### Failure handling

`announcement_body`'s contract is that it never raises, and returns `None` only
when the fetch itself failed. A malformed or unparseable payload must therefore
be skipped in silence and must not discard the visible text already extracted: a
site shipping broken JSON should cost the recovered half, never the half that
already worked.

The recovered text is capped alongside the visible text at `BODY_MAX_BYTES`, so a
large payload cannot make the body unbounded.

## Two properties that bound the risk

**`candidate_dates` deduplicates.** It carries a `seen` set, so appending text
that repeats a date the visible half already had cannot produce a second
candidate. A source with both a payload and rendered prose cannot be pushed from
`one` into `several` by duplication.

**The probe and the rule share this function.** Both call `announcement_body`, so
whatever the probe measures after this change is exactly what the rule will act
on. That is why the fix belongs here and nowhere else.

## Verification

Re-run `probe_body_dates` and diff the table against the run recorded in
`docs/press-monitor.md`.

**Exactly one row may change: HUT moves from `none` to `one` carrying
`2026-08-04`**, taking advance notices to 6 of 6. Any other row that changes is a
**finding to investigate and explain, not a bonus to accept.** The whole claim of
this design is that it is additive for sources with no JSON payload, and a second
changed row falsifies that claim rather than improving the result.

The `chars` column will rise for HUT and must stay identical for every other row,
which is the cheapest way to see whether the extraction reached anything it
should not have.

Unit-level checks belong on the extraction itself, driven by fixtures rather than
network: a payload holding prose, a payload that is not valid JSON, a page with no
payload at all, and a page whose payload repeats a date the visible text already
carries.

## Out of scope

Any change to the body-date rule, its gate, or its markers. This makes one more
source readable; what happens to a readable body is already settled and shipped.
