#!/usr/bin/env python3
"""
Schedule 13D/G holder events -> Discord.

An EVENT FEED, not a concentration report. Three event types and one silence:

    arrival        a filer group's first filing on this company
    change         an amendment moving the percentage
    declared exit  a final amendment reporting 0%
    (silence)      a holder who stops filing — NEVER reported as a departure

Data: EDGAR structured Schedule 13D/G, one submissions call per CIK.

WHY IT IS NOT A CONCENTRATION MEASURE, AND MUST NOT BECOME ONE
--------------------------------------------------------------
Anyone holding below 5% never files. A sum of disclosed holders therefore has a
floor it cannot state, and invites exactly the cross-company comparison it
cannot support — a company with three disclosed holders may have more
institutional ownership than one with six.

THIS IS ALSO WHY THE COMPONENT NEVER COUNTS HOLDERS, and that constraint has a
second consequence worth stating before someone asks for the count anyway.
Measured over 233 structured filings: 184 distinct reporting-person names
collapse to 70 filer groups once co-filing is taken into account, so 83% of
names sit inside a group. WULF's group is nine entities across five naming
conventions — Beowulf, Heorot Power, Lucky Liefern, Riesling Power, Stammtisch
Investments and Paul B. Prager personally. Any holder count has to solve that
first.

An event feed does not, because A GROUP FILING IS ONE EVENT WITH SEVERAL
SIGNATORIES rather than several events. The filing carries its own signatory
list and the component reports it as one thing.

WHY IT CANNOT REPORT A DEPARTURE
--------------------------------
A holder dropping below 5% files a final amendment at 0%, and that is
unambiguous — 29 exist across the structured era. A holder who simply stops
filing may still hold.

Ageing one out was tested and refused: the gap between consecutive filings has
a median of 92 days for holders still filing against 91 for those gone silent.
The same distribution. No threshold separates them, and the calibrate_staleness
formula applied to it yields 426 days, longer than the structured era for most
of the roster. So silence is reported as silence, or not at all.

LATENCY IS MEASURED, NOT QUOTED
-------------------------------
Measured over 233 filings on 2026-08-07:

    13D   dateOfEvent populated in 77 of 77 (100%)
          lag: median 3 days, 83% within 5, two over 45
    13G   absent in 156 of 156 (0%)

The absence is substantive rather than a gap. A 13D reports an EVENT — crossing
5% with intent — so it carries the date that happened. A 13G reports a POSITION
as of a date, on a periodic schedule; there is no event to date, and the schema
says so by omitting the field.

So a 13D post states the measured gap and a 13G post states that no event date
is filed and why. Neither quotes a statutory deadline, which matters because
the 2024 amendments already changed those once — a component asserting a rule
goes stale when the rule changes; one measuring the gap does not.

AND THE FIELD IS US-FORMATTED. `dateOfEvent` reads 09/03/2025 while `filingDate`
in the same payload is ISO. A parser assuming one format across a payload that
mixes both reports every 13D unparseable, which is a clean zero rather than an
error — see parse_event_date().

RELATIONSHIP TO press_monitor.py
--------------------------------
press_monitor already posts every 13D/G to the main filings channel, because
both spellings are in its FORM_TYPES. IT ANNOUNCES THAT A FILING EXISTS. THIS
COMPONENT READS IT. Same source, different question — the relationship
regsho_volume.py and short_interest.py already have. They post to different
channels so the pair never reads as a duplicate.
"""

import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests

import watchlist
# Imported by name rather than as a module: this file already has a local
# `first_run` for the whole-file guard, and the two names would collide.
from first_run import (backfill_note, backfilled, baseline, baseline_by_cik,
                       held_by_cik, newly_tracked, prune_unmeasured, summary)
from filing_subject import subject_cik

# ------------------------------------------------------------------ CONFIG

CIKS = watchlist.ciks()

# Any symbol a roster company has traded under -> its current ticker,
# identity mapping included. Imported rather than rebuilt: see
# migrate_symbols() for what writing this map backwards by hand once cost.
CANON = watchlist.symbol_to_ticker()

# {1591956: 'ANY', ...}. Integers, because watchlist pins CIKs zero-padded to
# ten and EDGAR writes them both ways in the same payload.
BY_CIK = {int(c): t for t, (c, _n) in CIKS.items()}

# Both spellings, for the reason press_monitor records: "SCHEDULE 13D" does not
# start with "SC 13D" — the fourth character is H, not a space — and the legacy
# prefix alone silently missed 117 filings.
#
# Only the SCHEDULE spellings are read for CONTENT, because only those are
# structured XML. The SC spellings are matched so the component can say a
# legacy filing exists rather than skip it silently.
STRUCTURED = ("SCHEDULE 13D", "SCHEDULE 13G")
LEGACY = ("SC 13D", "SC 13G")

# What the CAPABILITY axis of the first-run rule guards. Adding a prefix here
# is the same act as adding a company to the roster, and with no age floor it
# carries the same cost: every filing matching the new prefix is a first
# appearance. EDGAR has already forced one such edit — `SC 13D` became
# `SCHEDULE 13D` around December 2024 and 117 filings went missing until the
# new spelling was added.
#
# STRUCTURED ONLY, AND LEGACY IS NOT AN OVERSIGHT. Only structured filings
# become events; a legacy one becomes a line in the footnote saying it exists.
# Including LEGACY would let a prefix added there print a first-run line
# claiming a suppression that could not have happened, which is the same
# class of confident wrong answer the rule exists to stop printing.
FORMS_TRACKED = STRUCTURED

# A percentage moving by less than this is not an event. Institutions restate
# to two decimals every quarter and the number drifts with the share count
# rather than with their position.
NOTABLE_MOVE_PCT = 0.5

