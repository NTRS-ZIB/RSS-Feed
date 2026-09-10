#!/usr/bin/env python3
"""Tests for regsho_volume's pure functions. Standalone, no network.

`requests` is stubbed below because regsho_volume imports it at module scope
and nothing tested here calls it. Remove the stub rather than extending it if a
test ever needs a fetching function: a stub that grows is a stub that hides
things.

THE ONE THAT MATTERS: short exempt volume is a SUBSET of short volume, not an
addition to it. From the component's first commit until 2026-09-10, parse()
did `bucket[0] += short + exempt`, double-counting every exempt share, and the
component doc asserted it "belongs in the numerator" and was "normally a
rounding error". Neither was true: 43% of live rows carry a non-zero exempt,
and the component published VIP at 167.6% of its own total volume, BGDE at
108%, and GLXY at 83.6% against a true 60.7% while calling it the day's
largest mover. An impossible ratio sat in a public channel for weeks and no
check anywhere objected, because there were no checks. This file is those
checks.
"""

import io
import contextlib
import sys
import types

sys.modules.setdefault("requests", types.ModuleType("requests"))

import regsho_volume as rv

PASS, FAIL = "PASS", "FAIL"
results = []

SYM = "securitiesInformationProcessorSymbolIdentifier"
DAY = "tradeReportDate"
SHORT = "shortParQuantity"
EXEMPT = "shortExemptParQuantity"
TOTAL = "totalParQuantity"


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def row(sym, day, short, exempt, total):
    return {SYM: sym, DAY: day, SHORT: short, EXEMPT: exempt, TOTAL: total}


def parsed(rows):
    """parse() with its stdout captured, so a guard line does not pollute."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = rv.parse(rows)
    return out, buf.getvalue()


def main():
    print("SHORT EXEMPT IS INSIDE SHORT, NOT BESIDE IT")
    # The regression fixture is the real row that produced the worst published
    # figure: VIP on 2026-08-03. The old arithmetic made this 167.6%, which is
    # more short volume than there was volume.
    out, _ = parsed([row("VIP", "2026-08-03", 15426, 14926, 18106)])
    short, total = out["VIP"]["2026-08-03"]
    check("THE REAL VIP ROW IS 85.2%, NOT 167.6%",
          abs(short / total * 100 - 85.2) < 0.1,
          f"got {short / total * 100:.1f}%; `short + exempt` gives 167.6%")
    check("exempt is not added to the numerator",
          short == 15426,
          "adding it would give 30,352")
    check("total is untouched by exempt",
          total == 18106)

    # A ratio above 100% is arithmetically impossible for a subset. This is the
    # cheapest statement of the whole bug, and nothing anywhere made it.
    out, _ = parsed([row("BGDE", "2026-08-31", 32343, 8013, 37360)])
    s, t = out["BGDE"]["2026-08-31"]
    check("a published ratio cannot exceed 100%",
          s / t * 100 <= 100.0,
          f"got {s / t * 100:.1f}%; the old code published 108.0%")

    print("\nAGGREGATION ACROSS REPORTING FACILITIES")
    # FINRA reports one symbol-day once per facility, so the rows must sum.
    # This is the behaviour the exempt fix must not have broken.
    out, _ = parsed([
        row("BGDE", "2026-09-01", 1000, 100, 4000),
        row("BGDE", "2026-09-01", 500, 50, 2000),
    ])
    s, t = out["BGDE"]["2026-09-01"]
    check("short sums across facilities", s == 1500)
    check("total sums across facilities", t == 6000)
    check("the summed ratio is 25%, not 27.5%",
          abs(s / t * 100 - 25.0) < 1e-9,
          "27.5% is what adding the two exempt values would give")

    print("\nTHE CONTAINMENT GUARD")
    # Both of these are impossible while exempt <= short <= total. Either one
    # firing means a FINRA field has changed meaning, which is exactly the
    # failure this component could not see for itself.
    _, log = parsed([row("BGDE", "2026-09-01", 9000, 0, 4000)])
    check("SHORT ABOVE TOTAL IS REPORTED",
          "IMPOSSIBLE" in log and "short above total" in log,
          "silence here is how the original bug survived")
    _, log = parsed([row("BGDE", "2026-09-01", 100, 900, 4000)])
    check("EXEMPT ABOVE SHORT IS REPORTED",
          "IMPOSSIBLE" in log and "exempt above short" in log,
          "this is the assumption the fix rests on, so it is checked")
    _, log = parsed([row("BGDE", "2026-09-01", 1000, 100, 4000)])
    check("an ordinary row says nothing",
          "IMPOSSIBLE" not in log,
          "a guard that fires on healthy data is noise")

    print("\nROWS THAT MUST BE SKIPPED")
    out, _ = parsed([row("BGDE", "2026-09-01", 100, 0, 0)])
    check("a row with no total volume is dropped",
          "BGDE" not in out,
          "it would divide by zero")
    out, _ = parsed([row("NOTATICKER", "2026-09-01", 100, 0, 4000)])
    check("a symbol not on the roster is dropped",
          out == {})

    print("\nTHRESHOLDS")
    series = {"2026-09-01": (1000.0, 10_000.0)}
    check("a day below MIN_TOTAL_VOLUME is not summarised",
          rv.summarise(series, "2026-09-01") is None,
          f"floor is {rv.MIN_TOTAL_VOLUME:,}")
    series = {"2026-09-01": (30_000.0, 100_000.0)}
    m = rv.summarise(series, "2026-09-01")
    check("a day above it is summarised at the right ratio",
          m is not None and abs(m["ratio"] - 30.0) < 1e-9)
    check("a single session has no average to compare against",
          m["avg"] is None and m["delta"] is None,
          "one day is not a baseline")
    check("a baseline of one session is thin",
          rv.thin_baseline({"sessions": 1}),
          f"floor is {rv.MIN_BASELINE_SESSIONS} sessions")
    check("a full baseline is not thin",
          not rv.thin_baseline({"sessions": rv.MIN_BASELINE_SESSIONS}))

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
