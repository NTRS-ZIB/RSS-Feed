#!/usr/bin/env python3
"""Tests for holder_events' pure functions. Standalone, no network.

`requests` is stubbed below because holder_events imports it at module scope
and nothing tested here posts. HOLDER_STATE is redirected to a temp path
BEFORE the import, because STATE_FILE is bound at import time and a suite that
imported first could overwrite a bot-written output. Remove the stub rather
than extending it if a test ever needs a fetching function: a stub that grows
is a stub that hides things.

THE ONE THAT MATTERS is not yet in this file, and that is deliberate rather
than an omission. On 2026-08-14, run 31810564097 posted nine embeds opening
"RIOT, activist stake disclosed / Riot Platforms, Inc. / 16.30% of class" and
walking down to 4.60. Riot Platforms does not hold a stake in Riot Platforms.
EDGAR lists a Schedule 13D/G under every reporting person's CIK as well as the
subject's, and main() labels each filing with the ticker of the roster loop it
was read under. Nothing in this module reads the subject, so there is no
function here to assert against yet; the check lands in the same commit as the
fix, against the real accession. Five self-referential records sit in
holder_state.json today and snapshot.json publishes RIOT SCHEDULE 13D count 9,
where the truth is zero.

WHAT THIS FILE DELIBERATELY DOES NOT COVER: the first-run axis.
test_first_run.py already owns drop_newly_watched, drop_newly_tracked and
prune_unmeasured, and its fixture for the prefix arm is better than a naive
one. Twenty of its 135 checks touch this component. Duplicating them here
would give two places to update and one of them would rot.

Every check below was demonstrated red under a named one-line change to
holder_events.py, with __pycache__ cleared between mutations and the mutated
file read back. A check nobody has watched fail is decoration.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import types

# BEFORE the import, not after. holder_events binds STATE_FILE at module scope
# from this variable, so a redirect afterwards would be read too late and the
# suite would write over the real bot-written state file.
os.environ["HOLDER_STATE"] = os.path.join(
    tempfile.gettempdir(), "test_holder_events_state.json")

sys.modules.setdefault("requests", types.ModuleType("requests"))

import inspect                        # noqa: E402
import holder_events as he            # noqa: E402
import filing_subject as fs           # noqa: E402
import xml.etree.ElementTree as ET    # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  ({detail})" if detail else ""))


def migrated(st):
    """migrate_symbols with stdout captured, returning (state, log)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = he.migrate_symbols(st)
    return out, buf.getvalue()


def state(holders=None, era=None):
    """A state dict shaped the way load_state() leaves one."""
    return {"seen": [], "holders": dict(holders or {}), "era": dict(era or {})}