# Bound on the accession list. A CONSTANT rather than an inline literal, and
# that is the precondition for testing the eviction at all: with 348 entries
# against 2000 the slice is the identity function, so a check written against
# the live size passes under any implementation, right or wrong.
SEEN_CAP = 2000

STATE_FILE = Path(os.environ.get("HOLDER_STATE", "holder_state.json"))
REQUEST_GAP = 0.15

# ----------------------------------------------------------------- RUNTIME

# The insider channel. Form 4 is people acting on their own holdings and a
# 13D/G is an institution crossing 5% — the reader watching one wants the
# other. If the volume ever proves wrong it separates into its own webhook
# without touching anything else.
WEBHOOK = (os.environ.get("WEBHOOK_URL_INSIDER", "").strip()
           or os.environ.get("WEBHOOK_URL", "").strip())
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
# The older index pages. filer_regime, build_snapshot and audit_8k_items all
# already follow these; this component was the one that did not.
OLDER = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{doc}"
INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{acc}-index.htm"

ARRIVAL, CHANGE, EXIT, BELOW = "arrival", "change", "exit", "below"

# The threshold the whole form family is about. A first sighting BELOW it is
# not an arrival — see classify().
FILING_THRESHOLD_PCT = 5.0
AMBER, GREEN, GREY = 0xD29922, 0x3FB950, 0x5A6672

# The two schema variants, one per form family. Measured over 233 filings:
# every one carries blocks of exactly one kind and none of the other. Reading
# only the first found zero blocks in 156 of 233 and reported an answer about
# two-thirds of nothing.
VARIANTS = {
    "reportingPersonInfo": ("reportingPersonName", "percentOfClass",
                            "aggregateAmountOwned"),                # 13D
    "coverPageHeaderReportingPersonDetails": (
        "reportingPersonName", "classPercent",
        "reportingPersonBeneficiallyOwnedAggregateNumberOfShares"),  # 13G
}


# ------------------------------------------------------------------- STATE


def migrate_symbols(state):
    """Move per-company state off a former ticker and onto the current one.

    THE RENAME IS THE TRAP, and it is not hypothetical. `holders`, `era` and
    `read` are keyed by TICKER while the first-run record is keyed by CIK, so
    on the run after a rename the CIK still reads as established while every
    holder for that company orphans. Each one's next filing then classifies as
    an ARRIVAL and era_note attaches "first appearance in <TICKER>'s structured
    record, which begins <date>" to it, so the caveat written to catch a false
    arrival supplies evidence for one instead. Six of nineteen roster members
    have renamed in eighteen months.

    Sphere 3D's shareholders approved the change to DarkHorse on 2026-08-24 and
    the ticker has not flipped yet, so this lands BEFORE the rename rather than
    after it. It holds six keys today: four holders, one era, one read.

    first_run.held_by_cik already resolves aliases, for the prune and only for
    the prune. Fixing the lookup there and nowhere else is what left this open.

    THE RESOLUTION IS IMPORTED, NOT COPIED. watchlist.symbol_to_ticker() is the
    same map ftd_monitor and audit_identifiers use, and it is derived from the
    same field as alt_by_ticker() so the two cannot disagree. Writing that map
    out by hand backwards once attributed GREE to Soluna, merging two companies
    under a plausible number with nothing raised anywhere.

    Idempotent: the next run finds nothing to move. An unmappable prefix is
    LEFT IN PLACE AND COUNTED rather than deleted, because a prefix that
    resolves to nothing is a company this roster no longer knows about, and
    deleting its history to tidy up is exactly the silent loss this component
    cannot afford. The count is the part that matters: it is the only warning
    that a rename happened without the former symbol being recorded in
    `alt_symbols`, which is the one case this cannot repair.
    """
    moved = Counter()
    unmapped = Counter()
    conflicts = []

    def target(symbol):
        got = CANON.get((symbol or "").upper().strip())
        return got if got and got != symbol else None

    # era is a FLOOR and read is a HIGH-WATER MARK, so a collision resolves by
    # the namespace's own meaning rather than by a blanket "newest wins". era
    # takes the earlier date because it is stored as min() everywhere else, and
    # taking the later one would move a floor forward, which the component
    # treats as impossible.
    for space, keep in (("era", min), ("read", max)):
        book = state.get(space) or {}
        for old in sorted(book):
            new = target(old)
            if new is None:
                if not CANON.get((old or "").upper().strip()):
                    unmapped[old] += 1
                continue
            if new in book:
                book[new] = keep(book[new], book[old])
                conflicts.append(f"{space} {old} into existing {new}")
            else:
                book[new] = book[old]
            del book[old]
            moved[space] += 1

    holders = state.get("holders") or {}
    for key in sorted(holders):
        old, sep, sig = key.partition("|")
        if not sep:
            continue
        new = target(old)
        if new is None:
            if not CANON.get((old or "").upper().strip()):
                unmapped[old] += 1
            continue
        moved_key = f"{new}|{sig}"
        if moved_key in holders:
            # The current-ticker key already exists, which means a filing has
            # already posted under the new symbol. Its value is the more recent
            # reading, so it wins and the stale one goes. Recorded rather than
            # done quietly: this is the shape a false arrival leaves behind.
            conflicts.append(f"holders {old} into existing {new}")
        else:
            holders[moved_key] = holders[key]
        del holders[key]
        moved["holders"] += 1

    total = sum(moved.values())
    if total:
        detail = ", ".join(f"{k} {n}" for k, n in sorted(moved.items()))
        print(f"  symbol migration: moved {total} key(s) onto current tickers "
              f"({detail})")
        for line in conflicts:
            print(f"    merged {line}")
    else:
        # ALWAYS a line, even when there is nothing to move. A migration that
        # prints only when it fires is indistinguishable from one that never
        # ran, and this one runs before every read.
        print(f"  symbol migration: nothing to move "
              f"({len(state.get('era') or {})} tickers, "
              f"{len(state.get('holders') or {})} holder keys)")
    if unmapped:
        print(f"  symbol migration: {len(unmapped)} prefix(es) resolve to no "
              f"roster company and were LEFT IN PLACE: "
              f"{', '.join(sorted(unmapped))}")
        print("    A rename recorded without its former symbol in "
              "alt_symbols reads exactly like this.")
    return state


