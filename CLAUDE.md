# Working on this repo

Thirteen components post to Discord from GitHub Actions crons. [`README.md`](README.md)
lists them; [`docs/`](docs/) covers one per component;
[`docs/watchlist.md`](docs/watchlist.md) holds the roster and identifier rules;
[`docs/local-workflow.md`](docs/local-workflow.md) holds the git mechanics. This
file is only the reasoning behind the conventions — the part not recoverable by
reading the code.

## Output conventions

**Monospace blocks stay at or under 28 characters.** The README gives the
mechanics. What matters is that it is a ceiling, not a preference: Discord
mobile wraps past that width and splits every table row in two, which is worse
than showing less. A new column means an existing one goes.

**Never identify a company by ticker alone.** Five of fourteen have renamed in
eighteen months. A ticker is a display label; pin by CIK for EDGAR and CUSIP for
FINRA and SEC data, both of which survive a rename.

**Show a metric against that ticker's own trailing baseline, never as a bare
absolute.** Is 400,000 fails a lot? For one company it is a normal week, for
another it has never happened. A bare number invites the reader to supply a
baseline from intuition, and intuition here is wrong.

**Every post states its own data latency.** Sources run from minutes old to
three months, and the reader cannot tell by looking. A stale figure read as a
live one is the easiest mistake this channel invites.

**Absence of data is a measurement, not a gap — so report it.** The SEC lists
only non-zero fails, so a ticker missing from a file had zero, and the FTD
monitor stores a literal zero rather than skipping the period. Median over only
the periods where a ticker appeared would average its non-zero periods and erase
the most informative case there is: a name that never fails suddenly failing.

## Verification

**Nothing is trusted until a dry run against live data confirms it.** Every
component takes `DRY_RUN`, which evaluates and logs while posting nothing and
saving no state. Reasoning that a URL or a form type is right does not count as
confirming it.

**A test that has never failed proves nothing.** Adding a guard means first
demonstrating the failure it prevents, with the guard removed. The drift
detector below was validated that way — `SCHEDULE 13D` was taken back out of
`FORM_TYPES` to confirm it flagged it.

**Identifiers come from data a component actually reads, never from a filing.** A
filing is a lead to verify. The failure modes are not symmetric: a missing
identifier shows up as an unexplained gap, while a wrong one silently attributes
another security's rows to a company that never had them. `docs/watchlist.md`
records the BKKT case that established this.

**A window that finds nothing has shown only that it did not sweep far enough.**
Two identifiers were nearly deleted as phantoms on that mistake — BKKT's
`05759B107` (missed at 12 months, found at 36) and HUT's `44812T102` (missed at
48 periods, found at 120). Match depth to the company's history, not to habit.

## Working locally

**Do not run the component scripts.** They read secrets that exist only in
GitHub Actions, and several post to live Discord channels — a local run is a
real post. Use the workflow:

```bash
gh workflow run "Press release monitor" -f dry_run=true
```

That dispatches against a ref on GitHub, so it tests committed code and cannot
see local edits.

**`watchlist.py` is the exception, and safe to run directly.** It imports only
`sys`, makes no network calls, and its docstring says to run it. It prints and
validates the roster — the fastest check that an edit is sound.

**The `*_state.json` files and `snapshot.json` are outputs**, written by the
workflows several times a day. Never edit, delete or reformat one; a local edit
races the next bot commit and usually loses quietly.

**Their protection does not survive a re-clone.** The merge driver and
pre-commit hook live in `.git/`, which cannot be committed. Rebuild both from
`docs/local-workflow.md` before working in a fresh clone.

**Pull before pushing, always.** Fourteen workflows commit to `main` through the
day, so a non-fast-forward rejection is the normal case, not the exception.

## Standing traps

Each has happened once. They are listed because none announces itself in the
logs.

| Trap | The case that proves it |
|---|---|
| **EDGAR renames form types**, and prefix matching does not bridge a rename — `"SCHEDULE 13D".startswith("SC 13D")` is `False`. | `SC 13D` became `SCHEDULE 13D` around December 2024 and silently missed 117 filings, found only when a real one went unposted. `press_monitor.py` carries a drift detector. |
| **A CIK survives renames, reverse splits and a Rule 12g-3 succession — but not a combination creating a new registrant.** | HUT changed CIK while keeping its ticker, so nothing in `alt_symbols` would have caught it. The old CIK returns no filings and no error. |
| **A form type matching nothing looks exactly like one whose filings never occur.** | Both give no posts, no errors, no log lines. An entry in `FORM_TYPES` is an assumption until a filing of that type has actually posted. |
| **SEC's fair-access filter rejects a GitHub noreply address**; it wants a plain name and contact address. | The noreply form returns **403 from every sec.gov endpoint**, in both `urllib` and `requests`. Six components send `SEC_USER_AGENT`, so a wrong value fails all six at once and reads like an SEC outage. |
| **A source can die at HTTP 200 and look healthy in every check.** | DGXX's old GlobeNewswire feed serves 20 items, valid XML, good uid and timestamp on each, nothing newer than 2025-12-24; its sitemap lists 100 release URLs sharing one rebuild `lastmod`. Both passed every test this repo had. Bakkt's platform move broke loudly with a 404 — that is the rare case. See `check_staleness()` and `calibrate_staleness.py`. |
| **A soft-404 makes a wrong link indistinguishable from a right one.** | `digipowerx.com` answers 200 with wrong content for an unknown release URL, so a derived slug resolving 6 of 8 would have posted two dead links and logged nothing. Confirm a site actually 404s before trusting a constructed URL. See `read_dgxx()`. |
| **A default sort is not a date sort, and document order is not date order.** | DGXX's CMS returns a 2025-11-19 item first on an unsorted page 1, so `rows[0]` reports something eight months stale as newest; Hut 8's page interleaves recent and old in markup order. Sort explicitly by date; never trust position. |
| **EDGAR's `acceptanceDateTime` is EASTERN, despite ending in `Z`.** | Reading it as UTC puts every filing four or five hours early and nothing announces it. Confirmed twice: MARA's release is 12:05 UTC in its IR feed while the 8-K furnishing it shows `08:05`, exactly the EDT offset; and EDGAR accepts filings 06:00–22:00 ET, so a `06:31` read as UTC would fall outside its own operating hours. `filingDate` is date-only and unaffected. |