def main():
    print("THE URL THAT READS AS 'NOT STRUCTURED AFTER ALL'")
    # EDGAR's primaryDocument for a structured 13D/G points at the XSL-rendered
    # HTML view. Fetching that returns HTML, ElementTree dies on the first
    # unclosed tag, and the natural conclusion is that the filing is not
    # structured. Three companies were written off that way.
    check("THE XSL SEGMENT IS STRIPPED",
          he.raw_xml_path("xslSCHEDULE_13D_X02/primary_doc.xml")
          == "primary_doc.xml",
          "the rendered view parses as HTML and reads as an unstructured filing")
    # The converse, and it is load-bearing rather than symmetry for its own
    # sake: a rule that always took the last segment would pass the check above
    # while silently rewriting every ordinary nested path.
    check("an ordinary nested path is left alone",
          he.raw_xml_path("subdir/filing.htm") == "subdir/filing.htm")
    # A THIRD CHECK WAS WRITTEN HERE AND DELETED. "a bare filename is left
    # alone" cannot fail: with no slash, len(parts) is 1 and parts[-1] IS doc,
    # so every one-line mutation of this function returns the same value for
    # that input. It read as coverage in a green run and was not.

    print("\nA PAYLOAD THAT MIXES TWO DATE FORMATS")
    # dateOfEvent is US MM/DD/YYYY while filingDate in the SAME payload is ISO.
    # Assuming one format across it reports every 13D unparseable, which is a
    # clean zero rather than an error.
    check("US MM/DD/YYYY parses",
          str(he.parse_event_date("04/07/2025")) == "2025-04-07")
    check("ISO parses from the same function",
          str(he.parse_event_date("2025-04-07")) == "2025-04-07")
    # Wrapped, because the mutation that proves this check is removing the
    # try/except, and an exception escaping into the harness is not a failure
    # anyone can read.
    try:
        junk = he.parse_event_date("not a date")
        ok, why = junk is None, f"returned {junk!r}"
    except Exception as e:                                      # noqa: BLE001
        ok, why = False, f"raised {type(e).__name__}"
    check("an unreadable date is None rather than an exception", ok, why)

    print("\nPERCENTAGES")
    check("a trailing percent sign is stripped", he.as_pct("16.30%") == 16.30)
    check("thousands separators are stripped", he.as_pct("1,234.5") == 1234.5)
    check("prose yields None, not a number",
          he.as_pct("approximately five percent") is None,
          "a wrong number here is published as a holding")
    check("an absent field yields None", he.as_pct(None) is None)

    print("\nA GROUP FILING IS ONE EVENT WITH SEVERAL SIGNATORIES")
    # Co-filing is what makes a group, so the key is the SORTED signatory set.
    # Document order is not stable and must not reach the key.
    check("the signature is order independent",
          he.signature(["B Corp", "A Corp"]) == he.signature(["A Corp", "B Corp"]))
    st = state({"WULF|Beowulf | Heorot Power": 5.1})
    check("OVERLAP OF ANY SIGNATORY MATCHES THE GROUP",
          he.match_holder(st, "WULF", ["Heorot Power", "Riesling Power"])
          == "WULF|Beowulf | Heorot Power",
          "a group that gains one entity must not read as a new arrival")
    check("no shared signatory does not match",
          he.match_holder(st, "WULF", ["Vanguard Portfolio Management"]) is None)
    # The regression guard for the alias work: resolving a RENAMED ticker onto
    # its old key must never widen into matching a genuinely different company.
    check("A DIFFERENT COMPANY NEVER MATCHES",
          he.match_holder(st, "MARA", ["Heorot Power"]) is None,
          "same signature, different issuer, must be a separate position")

    print("\nCLASSIFICATION")
    # A first sighting below 5% is not an arrival, and calling it one rendered
    # "ABTC new >5% holder / Roxy Capital Corp / 0.20% of class", which is
    # three claims and all of them wrong.
    kind, prev, key = he.classify(state(), "ABTC", ["Roxy Capital Corp"], 0.20)
    check("A FIRST SIGHTING BELOW 5% IS NOT AN ARRIVAL",
          kind == he.BELOW,
          f"got {kind}; arrival would publish a >5% claim about 0.20%")
    check("the below-threshold sighting has no previous value", prev is None)
    kind, _p, _k = he.classify(state(), "ABTC", ["Some Holder LP"], 7.5)
    check("a first sighting at or above 5% is an arrival", kind == he.ARRIVAL)

    known = {"CORZ|Two Seas Capital LP": 6.0}
    kind, prev, _k = he.classify(state(known), "CORZ", ["Two Seas Capital LP"], 0.0)
    check("A DECLARED EXIT AT ZERO IS AN EXIT", kind == he.EXIT,
          "the only unambiguous departure this component can report")
    check("the exit carries the previous percentage", prev == 6.0)

    kind, _p, _k = he.classify(state(known), "CORZ", ["Two Seas Capital LP"], 6.3)
    check("a sub-floor move produces no event", kind is None,
          f"0.3 points against a floor of {he.NOTABLE_MOVE_PCT}")
    # The boundary is the whole trap, and neither side of it errors or logs.
    kind, _p, _k = he.classify(state(known), "CORZ", ["Two Seas Capital LP"], 6.5)
    check("A MOVE EXACTLY AT THE FLOOR DOES POST", kind == he.CHANGE,
          "the test is < rather than <=, so 0.5 is reportable")
    kind, prev, _k = he.classify(state(known), "CORZ", ["Two Seas Capital LP"], 9.0)
    check("a move above the floor is a change", kind == he.CHANGE)
    check("the change carries the previous percentage forward", prev == 6.0,
          "this is the 'down from X%' the embed prints")

    print("\nTHE ARRIVAL CAVEAT")
    st = state(era={"IREN": "2024-01-26"})
    note = he.era_note(st, "IREN", "2026-01-26")
    check("the caveat names the floor and counts months against it",
          "2024-01-26" in note and "24 months" in note, note[:60])
    note = he.era_note(state(era={"HUT": "2025-09-10"}), "HUT", "2025-09-20")
    check("a holder at the very start of the record is caveated harder",
          "barely any record" in note)
    # Wrapped: the mutation that proves this one removes the guard, and the
    # unguarded path calls date.fromisoformat(None), which raises. An exception
    # reaching the harness is not a failure anyone can read.
    try:
        note = he.era_note(state(), "NEWCO", "2026-01-01")
        ok, why = "no record to have been absent from" in note, note[:50]
    except Exception as e:                                      # noqa: BLE001
        ok, why = False, f"raised {type(e).__name__}"
    check("no floor at all says there is no record to have been absent from",
          ok, why)

    print("\nLATENCY IS MEASURED, NOT QUOTED")
    from datetime import date as _date
    note = he.latency_note("SCHEDULE 13D/A", _date(2025, 4, 7), "2025-04-09")
    check("a 13D states the measured gap", "2 days" in note, note)
    note = he.latency_note("SCHEDULE 13G", None, "2026-08-14")
    check("a 13G says WHY it carries no event date",
          "no event date" in note and "position as of a date" in note)
    note = he.latency_note("SCHEDULE 13D", None, "2026-08-14")
    check("a 13D with no event date is not explained away as a 13G",
          "position as of a date" not in note, note)

    print("\nTITLES")
    row = {"form": "SCHEDULE 13G", "filed": "2026-08-14", "accession": "x"}
    titles = {}
    for kind in (he.ARRIVAL, he.CHANGE, he.EXIT, he.BELOW):
        e = he.build_embed("CORZ", "Core Scientific", row, kind,
                           ["A Holder LP"], 6.0, 5.0, None, None)
        titles[kind] = e["title"]
    check("every event kind has its own title",
          len(set(titles.values())) == 4,
          "; ".join(sorted(titles.values()))[:80])
    check("the below-5% title claims nothing about crossing 5%",
          ">5%" not in titles[he.BELOW], titles[he.BELOW])

    print("\nA RENAME MUST NOT ORPHAN A COMPANY\'S HOLDERS")
    # GREE to VIP is a REAL rename this roster already carries, not a synthetic
    # one. holders, era and read are keyed by ticker while the first-run record
    # is keyed by CIK, so without this the company still reads as established
    # while every holder orphans, and each one's next filing posts as a new
    # >5% holder with era_note supplying a record length that makes the false
    # arrival look supported.
    st = {"seen": [], "companies": {"0001844971": {"any": "value"}},
          "holders": {"GREE|Some Holder LP": 7.2, "VIP|Other Holder": 5.5},
          "era": {"GREE": "2024-03-01", "VIP": "2025-01-28"},
          "read": {"GREE": "2025-06-01", "VIP": "2026-09-09"}}
    out, log = migrated(st)
    check("A FORMER TICKER'S HOLDER MOVES TO THE CURRENT ONE",
          "VIP|Some Holder LP" in out["holders"]
          and "GREE|Some Holder LP" not in out["holders"],
          "otherwise its next filing posts as a first appearance")
    # .get, not [], throughout these checks. A mutation that DELETES a key
    # would otherwise raise KeyError and take the harness down before the
    # check could report, and a mutation that crashes the runner has shown
    # nothing.
    check("the moved holder keeps its percentage",
          out["holders"].get("VIP|Some Holder LP") == 7.2)
    check("a holder already under the current ticker is untouched",
          out["holders"].get("VIP|Other Holder") == 5.5)
    # The two namespaces collide differently ON PURPOSE, by what each MEANS.
    check("ERA TAKES THE EARLIER DATE, because it is a floor",
          out["era"] == {"VIP": "2024-03-01"},
          "taking the later one would move a floor forward, which the "
          "component treats as impossible")
    check("read takes the later date, because it is a high-water mark",
          out["read"] == {"VIP": "2026-09-09"})
    check("the CIK-keyed first-run namespace is not touched",
          out["companies"] == {"0001844971": {"any": "value"}}
          and "LEFT IN PLACE" not in log,
          "CIK keys are not tickers and must not be reported as unmappable")

    # The bug this closes, stated as behaviour rather than as key shapes.
    kind, _p, _k = he.classify(out, "VIP", ["Some Holder LP"], 7.4)
    check("AFTER THE MOVE A SMALL CHANGE IS NOT A NEW ARRIVAL",
          kind is None,
          f"got {kind}; before the migration this published 'new >5% holder'")

    # A prefix that resolves to nothing is a company the roster no longer
    # knows. Deleting its history to tidy up is the silent loss this component
    # cannot afford, so it stays and is counted.
    st = {"seen": [], "holders": {"ZZZZ|Ghost Capital": 9.9},
          "era": {"ZZZZ": "2024-01-01"}, "read": {}}
    out, log = migrated(st)
    check("AN UNMAPPABLE PREFIX IS LEFT IN PLACE, NOT DELETED",
          out["holders"] == {"ZZZZ|Ghost Capital": 9.9}
          and out["era"] == {"ZZZZ": "2024-01-01"})
    check("and it is counted out loud",
          "LEFT IN PLACE" in log and "ZZZZ" in log,
          "the only warning that a rename lost its former symbol")

    # Idempotent, because it runs before every single read.
    st = {"seen": [], "holders": {"GREE|Some Holder LP": 7.2},
          "era": {"GREE": "2024-03-01"}, "read": {"GREE": "2025-06-01"}}
    once, _l = migrated(st)
    snapshot = json.dumps(once, sort_keys=True)
    twice, log = migrated(once)
    check("running it twice changes nothing",
          json.dumps(twice, sort_keys=True) == snapshot
          and "nothing to move" in log)
    check("it says so even when there is nothing to move",
          "nothing to move" in log,
          "a migration that prints only when it fires looks like one that "
          "never ran")

    # THE HAZARD THIS SHAPE EXISTS TO AVOID. Re-keying onto CIKs would have
    # been the tidier fix and would silently break first_run.held_by_cik,
    # which expects TICKER keys and drops anything else with no error, so
    # prune_unmeasured would start pruning established companies on a
    # transient fetch failure.
    from first_run import held_by_cik
    import watchlist as _w
    st = {"seen": [], "holders": {}, "era": {"GREE": "2024-03-01"},
          "read": {"GREE": "2025-06-01"}}
    before = held_by_cik(set(st["era"]) | set(st["read"]), he.CIKS,
                         _w.alt_by_ticker())
    out, _l = migrated(st)
    after = held_by_cik(set(out["era"]) | set(out["read"]), he.CIKS,
                        _w.alt_by_ticker())
    check("HELD_BY_CIK RESOLVES THE SAME CIKS AFTER THE MOVE",
          before == after and len(after) == 1,
          "prune_unmeasured reads this; shrinking it prunes live companies")

    # It has to run before the first lookup, not at each lookup site.
    path = os.environ["HOLDER_STATE"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"seen": [], "holders": {"GREE|Some Holder LP": 7.2},
                   "era": {"GREE": "2024-03-01"}, "read": {}}, fh)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        loaded = he.load_state()
    os.remove(path)
    check("LOAD_STATE MIGRATES BEFORE ANYTHING READS",
          "VIP|Some Holder LP" in loaded["holders"],
          "a resolution added at three call sites is one missing at the fourth")

    print("\nTHE BASELINE ONLY ADVANCES FOR A FILING THAT POSTED")
    # The write used to be gated on `pct is not None` alone and ran before the
    # sub-floor check, so a move too small to report still moved the baseline.
    # A holder could then travel any distance in steps under the floor with
    # nothing posted, and the eventual "down from X%" would cite a figure the
    # channel was never shown.
    check("A SUB-FLOOR FILING DOES NOT ADVANCE THE BASELINE",
          he.advances_baseline(None, 6.3) is False,
          "kind None means nothing was published, so nothing may be recorded")
    check("a reportable change does advance it",
          he.advances_baseline(he.CHANGE, 6.3) is True)
    check("A DECLARED EXIT AT ZERO STILL ADVANCES IT",
          he.advances_baseline(he.EXIT, 0.0) is True,
          "0.0 is falsy, so this tests kind rather than the truthiness of pct")
    check("a filing whose percentage would not parse advances nothing",
          he.advances_baseline(he.ARRIVAL, None) is False)

    # The behaviour, walked two steps, which is the thing the gate exists for.
    # Old rule: baseline becomes 5.4, so 5.8 is a 0.4 move and never posts.
    # New rule: baseline stays 5.0, so 5.8 is a 0.8 move and does.
    st = state({"CORZ|Two Seas Capital LP": 5.0})
    kind, _p, key = he.classify(st, "CORZ", ["Two Seas Capital LP"], 5.4)
    if he.advances_baseline(kind, 5.4):
        st["holders"][key] = 5.4
    check("the first sub-floor step still posts nothing", kind is None)
    check("and the stored baseline is untouched",
          st["holders"]["CORZ|Two Seas Capital LP"] == 5.0)
    kind2, prev2, _k = he.classify(st, "CORZ", ["Two Seas Capital LP"], 5.8)
    check("CUMULATIVE DRIFT REACHES THE FLOOR AND POSTS",
          kind2 == he.CHANGE and prev2 == 5.0,
          f"got {kind2} from {prev2}; rebasing made this a 0.4 move that "
          f"never posted")

    print("\nEVICTION KEEPS THE NEWEST RECORDED, NOT THE LARGEST STRING")
    # An accession is TENDIGITS-YY-NNNNNN and the leading ten digits identify
    # the FILING AGENT, so sorting orders by submitter. On the live list of 348
    # a cap of 100 would drop 117 filings from 2026 and keep 3 from 2024.
    # The fixture is built so the two rules disagree: the 2024 accession has
    # the LARGEST agent prefix, so sorted() keeps it and drops a 2026 one.
    saved_cap = he.SEEN_CAP
    he.SEEN_CAP = 3
    try:
        st = {"seen": ["0002999999-24-000001", "0000000001-26-000009",
                       "0000000001-26-000010", "0000000001-26-000010",
                       "0000000001-26-000011"],
              "holders": {}, "era": {}, "read": {}}
        he.save_state(st)
        with open(os.environ["HOLDER_STATE"], encoding="utf-8") as fh:
            # .get, not [], for the same reason as everywhere else here: a
            # mutation that writes an empty state would raise KeyError and
            # take the harness down before any check could report.
            written = json.load(fh).get("seen", [])
    finally:
        he.SEEN_CAP = saved_cap
        if os.path.exists(os.environ["HOLDER_STATE"]):
            os.remove(os.environ["HOLDER_STATE"])
    check("THE 2024 FILING WITH THE LARGEST AGENT PREFIX IS EVICTED",
          "0002999999-24-000001" not in written,
          f"sorted() would keep it; got {written}")
    check("the newest recorded filing survives",
          "0000000001-26-000011" in written)
    check("THE LIST IS DE-DUPLICATED",
          len(written) == len(set(written)),
          "seen.remove() on a failed post deletes one copy of two, and "
          "0000950170-25-114068 really is in the live file twice")
    check("the cap is honoured", len(written) <= 3, str(written))

    print("\nWHICH COMPANY IS THIS FILING ACTUALLY ABOUT")
    # THE ONE THAT MATTERS. EDGAR lists a 13D/G under every reporting person's
    # CIK as well as the subject's. On 2026-08-14 run 31810564097 posted nine
    # embeds reading "RIOT, activist stake disclosed / Riot Platforms, Inc. /
    # 16.30% of class", walking down to 4.60. Those are Riot's own filings
    # about Bitfarms. The fixture below is the real shape of accession
    # 0000950170-25-114068: Hut 8 Corp. filing about American Bitcoin, which
    # put HUT into holder_state.json at 64.5% of itself.
    #
    # These checks live here rather than in a suite of their own because
    # holder_events is the only caller today. When build_snapshot adopts the
    # rule they should move to test_filing_subject.py.
    D13 = ET.fromstring("""
      <edgarSubmission><formData><coverPageHeader>
        <issuerInfo>
          <issuerCIK>0001755953</issuerCIK>
          <issuerName>American Bitcoin Corp.</issuerName>
        </issuerInfo>
        <coverPageHeaderReportingPersonDetails>
          <reportingPersonName>Hut 8 Corp.</reportingPersonName>
          <reportingPersonCIK>0001964789</reportingPersonCIK>
        </coverPageHeaderReportingPersonDetails>
      </coverPageHeader></formData></edgarSubmission>""")
    check("THE REAL HUT FILING IS ABOUT AMERICAN BITCOIN, NOT HUT",
          fs.subject_cik(D13) == 1755953,
          "1964789 is Hut 8, the filer; this is the record that read 64.5% "
          "of HUT")
    # A CHECK WAS WRITTEN HERE AND REPLACED. "the filer's own CIK is not
    # mistaken for the subject" asserted != 1964789, which the check above
    # already implies: if the answer is 1755953 it is not 1964789, so no
    # mutation can redden one without the other. What is actually worth
    # asserting is the SCOPE, so the fixture below puts a stray issuerCIK
    # earlier in document order than the real one.
    STRAY = ET.fromstring("""
      <edgarSubmission><formData>
        <someOtherBlock><issuerCIK>0001964789</issuerCIK></someOtherBlock>
        <coverPageHeader>
          <issuerInfo><issuerCIK>0001755953</issuerCIK></issuerInfo>
        </coverPageHeader>
      </formData></edgarSubmission>""")
    check("ONLY THE issuerInfo BLOCK IS READ",
          fs.subject_cik(STRAY) == 1755953,
          "a bare tree scan takes document order and would answer 1964789")

    # 13D spells it issuerCIK and 13G spells it issuerCik, measured 103 of 103
    # and 247 of 247. ElementTree tag comparison is case sensitive, so a rule
    # accepting one spelling drops seven filings in ten.
    G13 = ET.fromstring("""
      <edgarSubmission><formData><coverPageHeader>
        <issuerInfo><issuerCik>0001144879</issuerCik></issuerInfo>
      </coverPageHeader></formData></edgarSubmission>""")
    check("THE 13G LOWERCASE SPELLING IS HONOURED",
          fs.subject_cik(G13) == 1144879,
          "issuerCik against issuerCIK; the split runs on form family")

    NS = ET.fromstring("""
      <edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13">
        <formData><coverPageHeader>
          <issuerInfo><issuerCIK>0001812477</issuerCIK></issuerInfo>
        </coverPageHeader></formData></edgarSubmission>""")
    check("a namespaced document still resolves",
          fs.subject_cik(NS) == 1812477,
          "tag_of strips the namespace; without it every tag is a URL")

    NONE = ET.fromstring("<edgarSubmission><formData/></edgarSubmission>")
    check("a document that names no issuer returns None, not a guess",
          fs.subject_cik(NONE) is None,
          "the caller refuses rather than falling back on the index")
    EMPTY = ET.fromstring("""
      <edgarSubmission><issuerInfo><issuerCIK>  </issuerCIK></issuerInfo>
      </edgarSubmission>""")
    check("AN EMPTY ELEMENT IS None, NOT ZERO",
          fs.subject_cik(EMPTY) is None,
          "0 compares unequal to every roster CIK, so it would report the "
          "whole corpus as misattributed")
    TWO = ET.fromstring("""
      <edgarSubmission><issuerInfo>
        <issuerCIK></issuerCIK><issuerCIK>0001591956</issuerCIK>
      </issuerInfo></edgarSubmission>""")
    check("an empty element does not stop a later one being read",
          fs.subject_cik(TWO) == 1591956)

    check("ZERO PADDING DOES NOT CHANGE THE ANSWER",
          fs.as_cik("0001755953") == fs.as_cik("1755953") == 1755953,
          "watchlist pads to ten, EDGAR writes both in one payload")
    check("a non-numeric CIK is None", fs.as_cik("n/a") is None)
    check("an absent CIK is None", fs.as_cik(None) is None)

    print("\nfilings.recent IS A WINDOW, NOT THE INDEX")
    # CoreWeave's printed structured count fell 32, 35, 25, 23, 23, 23 across
    # scheduled runs from 2026-08-14 to 2026-09-09 while three NEW filings
    # arrived. A count going down reads as a data correction rather than as a
    # truncated page. Five roster companies have a second index page.
    calls = []

    def fake_get(url, as_json=True):
        calls.append(url)
        if url.endswith("CIK0000000001.json"):
            return {"filings": {
                "recent": {"form": ["SCHEDULE 13D", "8-K"],
                           "filingDate": ["2026-09-01", "2026-08-01"],
                           "accessionNumber": ["A-1", "X-1"],
                           "primaryDocument": ["a.xml", "x.htm"]},
                "files": [{"name": "CIK0000000001-submissions-001.json"}]}}
        return {"form": ["SCHEDULE 13G", "10-K"],
                "filingDate": ["2025-01-01", "2024-01-01"],
                "accessionNumber": ["B-1", "Y-1"],
                "primaryDocument": ["b.xml", "y.htm"]}

    saved_get, saved_gap = he.sec_get, he.REQUEST_GAP
    he.sec_get, he.REQUEST_GAP = fake_get, 0
    try:
        rows = he.filings_for("0000000001")
    finally:
        he.sec_get, he.REQUEST_GAP = saved_get, saved_gap
    accs = {r["accession"] for r in rows}
    check("THE OLDER INDEX PAGE IS REQUESTED",
          any("submissions-001" in u for u in calls),
          f"requested {len(calls)} url(s)")
    check("AND ITS ROWS COME BACK",
          "B-1" in accs,
          "requesting the page and dropping its rows would pass a "
          "call-count check on its own")
    check("the recent page's rows are still there", "A-1" in accs)
    check("non-13D/G forms are filtered on BOTH pages",
          "X-1" not in accs and "Y-1" not in accs,
          f"got {sorted(accs)}")

    # A short parallel column reaches this as an empty string rather than an
    # error. Measured 0 ragged columns across all 22 CIKs on 2026-09-10, so
    # this guard has never fired; that is a reason to check it, not to drop it.
    def ragged_get(url, as_json=True):
        return {"filings": {"recent": {
            "form": ["SCHEDULE 13D"], "filingDate": [],
            "accessionNumber": ["A-1"], "primaryDocument": []}}}
    saved_get = he.sec_get
    he.sec_get = ragged_get
    try:
        rows = he.filings_for("0000000002")
        ok, why = rows and rows[0]["filed"] == "", f"got {rows}"
    except Exception as e:                                      # noqa: BLE001
        ok, why = False, f"raised {type(e).__name__}"
    finally:
        he.sec_get = saved_get
    check("A SHORT COLUMN YIELDS AN EMPTY FIELD, NOT AN IndexError", ok, why)

    print("\nTHREE OUTCOMES, NOT ONE BARE None")
    # A fetch failure logged a line; a document that parsed but held no known
    # reporting-person block returned the SAME bare None in silence, and the
    # caller could not tell them apart. A block-name rename at EDGAR hits every
    # filing at once, so the component would go quiet while the per-company
    # counts read normally and the run stayed green.
    def as_get(xml):
        def go(url, as_json=True):
            if isinstance(xml, Exception):
                raise xml
            return xml
        return go

    row = {"accession": "0000950170-25-114068", "doc": "primary_doc.xml"}
    saved = he.sec_get
    try:
        he.sec_get = as_get(RuntimeError("boom"))
        rec, why = he.read_filing("0001964789", row)
        check("A FETCH FAILURE NAMES THE EXCEPTION",
              rec is None and "RuntimeError" in why, why)
        fetch_why = why

        he.sec_get = as_get(
            "<edgarSubmission><formData><somethingElse>"
            "<newBlockName>X</newBlockName></somethingElse>"
            "</formData></edgarSubmission>")
        rec, why = he.read_filing("0001964789", row)
        check("A DOCUMENT WITH NO KNOWN BLOCK NAMES THE TAGS PRESENT",
              rec is None and "newBlockName" in why,
              "after a rename the useful question is what it is called now")
        check("and it is distinguishable from a fetch failure",
              why != fetch_why and "no reporting-person block" in why)

        he.sec_get = as_get("""
          <edgarSubmission><formData><coverPageHeader>
            <issuerInfo><issuerCIK>0001755953</issuerCIK></issuerInfo>
            <reportingPersonInfo>
              <reportingPersonName>Hut 8 Corp.</reportingPersonName>
              <percentOfClass>64.5</percentOfClass>
            </reportingPersonInfo>
            <reportingPersonInfo>
              <reportingPersonName>U.S. Data Mining Group, Inc.</reportingPersonName>
              <percentOfClass>12.0</percentOfClass>
            </reportingPersonInfo>
            <dateOfEvent>09/03/2025</dateOfEvent>
          </coverPageHeader></formData></edgarSubmission>""")
        rec, why = he.read_filing("0001964789", row)
        check("a readable filing returns a record and no reason",
              rec is not None and why is None)
        check("THE PERCENT IS THE LARGEST SIGNATORY'S, NOT A SUM",
              rec["pct"] == 64.5,
              "the members report overlapping slices of one position; "
              "76.5 would double-count")
        check("the subject rides along from the same document",
              rec["subject"] == 1755953)
        check("the event date parses from the US format",
              str(rec["event"]) == "2025-09-03")
        check("both signatories are read", len(rec["people"]) == 2)

        # A block with no name is skipped while the rest of the group is kept,
        # so the signature comes out short. Never measured before today.
        he.sec_get = as_get("""
          <edgarSubmission><reportingPersonInfo>
            <reportingPersonName></reportingPersonName>
            <percentOfClass>5.0</percentOfClass>
          </reportingPersonInfo><reportingPersonInfo>
            <reportingPersonName>Real Holder LP</reportingPersonName>
            <percentOfClass>6.0</percentOfClass>
          </reportingPersonInfo></edgarSubmission>""")
        rec, why = he.read_filing("0001964789", row)
        check("AN UNNAMED BLOCK IS COUNTED, NOT IGNORED",
              rec is not None and rec["unnamed_blocks"] == 1,
              "the group reads short and could look like an arrival later")
        check("and the named signatory is still read",
              rec["people"] == ["Real Holder LP"])
    finally:
        he.sec_get = saved

    print("\nAN UNREADABLE FILING IS ONLY MARKED SEEN IF IT COULD NOT POST")
    # The naive fix, moving the append below the None check unconditionally,
    # reads as the obvious correction and is worse: `measured` and state["read"]
    # are written the instant the submissions request returns, so a company
    # whose index read fine is recorded established however many documents
    # failed. Its unreadable back catalogue would then post one run after the
    # suppression window closed.
    ARGS = dict(first_run=False, backfill=False, newly_watched=set(),
                newly_forms=set(), old_forms={"SCHEDULE 13D", "SCHEDULE 13G"})
    check("AN ORDINARY RUN LEAVES IT UNSEEN, so it retries",
          he.suppressed_run("CORZ", "SCHEDULE 13D", **ARGS) is False)
    check("a cold start marks it seen",
          he.suppressed_run("CORZ", "SCHEDULE 13D", **{**ARGS, "first_run": True}))
    check("a roster backfill marks it seen",
          he.suppressed_run("CORZ", "SCHEDULE 13D", **{**ARGS, "backfill": True}))
    check("A NEWLY WATCHED COMPANY MARKS IT SEEN",
          he.suppressed_run("CORZ", "SCHEDULE 13D",
                            **{**ARGS, "newly_watched": {"CORZ"}}),
          "this is the 2026-08-14 axis, and the reason the append is paired")
    check("another company being new does not",
          he.suppressed_run("CORZ", "SCHEDULE 13D",
                            **{**ARGS, "newly_watched": {"CRWV"}}) is False)
    check("A NEWLY TRACKED FORM PREFIX MARKS IT SEEN",
          he.suppressed_run("CORZ", "SCHEDULE 13G",
                            **{**ARGS, "newly_forms": {"SCHEDULE 13G"},
                               "old_forms": {"SCHEDULE 13D"}}),
          "the capability axis, reached by editing a constant")
    check("a form the PREVIOUS set already matched is not new",
          he.suppressed_run("CORZ", "SCHEDULE 13D/A",
                            **{**ARGS, "newly_forms": {"SCHEDULE 13D/A"},
                               "old_forms": {"SCHEDULE 13D"}}) is False,
          "adding 13D/A beside 13D adds no filings, so nothing may go quiet")

    print("\nA FAILED POST MUST LEAVE NO TRACE")
    # Un-marking `seen` was only half of it. The baseline was already advanced
    # for the event, so the retry re-reads the same filing as a zero-point move
    # and drops it as sub-floor: un-marked, re-fetched, silently never posted.
    # Inert until the workflow stopped discarding a failed run's state, which
    # is why the two changed together.
    row = {"accession": "ACC-1", "form": "SCHEDULE 13D", "filed": "2026-09-01"}
    st = {"seen": ["OLD-1"], "holders": {"CORZ|Two Seas Capital LP": 6.0},
          "era": {}, "read": {}}
    before = json.dumps(st, sort_keys=True)
    st["seen"].append("ACC-1")
    st["holders"]["CORZ|Two Seas Capital LP"] = 9.0        # a CHANGE was built
    he.undo_event(st, row, 6.0, "CORZ|Two Seas Capital LP")
    check("the accession is un-marked", "ACC-1" not in st["seen"])
    check("THE BASELINE GOES BACK TO WHAT IT PUBLISHED",
          st["holders"]["CORZ|Two Seas Capital LP"] == 6.0,
          "left at 9.0 the retry is a zero-point move and never posts")
    check("STATE IS BYTE-IDENTICAL TO BEFORE THE EVENT",
          json.dumps(st, sort_keys=True) == before,
          "anything left behind is a difference the retry cannot see")

    # An arrival had no key beforehand, so the key GOES rather than being set
    # to None: a key present with a null value matches on the next run and
    # classifies as a change against nothing.
    st = {"seen": [], "holders": {}, "era": {}, "read": {}}
    before = json.dumps(st, sort_keys=True)
    st["seen"].append("ACC-2")
    st["holders"]["NUAI|New Holder LP"] = 7.5
    he.undo_event(st, {"accession": "ACC-2"}, None, "NUAI|New Holder LP")
    check("AN ARRIVAL'S KEY IS REMOVED, NOT NULLED",
          "NUAI|New Holder LP" not in st["holders"],
          "a null-valued key matches next run and reads as a change")
    check("and that state is byte-identical too",
          json.dumps(st, sort_keys=True) == before)

    print("\nTHE STATE FILE IS WRITTEN ATOMICALLY")
    # always() on the persist step means a run killed mid-write now reaches
    # `git add`. A truncated file commits, and the next run reads a JSON error
    # and starts from nothing: a cold start reached by a clock.
    path = os.environ["HOLDER_STATE"]
    st = {"seen": ["A-1"], "holders": {}, "era": {}, "read": {}}
    # Wrapped, and read with .get: the mutations that prove this one write
    # truncated or empty content, and both would raise before the check could
    # report. A mutation that crashes the harness has shown nothing.
    back, leftovers, err = None, None, None
    try:
        he.save_state(st)
        with open(path, encoding="utf-8") as fh:
            back = json.load(fh)
        leftovers = os.path.exists(path + ".tmp")
    except Exception as e:                                      # noqa: BLE001
        err = type(e).__name__
    finally:
        for f in (path, path + ".tmp"):
            if os.path.exists(f):
                os.remove(f)
    check("the file reads back as JSON, with the state in it",
          isinstance(back, dict) and back.get("seen") == ["A-1"],
          err or f"got {back}")
    check("NO TEMPORARY FILE IS LEFT BEHIND", not leftovers,
          "os.replace is the rename that makes the write atomic")

    print("\nTHE EVENT RECORD AND ITS READERS STAY IN STEP")
    # A LIVE CRASH, and neither the suite nor four green dry runs caught it.
    # `key` was appended to the event tuple so a failed post could undo the
    # baseline write; one of the two loops that unpack it was updated and the
    # other was not, so a run with at least one event raised ValueError. Every
    # dry run printed "0 event(s) to post", and a `for` over an empty list
    # never unpacks anything. Both loops live inside main(), so nothing here
    # can exercise them. What CAN be asserted is that the record and its
    # readers agree, which is the actual bug class.
    fields = he.Event._fields
    check("the event record carries the key the rollback needs",
          "key" in fields, ", ".join(fields))
    params = list(inspect.signature(he.build_embed).parameters)
    check("BUILD_EMBED'S PARAMETERS ARE THE EVENT'S LEADING FIELDS, IN ORDER",
          list(fields[:len(params)]) == params,
          f"event {fields[:len(params)]} against embed {tuple(params)}")
    check("and key is not one of them",
          "key" not in params,
          "it is state bookkeeping, not something the reader sees")

    # The two first-run filters read the record. They are pure and take a list,
    # so unlike the loops they CAN be exercised.
    e1 = he.Event("CORZ", "Core Scientific", {"form": "SCHEDULE 13D"},
                  he.CHANGE, ["A LP"], 6.0, 5.0, None, None, "CORZ|A LP")
    e2 = he.Event("CRWV", "CoreWeave", {"form": "SCHEDULE 13G"},
                  he.ARRIVAL, ["B LP"], 7.0, None, None, None, "CRWV|B LP")
    kept, per = he.drop_newly_watched([e1, e2], {"CRWV"})
    check("a newly watched company's events are dropped by name",
          [e.ticker for e in kept] == ["CORZ"] and per["CRWV"] == 1)
    kept, per = he.drop_newly_tracked([e1, e2], {"SCHEDULE 13G"},
                                      {"SCHEDULE 13D"})
    check("a newly tracked form's events are dropped by name",
          [e.ticker for e in kept] == ["CORZ"] and per["SCHEDULE 13G"] == 1,
          "this reads e.row['form'], which was e[2]['form'] positionally")

    print("\nTHE ONE-SHOT REPAIR, WHICH DELETES STORED RECORDS")
    # Every arm of this is exercised with the network stubbed, because it is
    # the only code in the component that destroys, and a dry run against live
    # data rehearses only the path the live data happens to take.
    RIOT_CIK, BITFARMS = "0001167419", 1812477

    def run_repair(state, listed, docs, rows=None, dry=False):
        """repair_misattribution with filings_for and read_filing stubbed."""
        saved = (he.MISATTRIBUTED, he.DRY_RUN, he.filings_for, he.read_filing,
                 he.REQUEST_GAP)
        he.MISATTRIBUTED = tuple(listed)
        he.DRY_RUN = dry
        he.REQUEST_GAP = 0
        he.filings_for = lambda cik: rows if rows is not None else [
            {"form": "SCHEDULE 13D", "filed": "2025-04-09",
             "accession": a, "doc": "primary_doc.xml"} for _c, a in listed]
        he.read_filing = lambda cik, row: docs[row["accession"]]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                he.repair_misattribution(state)
        finally:
            (he.MISATTRIBUTED, he.DRY_RUN, he.filings_for, he.read_filing,
             he.REQUEST_GAP) = saved
        return buf.getvalue()

    def doc(subject, people, pct):
        return ({"people": people, "pct": pct, "event": None,
                 "subject": subject, "unnamed_blocks": 0}, None)

    # NINE FILINGS, ONE SIGNATURE. Deleting inside the confirm pass popped the
    # key on the first and reported the other eight as "wrote no holder
    # record", which is false and reads as eight harmless no-ops.
    accs = [f"0001104659-25-0{n}" for n in range(10001, 10010)]
    st = {"seen": [], "holders": {"RIOT|Riot Platforms, Inc.": 4.6},
          "era": {"RIOT": "2025-04-09"}, "read": {}, "repairs": [],
          "not_subject": []}
    log = run_repair(st, [(RIOT_CIK, a) for a in accs],
                     {a: doc(BITFARMS, ["Riot Platforms, Inc."], 4.6)
                      for a in accs})
    check("NINE FILINGS ON ONE KEY ARE ONE DELETION, NOT ONE PLUS EIGHT",
          "1 holder record(s) deleted, covering 9 filing(s)" in log,
          "the earlier shape reported eight phantom absences")
    check("the wrong record is gone",
          "RIOT|Riot Platforms, Inc." not in st["holders"])
    check("every confirmed accession is recorded as not-ours",
          set(st["not_subject"]) == set(accs),
          "this is what stops main() pulling the era floor back")
    check("a clean repair records its sentinel",
          he.REPAIR_ID in st["repairs"])

    # THE FLOOR MUST MOVE FORWARD. era is min() everywhere else, so only an
    # explicit overwrite can correct one.
    rows = [{"form": "SCHEDULE 13D", "filed": "2025-04-09",
             "accession": accs[0], "doc": "d"},
            {"form": "SCHEDULE 13G", "filed": "2025-05-12",
             "accession": "GOOD-1", "doc": "d"}]
    st = {"seen": [], "holders": {}, "era": {"RIOT": "2025-04-09"},
          "read": {}, "repairs": [], "not_subject": []}
    log = run_repair(st, [(RIOT_CIK, accs[0])],
                     {accs[0]: doc(BITFARMS, ["Riot Platforms, Inc."], 4.6)},
                     rows=rows)
    check("THE ERA FLOOR IS OVERWRITTEN FORWARD",
          st["era"]["RIOT"] == "2025-05-12",
          f"got {st['era']['RIOT']}; min() can only ever move it earlier")
    check("and the move is printed with a count",
          "2025-04-09 -> 2025-05-12" in log and "1 kept of 2 structured" in log)
    # The other half: main() must not pull it back.
    check("MAIN'S FLOOR HONOURS THE EXCLUSION",
          he.era_floor(rows, set(st["not_subject"])) == ["2025-05-12"],
          "without this the next run recomputes 2025-04-09 and min() keeps it")

    # A REFUSAL POISONS THE WHOLE COMPANY. Moving a floor forward on a disputed
    # measurement is the one thing era can never undo.
    st = {"seen": [], "holders": {}, "era": {"RIOT": "2025-04-09"},
          "read": {}, "repairs": [], "not_subject": []}
    # The index must carry BOTH, or the refusal that fires is "not on this
    # company's index" and the check passes for the wrong reason. It did on the
    # first run of this check.
    both = rows + [{"form": "SCHEDULE 13D", "filed": "2025-06-01",
                    "accession": accs[1], "doc": "d"}]
    log = run_repair(st, [(RIOT_CIK, accs[0]), (RIOT_CIK, accs[1])],
                     {accs[0]: doc(BITFARMS, ["Riot Platforms, Inc."], 4.6),
                      accs[1]: doc(int(RIOT_CIK), ["Riot Platforms, Inc."], 4.6)},
                     rows=both)
    check("A FILING THAT IS ABOUT THIS COMPANY IS REFUSED",
          "IS about RIOT after all" in log)
    check("and its company's era is left alone",
          st["era"]["RIOT"] == "2025-04-09" and "SKIPPED" in log)
    check("A REFUSAL WITHHOLDS THE SENTINEL",
          he.REPAIR_ID not in st["repairs"] and "SENTINEL WITHHELD" in log,
          "otherwise fifteen refusals would record the repair as done")

    # THE VALUE GUARD. If the stored percentage is not one this group ever
    # filed here, something else wrote it and deleting takes a live position.
    st = {"seen": [], "holders": {"RIOT|Riot Platforms, Inc.": 12.0},
          "era": {}, "read": {}, "repairs": [], "not_subject": []}
    log = run_repair(st, [(RIOT_CIK, accs[0])],
                     {accs[0]: doc(BITFARMS, ["Riot Platforms, Inc."], 4.6)})
    check("A STORED VALUE THE GROUP NEVER FILED IS REFUSED",
          st["holders"].get("RIOT|Riot Platforms, Inc.") == 12.0
          and "stored 12.0" in log,
          "deleting it would take a position something else wrote")

    # A dry run rehearses and commits to nothing.
    st = {"seen": [], "holders": {"RIOT|Riot Platforms, Inc.": 4.6},
          "era": {}, "read": {}, "repairs": [], "not_subject": []}
    log = run_repair(st, [(RIOT_CIK, accs[0])],
                     {accs[0]: doc(BITFARMS, ["Riot Platforms, Inc."], 4.6)},
                     dry=True)
    check("A DRY RUN WRITES NO SENTINEL",
          he.REPAIR_ID not in st["repairs"] and "DRY RUN" in log,
          "so the next dry run rehearses it again")
    check("the sentinel makes it run exactly once",
          run_repair({"repairs": [he.REPAIR_ID]}, [], {}) == "")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