def load_state():
    try:
        s = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("seen", [])          # accessions already posted
    s.setdefault("holders", {})       # "TICKER|signature" -> last percent
    s.setdefault("era", {})           # ticker -> first structured filing seen
    # BEFORE ANY READ. match_holder, era_note and the era floor all key by
    # ticker, so a stale prefix has to be gone before the first lookup rather
    # than resolved at each one: a resolution added at three call sites is a
    # resolution missing from the fourth.
    return migrate_symbols(s)


def save_state(state):
    # RECORDING ORDER, NOT SORTED ORDER, and de-duplicated.
    #
    # This was `sorted(state["seen"])[-2000:]`, which READS as "keep the newest
    # 2000" and is not. An accession is TENDIGITS-YY-NNNNNN and the leading ten
    # digits identify the FILING AGENT, so lexicographic order is agent-major
    # and date-minor. Measured on the live list of 348: sorted() puts three
    # 2026 accessions first and a 2025 one fifth, and at a cap of 100 it would
    # drop 117 filings from 2026 while keeping 3 from 2024. The eviction is by
    # submitter, and nothing about the expression says so.
    #
    # main() appends as it reads, so the list's own order IS the order things
    # were recorded and the tail is the most recent. dict.fromkeys keeps the
    # first occurrence and drops repeats.
    #
    # THE DUPLICATE IS REAL rather than defensive. 0000950170-25-114068 is in
    # the file twice: it is the Hut 8 filing about American Bitcoin, and it was
    # read once under each company in the same run. state["seen"].remove() on
    # the failed-post path deletes ONE copy, so an item could be un-marked and
    # still be seen.
    #
    # Inert today at 348 of 2000. That arithmetic is why this is safe to change
    # now rather than urgent, and it is written down because nothing else
    # records it.
    state["seen"] = list(dict.fromkeys(state["seen"]))[-SEEN_CAP:]
    # ATOMIC, because the workflow now persists after a FAILED step. A run
    # killed by the job timeout mid-write would otherwise leave a truncated
    # holder_state.json for `git add` to commit, and the next run would read a
    # JSON error and start from an empty state: a cold start reached by a
    # clock. write_text is not atomic; os.replace on the same filesystem is.
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    os.replace(tmp, STATE_FILE)


# ------------------------------------------------------------------- FETCH


