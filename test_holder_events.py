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
            written = json.load(fh)["seen"]
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

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
