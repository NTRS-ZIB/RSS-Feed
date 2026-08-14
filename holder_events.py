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
from first_run import backfill_note, backfilled, baseline, summary

# ------------------------------------------------------------------ CONFIG

CIKS = watchlist.ciks()

# Both spellings, for the reason press_monitor records: "SCHEDULE 13D" does not
# start with "SC 13D" — the fourth character is H, not a space — and the legacy
# prefix alone silently missed 117 filings.
#
# Only the SCHEDULE spellings are read for CONTENT, because only those are
# structured XML. The SC spellings are matched so the component can say a
# legacy filing exists rather than skip it silently.
STRUCTURED = ("SCHEDULE 13D", "SCHEDULE 13G")
LEGACY = ("SC 13D", "SC 13G")

# A percentage moving by less than this is not an event. Institutions restate
# to two decimals every quarter and the number drifts with the share count
# rather than with their position.
NOTABLE_MOVE_PCT = 0.5

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


def load_state():
    try:
        s = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("seen", [])          # accessions already posted
    s.setdefault("holders", {})       # "TICKER|signature" -> last percent
    s.setdefault("era", {})           # ticker -> first structured filing seen
    return s


def save_state(state):
    state["seen"] = sorted(state["seen"])[-2000:]
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


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
    """Recent 13D/G filings, newest first."""
    data = sec_get(SUBMISSIONS.format(cik=cik))
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    out = []
    for i, form in enumerate(forms):
        if not form.startswith(STRUCTURED + LEGACY):
            continue

        def at(key):
            seq = recent.get(key) or []
            return seq[i] if i < len(seq) else ""
        out.append({"form": form, "filed": at("filingDate"),
                    "accession": at("accessionNumber"),
                    "doc": at("primaryDocument")})
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
    """(signatories, percent, event_date) or None.

    `percent` is the LARGEST reported by any signatory. A group files one
    position; the members report overlapping slices of it, and the maximum is
    the group's stake rather than a sum, which would double-count.
    """
    url = ARCHIVE.format(cik=int(cik), nodash=row["accession"].replace("-", ""),
                         doc=raw_xml_path(row["doc"]))
    try:
        root = ET.fromstring(sec_get(url, as_json=False))
    except Exception as e:                                      # noqa: BLE001
        print(f"    {row['accession']}: {type(e).__name__}")
        return None

    people, pcts = [], []
    for block_name, (n_tag, p_tag, _a) in VARIANTS.items():
        for b in (el for el in root.iter() if tag_of(el) == block_name):
            name = field(b, n_tag)
            if not name:
                continue
            people.append(name)
            p = as_pct(field(b, p_tag))
            if p is not None:
                pcts.append(p)
    if not people:
        return None

    ev = None
    for el in root.iter():
        if tag_of(el) == "dateOfEvent":
            ev = parse_event_date(el.text)
            break
    return people, (max(pcts) if pcts else None), ev


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
    newly_watched = set(baseline(state, CIKS))
    if backfill:
        print("\n" + backfill_note("holder_events", len(CIKS)))
    events, legacy_seen = [], []

    for ticker, (cik, name) in sorted(CIKS.items()):
        try:
            rows = filings_for(cik)
        except Exception as e:                                  # noqa: BLE001
            print(f"  {ticker}: FAILED {type(e).__name__}")
            continue
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
            parsed = read_filing(cik, row)
            state["seen"].append(row["accession"])
            if parsed is None:
                continue
            people, pct, ev = parsed
            kind, prev, key = classify(state, ticker, people, pct)
            if pct is not None:
                state["holders"][key] = pct
            if kind is None:
                print(f"    {row['filed']} {people[0][:30]} "
                      f"{pct}% — below the {NOTABLE_MOVE_PCT}pt floor")
                continue
            note = era_note(state, ticker, row["filed"]) if kind == ARRIVAL \
                else None
            events.append((ticker, name, row, kind, people, pct, prev, ev,
                           note))

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
    if newly_watched:
        events, per = drop_newly_watched(events, newly_watched)
        print("\n" + summary("holder_events", sorted(newly_watched), per))

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

    if legacy_seen:
        print(f"\nLegacy SC-spelling filings present and not read: "
              + ", ".join(f"{t} {n}" for t, n in legacy_seen)
              + "\n  Those predate the structured schema and carry no parseable"
                " holder record. Reported so their absence is a measurement.")

    if DRY_RUN:
        print("\nDry run: nothing posted, state not saved.")
        return 0

    posted = 0
    for ticker, name, row, kind, people, pct, prev, ev, note in events:
        if post(build_embed(ticker, name, row, kind, people, pct, prev, ev,
                            note)):
            posted += 1
        else:
            # State is saved regardless below, but a failed post must not be
            # marked seen or it is lost silently.
            state["seen"].remove(row["accession"])
    save_state(state)
    print(f"\nPosted {posted} of {len(events)}.")
    return 0 if posted == len(events) else 1


if __name__ == "__main__":
    sys.exit(main())