def sec_get(url, as_json=True):
    req = urllib.request.Request(
        url, headers={"User-Agent": SEC_USER_AGENT or "watchlist-monitor",
                      "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding")
    if enc == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return json.loads(raw) if as_json else raw.decode("utf-8", "replace")


def filings_for(cik):
    """Every 13D/G on the index, recent page AND the older ones.

    `filings.recent` IS A ROLLING WINDOW, NOT THE INDEX. It holds roughly a
    thousand filings, and for a heavy filer it sweeps past the company's own
    13D/G era with no error and no log line. This read only that page until
    2026-09-10, and the eviction was live rather than theoretical: CoreWeave's
    printed structured count fell 32, 35, 25, 23, 23, 23 across scheduled runs
    from 2026-08-14 to 2026-09-09 while three NEW filings arrived. A count
    going down reads as a data correction, not as a truncated page.

    Measured on the runner over all 22 roster CIKs (probe_holders, phase
    `subjects`): five companies have a second page, CRWV, MARA, RIOT, SLNH and
    WULF, and only CRWV has structured 13D/G on it, twelve of them. The other
    four carry only legacy SC-spelling filings there, so the legacy footnote
    has been reporting a floor rather than a count.

    THIS ADDS NOTHING TO POST, WHICH IS THE WHOLE REASON IT IS SAFE. Every one
    of CRWV's twelve is already in `seen`, because they were read on 2026-08-14
    while still on the recent page and eviction from the window does not
    un-record them. The probe put the number at zero unseen across the roster
    after dropping the misattributed filings, so this needs no suppression axis
    of its own. Landing it without that number would have been the 2026-08-14
    shape reached by editing a fetch function.

    It cannot move an era floor either: `era` is stored as min(prior, oldest)
    and the stored floor already equals the oldest over the paginated set for
    all 22 companies.

    Five extra requests per run, one per company with a second page, each
    behind REQUEST_GAP. The company loop itself still has no gap between
    companies, which is unchanged and not addressed here.
    """
    data = sec_get(SUBMISSIONS.format(cik=cik))
    out = []

    def add(block):
        forms = block.get("form") or []
        for i, form in enumerate(forms):
            if not form.startswith(STRUCTURED + LEGACY):
                continue

            def at(key):
                seq = block.get(key) or []
                return seq[i] if i < len(seq) else ""
            out.append({"form": form, "filed": at("filingDate"),
                        "accession": at("accessionNumber"),
                        "doc": at("primaryDocument")})

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(REQUEST_GAP)
        add(sec_get(OLDER.format(name=extra["name"])))
    return out


def raw_xml_path(doc):
    """EDGAR's primaryDocument for a structured 13D/G points at the XSL-RENDERED
    HTML VIEW — `xslSCHEDULE_13D_X02/primary_doc.xml`. Fetching that returns
    HTML and ElementTree dies on the first unclosed tag, which reads exactly
    like "this filing is not structured after all". Three companies were
    written off that way before the pattern was spotted. The source sits in the
    same directory with the stylesheet segment stripped."""
    parts = doc.split("/")
    return parts[-1] if len(parts) > 1 and parts[0].lower().startswith("xsl") \
        else doc


def parse_event_date(raw):
    """EDGAR writes dateOfEvent as US MM/DD/YYYY while filingDate in the same
    payload is ISO. Assuming one format across a payload that mixes both
    reports every 13D unparseable — a clean zero rather than an error."""
    text = (raw or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def tag_of(el):
    return el.tag.split("}")[-1]


def field(block, name):
    for el in block.iter():
        if tag_of(el) == name and (el.text or "").strip():
            return el.text.strip()
    return None


def as_pct(text):
    if text is None:
        return None
    try:
        return float(text.strip().rstrip("%").replace(",", ""))
    except ValueError:
        return None


def read_filing(cik, row):
    """(record, None) on success, or (None, reason) on failure.

    THREE OUTCOMES USED TO SHARE ONE RETURN VALUE AND ONLY ONE OF THEM PRINTED.
    A fetch or parse failure logged a line; a document that parsed but carried
    no known reporting-person block returned the same bare None in silence, and
    the caller could not tell them apart. A block-name rename at EDGAR hits
    every filing at once, so the whole component would go quiet while the
    per-company counts read normally and the run stayed green. That is this
    repo's oldest shape: a pattern matching nothing looks exactly like one
    whose matches never occur.

    The no-block reason NAMES THE TAGS ACTUALLY PRESENT, because the useful
    question after a rename is what the document calls them now, and answering
    it by hand means downloading the filing again.

    `percent` is the LARGEST reported by any signatory. A group files one
    position; the members report overlapping slices of it, and the maximum is
    the group's stake rather than a sum, which would double-count.

    `unnamed_blocks` counts reporting-person blocks whose NAME field is empty.
    Those are skipped while the others are kept, so a group of five read as
    three gets a different signature and can read as an ARRIVAL a year later.
    NOBODY HAS EVER MEASURED THIS, which is why it is counted rather than acted
    on: a guard built on an unmeasured case is a guess with a log line.
    """
    url = ARCHIVE.format(cik=int(cik), nodash=row["accession"].replace("-", ""),
                         doc=raw_xml_path(row["doc"]))
    try:
        root = ET.fromstring(sec_get(url, as_json=False))
    except Exception as e:                                      # noqa: BLE001
        return None, f"fetch or parse failed, {type(e).__name__}"

    people, pcts, unnamed = [], [], 0
    for block_name, (n_tag, p_tag, _a) in VARIANTS.items():
        for b in (el for el in root.iter() if tag_of(el) == block_name):
            name = field(b, n_tag)
            if not name:
                unnamed += 1
                continue
            people.append(name)
            p = as_pct(field(b, p_tag))
            if p is not None:
                pcts.append(p)
    if not people:
        present = sorted({tag_of(el) for el in root.iter()})
        return None, ("no reporting-person block; tags present: "
                      + ", ".join(present[:14])
                      + (f" ...and {len(present) - 14} more"
                         if len(present) > 14 else ""))

    ev = None
    for el in root.iter():
        if tag_of(el) == "dateOfEvent":
            ev = parse_event_date(el.text)
            break
    # The subject comes from the SAME document, so reading it costs no extra
    # request. See filing_subject for why it is scoped and case-insensitive.
    return {"people": people, "pct": (max(pcts) if pcts else None), "event": ev,
            "subject": subject_cik(root), "unnamed_blocks": unnamed}, None


def signature(people):
    """A stable key for a filer group.

    The sorted signatory set, because CO-FILING IS WHAT MAKES A GROUP. Two
    entities on one filing are one filer; two unrelated firms sharing a word
    never co-file. A name-stem rule was tested and fails both ways — it would
    merge BANK OF AMERICA with BANK OF NOVA SCOTIA, and would miss 36 real
    groups whose members share no word at all.

    The set can shift between amendments when a group adds or drops an entity,
    so the FIRST name is used as the display label and the full set as the key
    only when it matches; see match_holder().
    """
    return " | ".join(sorted(people))


def match_holder(state, ticker, people):
    """Find this group's prior record, tolerating a changed signatory list.

    An exact-set key would treat a group that added one entity as a new
    arrival, which is the false positive this component can least afford.
    Overlap of any signatory is enough — the same discriminator that separates
    a filer group from unrelated firms.
    """
    here = set(people)
    for key in state["holders"]:
        t, _sep, sig = key.partition("|")
        if t != ticker:
            continue
        if here & set(sig.split(" | ")):
            return key
    return None


# ------------------------------------------------------------------ EVENTS


def classify(state, ticker, people, pct):
    """(kind, previous_percent, state_key)."""
    key = match_holder(state, ticker, people)
    if key is None:
        new_key = f"{ticker}|{signature(people)}"
        # A FIRST SIGHTING BELOW 5% IS NOT AN ARRIVAL, and calling it one was
        # the defect the first dry run caught: it rendered "ABTC — new >5%
        # holder / Roxy Capital Corp / 0.20% of class", which is three claims
        # and all of them wrong.
        #
        # What it actually is: an amendment disclosing a position that has
        # already fallen below the threshold, whose crossing happened before
        # this component's record begins. Reporting it as an arrival inverts
        # the direction. Reporting it as an EXIT would be almost as bad — that
        # asserts a transition nobody observed.
        #
        # So it gets its own kind, which states only what the filing states.
        if pct is not None and pct < FILING_THRESHOLD_PCT:
            return BELOW, None, new_key
        return ARRIVAL, None, new_key
    prev = state["holders"].get(key)
    if pct is not None and pct == 0:
        return EXIT, prev, key
    if prev is None or pct is None:
        return CHANGE, prev, key
    if abs(pct - prev) < NOTABLE_MOVE_PCT:
        return None, prev, key
    return CHANGE, prev, key


def suppressed_run(ticker, form, first_run, backfill, newly_watched,
                   newly_forms, old_forms):
    """Could an event from this filing reach the channel on THIS run?

    THE WHOLE SAFETY OF THE UNREADABLE-FILING RULE RESTS ON THIS. A filing that
    could not have posted anyway costs nothing extra by being marked seen: that
    is exactly what happens today. One that COULD have posted must stay unseen
    so it retries.

    Module level rather than a closure inside main() so it can be tested. The
    behaviour it guards is only reachable through main(), but the decision
    itself does not have to be.

    All three suppression axes, because all three end with the same outcome:
    a cold start where the whole file is new, a company added to the roster
    since the last run, and a form prefix this component started tracking since
    the last run.
    """
    return bool(first_run or backfill or ticker in newly_watched
                or newly_tracked(form, newly_forms, old_forms, str.startswith))


def undo_event(state, row, prev, key):
    """Undo everything an event wrote, so a failed post can be retried.

    UN-MARKING `seen` WAS ONLY HALF OF IT. The baseline was already advanced
    for this event, so on the retry the same filing re-reads as a zero-point
    move and is dropped as sub-floor: un-marked, re-fetched, and silently never
    posted. The comment that used to sit here said "a failed post must not be
    marked seen or it is lost silently" and was right about the mechanism and
    incomplete about the state.

    `prev` is what the baseline held BEFORE this event, which is exactly what
    restores it. It is None for an arrival and for a first sighting below the
    threshold, and there the key did not exist beforehand, so the key goes
    rather than being set to None: a key present with a null value would match
    on the next run and classify as a change against nothing.

    Inert until the workflow stopped discarding a failed run's state, which is
    why the two changed together.
    """
    state["seen"].remove(row["accession"])
    if prev is None:
        state["holders"].pop(key, None)
    else:
        state["holders"][key] = prev


def advances_baseline(kind, pct):
    """Whether this filing's percentage may become the stored baseline.

    ONLY A FILING THAT PRODUCED AN EVENT MAY. The write used to be gated on
    `pct is not None` alone and ran before the sub-floor check, so a move too
    small to report still moved the baseline. A holder could then travel any
    distance in steps under NOTABLE_MOVE_PCT with nothing ever posted, and the
    "down from X%" on the eventual post would cite a figure the channel was
    never shown.

    Measured over the 22 committed revisions of holder_state.json: 153 keys,
    14 ever moved, 12 crossed the floor and posted, 2 were sub-floor rebases
    (CORZ Christopher R. Hansen 5.1 to 5.3, NUAI Caracola Ventures 8.6 to 8.9).
    NO key has two sub-floor steps in a row, which is the only shape that makes
    the two rules differ, so replaying both over that record gives 12 posts
    either way. THE FIX CHANGES NOTHING THAT HAS HAPPENED. It is a correctness
    change for what has not.

    That replay sees only committed state, so two moves of one key inside a
    single run collapse into one transition and a sub-floor pair could hide
    there. The claim is about the record, not about the world.

    A declared exit at 0.0 must still be recorded, which is why the test is
    `kind is None` and not the truthiness of pct.
    """
    return kind is not None and pct is not None


def era_note(state, ticker, filed):
    """The arrival caveat, as a count against the floor.

    A holder appearing for the first time in a short structured record may have
    arrived, or may have held for years and filed legacy until the schema
    changed in 2024-25. Those read identically and one is not news. The
    structured era runs from 10.8 months (HUT) to 30.3 (IREN) across the
    roster, so the length is stated rather than assumed.
    """
    first = state["era"].get(ticker)
    if not first:
        return ("first appearance — but this is the earliest structured "
                "filing seen for this company, so there is no record to have "
                "been absent from")
    months = (date.fromisoformat(filed) - date.fromisoformat(first)).days / 30.44
    if months < 1:
        return (f"first appearance, and this is at or near the start of "
                f"{ticker}'s structured record ({first}) — there is barely "
                f"any record to have been absent from")
    return (f"first appearance in {ticker}'s structured record, which begins "
            f"{first} ({months:.0f} months)")


def latency_note(form, ev, filed):
    """13D states the measured gap; 13G states why there is none."""
    if ev is not None:
        lag = (date.fromisoformat(filed) - ev).days
        return (f"crossed {ev.isoformat()} · filed {filed} · "
                f"{lag} day{'s' if lag != 1 else ''}")
    if "13G" in form:
        return (f"filed {filed} · a 13G reports a position as of a date "
                f"rather than an event, and files no event date — measured "
                f"absent in 156 of 156")
    return f"filed {filed} · no event date in this filing"


def build_embed(ticker, name, row, kind, people, pct, prev, ev, note):
    title = {ARRIVAL: f"{ticker} — new >5% holder",
             CHANGE: f"{ticker} — holder position changed",
             EXIT: f"{ticker} — holder dropped below 5%",
             BELOW: f"{ticker} — holder reported below 5%"}[kind]
    if "13D" in row["form"] and kind == ARRIVAL:
        title = f"{ticker} — activist stake disclosed"

    lead = people[0]
    body = f"**{lead}**\n"
    if pct is not None:
        if kind == EXIT:
            body += f"now **0%** of class"
            if prev is not None:
                body += f", from {prev:.2f}%"
        elif prev is not None:
            arrow = "up" if pct > prev else "down"
            body += f"**{pct:.2f}%** of class — {arrow} from {prev:.2f}%"
        elif kind == BELOW:
            body += (f"**{pct:.2f}%** of class — already below the 5% "
                     f"threshold when first seen here")
        else:
            body += f"**{pct:.2f}%** of class"
        body += "\n"
    if len(people) > 1:
        body += (f"\nFiled with {len(people) - 1} other signator"
                 f"{'y' if len(people) == 2 else 'ies'}:\n"
                 + ", ".join(people[1:8])
                 + (f", and {len(people) - 8} more" if len(people) > 8 else "")
                 + "\n")
    body += f"\n{row['form']} · {latency_note(row['form'], ev, row['filed'])}"
    if note:
        body += f"\n{note}"

    return {
        "title": title,
        "description": body,
        "url": INDEX.format(cik=int(CIKS[ticker][0]),
                            nodash=row["accession"].replace("-", ""),
                            acc=row["accession"]),
        "color": {ARRIVAL: AMBER, CHANGE: GREY, EXIT: GREEN,
                  BELOW: GREY}[kind],
        "footer": {"text": f"{name} · {row['accession']} · >5% disclosures "
                           f"only; holders below 5% never file"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def post(embed):
    try:
        r = requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=25)
    except requests.RequestException as e:
        print(f"  webhook failed: {type(e).__name__}")
        return False
    if r.status_code >= 300:
        print(f"  webhook returned {r.status_code}: {r.text[:160]}")
        return False
    time.sleep(1.0)
    return True


def drop_newly_tracked(events, new_forms, old_forms):
    """Events of a form type this component started tracking since last run.

    The other axis of the same rule. This component has NO AGE FLOOR, so a
    prefix added to STRUCTURED means every filing of that type on record is a
    first appearance — the shape that cost 86 messages on the company axis,
    reached by editing a constant instead of the roster.

    Returns the survivors and a count per newly tracked prefix.
    """
    per, kept = Counter(), []
    for e in events:
        hit = newly_tracked(e[2]["form"], new_forms, old_forms, str.startswith)
        if hit:
            per[hit] += 1
        else:
            kept.append(e)
    return kept, per


def drop_newly_watched(events, newly_watched):
    """Events belonging to companies added since the last run, removed.

    Returns the surviving events and a per-ticker count of what was dropped,
    which is what the log line needs — a name without a count reads as a
    warning, a name with one reads as a measurement.
    """
    per = Counter(t for t, *_ in events if t in newly_watched)
    return [e for e in events if e[0] not in newly_watched], per


# -------------------------------------------------------------------- MAIN


def main():
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.\n")
    elif not WEBHOOK:
        sys.exit("WEBHOOK_URL_INSIDER is not set.")
    if not SEC_USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous "
              "traffic and rejects a noreply address outright.\n")
    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    state = load_state()
    seen = set(state["seen"])
    first_run = not STATE_FILE.exists()
    # PER COMPANY, NOT PER FILE. `first_run` above covers a cold start. It does
    # NOT cover a company added to a roster this component has been watching
    # for months, and on 2026-08-14 that cost EIGHTY-SIX POSTS in one run —
    # CORZ 39 of 39 new, CRWV 30 of 32 — because for an unseen company every
    # 13D/G on record is a first appearance, which is what this file reports.
    # press_monitor already had the per-company rule; the comment below claimed
    # to use "the same rule" and used only the file-level half of it.
    backfill = backfilled(state)
    newly_watched = set(baseline_by_cik(state, CIKS))
    if backfill:
        print("\n" + backfill_note("holder_events", len(CIKS)))
    # THE CAPABILITY AXIS, its own namespace in the same state file. Adding a
    # prefix to FORMS_TRACKED is the same act as adding a company, and this
    # component has no age floor to blunt it.
    backfill_forms = backfilled(state, "forms")
    newly_forms = set(baseline(state, FORMS_TRACKED, namespace="forms"))
    if backfill_forms:
        print("\n" + backfill_note("holder_events", len(FORMS_TRACKED),
                                   "form types"))
    events, legacy_seen, measured = [], [], set()
    cross_roster, cross_offroster, no_subject = [], [], []
    unreadable, unnamed_blocks = [], Counter()
    fetched = classified = below_floor = 0
    old_forms = set(state["forms"]) - newly_forms


    for ticker, (cik, name) in sorted(CIKS.items()):
        try:
            rows = filings_for(cik)
        except Exception as e:                                  # noqa: BLE001
            print(f"  {ticker}: FAILED {type(e).__name__}")
            continue
        # Reached only once the submissions request succeeded, which is the
        # whole distinction: an empty result means the company has no 13D/G,
        # and an exception means this run does not know.
        measured.add(ticker)
        state.setdefault("read", {})[ticker] = date.today().isoformat()
        structured = [r for r in rows if r["form"].startswith(STRUCTURED)]
        legacy = [r for r in rows if r["form"].startswith(LEGACY)]
        if legacy:
            legacy_seen.append((ticker, len(legacy)))
        if structured:
            oldest = min(r["filed"] for r in structured)
            prior = state["era"].get(ticker)
            state["era"][ticker] = min(prior, oldest) if prior else oldest

        fresh = [r for r in structured if r["accession"] not in seen]
        print(f"  {ticker}: {len(structured)} structured, {len(fresh)} new")

        for row in sorted(fresh, key=lambda r: r["filed"]):
            time.sleep(REQUEST_GAP)
            fetched += 1
            parsed, why = read_filing(cik, row)
            if parsed is None:
                # MARKED SEEN ONLY IF IT COULD NOT HAVE POSTED ANYWAY, and the
                # naive fix is the one to avoid here. Moving this append below
                # unconditionally reads as the obvious correction and is worse:
                # `measured` and state["read"] are written the instant the
                # SUBMISSIONS request returns, before any document is fetched,
                # so a company whose index read fine is recorded established no
                # matter how many of its documents failed. Leave those unseen
                # and the company drops out of newly_watched on the next run,
                # and its unreadable back catalogue posts one run after its
                # suppression window closed: 2026-08-14 reached through a
                # transient instead of a floor.
                unreadable.append((ticker, row, why))
                if suppressed_run(ticker, row["form"], first_run,
                                   backfill, newly_watched, newly_forms,
                                   old_forms):
                    state["seen"].append(row["accession"])
                continue
            people = parsed["people"]
            pct, ev, subject = parsed["pct"], parsed["event"], parsed["subject"]
            if parsed["unnamed_blocks"]:
                unnamed_blocks[ticker] += parsed["unnamed_blocks"]

            # WHICH COMPANY IS THIS FILING ABOUT? EDGAR lists a 13D/G under
            # every reporting person's CIK as well as the subject's, and until
            # 2026-09-10 this loop labelled each filing with its own ticker and
            # never asked. Nine embeds went out on 2026-08-14 reporting Riot
            # Platforms as holding a stake in Riot Platforms.
            #
            # Suppression is on a POSITIVE MISMATCH only. Refusing whenever the
            # subject is merely missing would convert a visible wrong post into
            # an invisible missing one, which is the worse direction in a
            # component whose normal state is a quiet channel.
            if subject is None:
                # Unreachable today: 350 of 350 filings carry a subject CIK.
                # Not appended to `seen`, so it is retried rather than lost,
                # and that retry is unbounded by design: a filing we cannot
                # attribute must not be attributed by default to the index it
                # happened to be read from.
                no_subject.append((ticker, row))
                continue
            if subject != int(cik):
                owner = BY_CIK.get(subject)
                if owner:
                    # The subject is on the roster, so its OWN iteration reads
                    # the same accession from its own index and records it
                    # correctly. Measured: all three roster-subject filings are
                    # present under the subject's CIK as well as the filer's,
                    # so skipping this copy cannot delete the only copy.
                    # Deliberately NOT appended here, because appending would
                    # race the subject's iteration through the `fresh` snapshot
                    # and could mark it seen before the right company reads it.
                    cross_roster.append((ticker, owner, row))
                else:
                    # Nobody else on the roster will read this one, so it is
                    # marked seen here or it is refetched every run for ever.
                    cross_offroster.append((ticker, subject, row))
                    state["seen"].append(row["accession"])
                continue

            state["seen"].append(row["accession"])
            kind, prev, key = classify(state, ticker, people, pct)
            if advances_baseline(kind, pct):
                state["holders"][key] = pct
            if kind is None:
                below_floor += 1
                print(f"    {row['filed']} {people[0][:30]} "
                      f"{pct}% — below the {NOTABLE_MOVE_PCT}pt floor")
                continue
            classified += 1
            note = era_note(state, ticker, row["filed"]) if kind == ARRIVAL \
                else None
            events.append((ticker, name, row, kind, people, pct, prev, ev,
                           note, key))

    # A NEWLY WATCHED COMPANY POSTS NOTHING, and unlike the cold-start rule
    # below this one filters in a DRY RUN too. The cold-start exception exists
    # so an unrendered embed can be previewed on the only run where events are
    # available; these embeds are rendered every week, so that argument does
    # not apply, and a dry run that showed the suppressed events could not
    # demonstrate that they were suppressed — which is the one thing anyone
    # verifying this change needs to see.
    #
    # Their filings were still read and recorded above: accessions into `seen`,
    # percentages into `holders`, the era floor into `era`. Only the OUTPUT is
    # withheld, so the next genuine change for these companies posts normally.
    # A COMPANY THIS RUN COULD NOT REACH IS NOT ESTABLISHED. Unlike dilution
    # and crossings, nothing here is wrong today — the record and the filings
    # match, because no fetch has failed on a run that mattered. That is
    # ORDERING, not construction: a roster addition landing on a run where the
    # SEC refuses one request would record the company having read none of its
    # 13D/G, and the next run posts every one of them. Which is 2026-08-14
    # exactly, arriving through a transient instead of a floor.
    cik_of = {t: c for t, (c, _) in CIKS.items()}
    # THE CONDITION THAT MAKES THIS SAFE HERE AT ALL. A suppressed event is
    # already in `seen` by this point, so pruning an established company on a
    # transient fetch failure would lose its next real 13D/G permanently. A
    # company with an era floor has been read before and is never pruned.
    # UNION, because `era` alone answers the wrong question. It is written
    # only inside `if structured:`, so a company read successfully every run
    # that simply HAS no 13D/G holds no era entry — and pruning that one is
    # the catastrophic case: its first-ever 13D lands, is marked seen, then
    # suppressed, and no run can recover it. `read` records every successful
    # fetch, which is the fact the guard actually needs.
    has_state = held_by_cik(set(state.get("era", {})) | set(state.get("read", {})),
                            CIKS, watchlist.alt_by_ticker())
    deferred = prune_unmeasured(state,
                                {cik_of[t] for t in measured if t in cik_of},
                                set(cik_of.values()), has_state)
    if deferred:
        by_cik = {c: t for t, c in cik_of.items()}
        print("\nFirst-run record DEFERRED for "
              + ", ".join(by_cik.get(c, c) for c in deferred)
              + " — their filings could not be read this run.")
    newly_watched &= measured

    if newly_watched:
        events, per = drop_newly_watched(events, newly_watched)
        print("\n" + summary("holder_events", sorted(newly_watched), per))

    # THE COMPANY AXIS RUNS FIRST, deliberately. When a company and a form
    # type are both new in the same run, the company line explains the whole
    # of it and the form count stays honest instead of double-counting the
    # same filings under both headings.
    if newly_forms:
        events, per = drop_newly_tracked(
            events, newly_forms, set(state["forms"]) - newly_forms)
        print("\n" + summary("holder_events forms", sorted(newly_forms), per,
                             "form type"))

    # FIRST RUN POSTS NOTHING. Every structured filing is new on a cold start,
    # and 233 of them would arrive at once. The same rule press_monitor uses.
    #
    # BUT A DRY RUN STILL SHOWS THEM, because a dry run saves no state and
    # posts nothing, so there is no reason to withhold the output —
    # comment_letters.py carries the same exception for the same reason.
    # Without it the embed is unpreviewable on the only run where every event
    # is available to preview, and the rendering ships having never been
    # looked at.
    if first_run:
        print(f"\nFirst run: {len(events)} event(s) recorded as seen. "
              + ("Showing them below; a dry run posts nothing and saves "
                 "nothing." if DRY_RUN else "None posted. State initialised."))
        if not DRY_RUN:
            events = []

    print(f"\n{len(events)} event(s) to post")
    for ticker, name, row, kind, people, pct, prev, ev, note in events:
        embed = build_embed(ticker, name, row, kind, people, pct, prev, ev,
                            note)
        print(f"\n--- {embed['title']}")
        print(embed["description"])
        print(f"    {embed['footer']['text']}")

    # THE RECONCILIATION, and the identity is the point rather than the counts.
    # Every filing this run fetched has exactly one outcome, so they must sum.
    # A block-name rename at EDGAR would move filings from `classified` into
    # `unreadable` without changing a single per-company line, and nothing else
    # in this component would notice: the counts stay normal, the run stays
    # green, and the channel simply goes quiet. Reconciling the 2026-08-17 run
    # by hand was the only way to know it had not happened.
    outcomes = (classified + below_floor + len(unreadable) + len(cross_roster)
                + len(cross_offroster) + len(no_subject))
    print(f"\nread {fetched} filing(s): {classified} classified, "
          f"{below_floor} below the floor, {len(unreadable)} unreadable, "
          f"{len(cross_roster)} about another roster company, "
          f"{len(cross_offroster)} about an off-roster company, "
          f"{len(no_subject)} naming no subject")
    if outcomes != fetched:
        print(f"  RECONCILIATION FAILED: {outcomes} outcomes against "
              f"{fetched} filings read. A filing has been counted twice or "
              f"not at all, which means this summary cannot be trusted and "
              f"neither can the ones above it.")
    print(f"  block names tracked: {', '.join(sorted(VARIANTS))}")

    if unreadable:
        print(f"\n{len(unreadable)} filing(s) could not be read. Marked seen "
              f"ONLY where this run would have suppressed the event anyway:")
        for t, row, why in unreadable[:10]:
            mark = "seen" if row["accession"] in set(state["seen"]) else "retry"
            print(f"  {t} {row['form']} {row['filed']} {row['accession']} "
                  f"[{mark}] {why}")
        if len(unreadable) > 10:
            print(f"  ...and {len(unreadable) - 10} more")
    if unnamed_blocks:
        total = sum(unnamed_blocks.values())
        print(f"\n{total} reporting-person block(s) carried no name and were "
              f"skipped: "
              + ", ".join(f"{t} {n}" for t, n in sorted(unnamed_blocks.items())))
        print("  The rest of the group was still read, so its signature is "
              "short and could read as an arrival later. Never measured "
              "before today; counted rather than acted on.")

    # EVERY SKIP ARM PRINTS. A filing dropped because it is about somebody
    # else is the right outcome, but a silent right outcome is the shape this
    # whole component keeps getting caught by: it is indistinguishable from a
    # filing dropped because something broke. The counts are the difference.
    if cross_roster:
        print(f"\n{len(cross_roster)} filing(s) skipped under the company that "
              f"FILED them, and left for the company they are ABOUT:")
        for t, owner, row in cross_roster[:10]:
            print(f"  {t} {row['form']} {row['filed']} {row['accession']} "
                  f"-> recorded under {owner}")
        if len(cross_roster) > 10:
            print(f"  ...and {len(cross_roster) - 10} more")
    if cross_offroster:
        print(f"\n{len(cross_offroster)} filing(s) are about a company not on "
              f"the roster, marked seen and not posted:")
        for t, subj, row in cross_offroster[:10]:
            print(f"  {t} {row['form']} {row['filed']} {row['accession']} "
                  f"-> subject CIK {subj}")
        if len(cross_offroster) > 10:
            print(f"  ...and {len(cross_offroster) - 10} more")
    if no_subject:
        print(f"\n{len(no_subject)} filing(s) NAME NO SUBJECT and were refused "
              f"rather than attributed. Not marked seen, so they retry:")
        for t, row in no_subject[:10]:
            print(f"  {t} {row['form']} {row['filed']} {row['accession']}")
        print("  Measured 0 of 350 on 2026-09-10, so a non-zero count here "
              "means the schema moved.")

    if legacy_seen:
        print(f"\nLegacy SC-spelling filings present and not read: "
              + ", ".join(f"{t} {n}" for t, n in legacy_seen)
              + "\n  Those predate the structured schema and carry no parseable"
                " holder record. Reported so their absence is a measurement.")

    if DRY_RUN:
        print("\nDry run: nothing posted, state not saved.")
        return 0

    posted = 0
    for ticker, name, row, kind, people, pct, prev, ev, note, key in events:
        if post(build_embed(ticker, name, row, kind, people, pct, prev, ev,
                            note)):
            posted += 1
        else:
            # A FAILED POST MUST LEAVE NO TRACE, and un-marking `seen` was only
            # half of that. The baseline was already advanced for this event,
            # so on the retry the same filing re-reads as a zero-point move and
            # is dropped as sub-floor: un-marked, re-fetched, and silently
            # never posted.
            #
            # This was inert while the workflow discarded the whole run's state
            # on a non-zero exit. The `always()` gate below is exactly what
            # makes it reach disk, which is why the two had to change together:
            # the gate alone converts today's bounded duplicate into permanent
            # silent loss.
            undo_event(state, row, prev, key)
    save_state(state)
    print(f"\nPosted {posted} of {len(events)}.")
    return 0 if posted == len(events) else 1


if __name__ == "__main__":
    sys.exit(main())
