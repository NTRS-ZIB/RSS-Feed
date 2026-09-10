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

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  ({detail})" if detail else ""))


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

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
