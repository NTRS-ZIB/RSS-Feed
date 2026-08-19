#!/usr/bin/env python3
"""Characterisation corpus for the shared filing-cadence rule.

WHAT IT MEASURES, AND WHY IT IS NOT A SUITE
`filing_cadence.cadence()` is the decision; `earnings_calendar.project()` and
`build_snapshot.projection()` are its two presentations. One reaches Discord,
the other reaches `snapshot.json`, a wire format another project reads every
weekday. `test_filing_cadence.py` and `test_build_snapshot.py` say what those
three SHOULD do on the cases somebody thought of. This says what they DO do,
over 7,700 generated ones, so that a change to any of them is measured before
it ships rather than after.

Run it, change the code, run it again. It names every case whose output moved,
across all three functions at once.

    python probe_cadence_corpus.py            # working tree against HEAD
    python probe_cadence_corpus.py main       # working tree against a ref
    python probe_cadence_corpus.py --branches # coverage only, no comparison

Exit 0 nothing moved, 1 something moved, 2 THE RUN MEASURED NOTHING.

TWO WAYS THE OUTPUT MEANS NOTHING, AND BOTH LOOK LIKE A PASS
This is the whole reason the file is worth committing, and the reason its
predecessor in scratch was rewritten before it was.

  * A GRID THAT CANNOT REACH A BRANCH REPORTS ZERO DIFFERENCES FOR IT. The
    first version of this corpus put 3,382 cases through `project()`, reported
    no differences, and reached the two branches most likely to move exactly
    zero times: it anchored the quarterly and annual periods on the same
    fiscal month, so `upcoming.month == fy_month` was structurally impossible.
    That result was presented as strong evidence and was worth nothing. So
    coverage over BRANCHES is asserted rather than hoped for, and a branch
    reached zero times exits 2 with no difference count printed.
  * A COMPARISON AGAINST AN IDENTICAL BASELINE REPORTS ZERO DIFFERENCES FOR
    EVERY BRANCH. On a clean tree the ref side and the working-tree side are
    the same code, and "0 differences" is then a fact about `git` rather than
    about the rule. That also exits 2, saying so.

HOW THE BASELINE IS BUILT, AND WHY IT IS NOT AN IMPORT
The ref's root-level `*.py` are written to a temporary directory and run in a
SEPARATE PROCESS. Loading them into this one does not work, and it fails
quietly: both callers do `from filing_cadence import ...`, so an old
`earnings_calendar` exec'd here would bind to the WORKING TREE's
`filing_cadence` already sitting in `sys.modules`, and the run would compare
an old caller against a new shared rule while reporting itself as a clean
before-and-after.

THE GRID COMES FROM ONE SIDE AND THE MODULES FROM TWO. This file is copied
over the ref's copy of itself before the baseline runs, so both sides put the
same cases through different code. A grid that changed with the ref would
report differences it had manufactured.

Bytecode caches are cleared before each side runs. CPython invalidates on the
source's mtime and size, so two edits of the same length within one second are
indistinguishable to it and the second run silently re-executes the first;
that has happened in this repo, and the wrong answer looked like a real
measurement.

THREE BRANCHES ARE ABSENT FROM `BRANCHES` BECAUSE THEY CANNOT BE REACHED, and
they are named here so the next reader does not spend an afternoon building a
case for them. All three are defensive and harmless; none is a defect.

  * `filing_cadence.cadence`, the SECOND `if len(pool) < 2: return None`. It
    sits on the path where `len(quarterly) >= 2` is already established, so
    the fallback above it can always choose `quarterly` and satisfy it.
  * `build_snapshot.projection`, the `else None` arm of `spread`. Every path
    reaching it has a pool of at least two, so `len(lags) > 1` always holds.
  * `build_snapshot.projection`, `c["sample"] < 2` in the confidence
    expression, unreachable for the same reason.

TEMPORARY is what the other probes say about themselves. This one is not: it
is the before-and-after for a rule two live outputs depend on, and it is worth
keeping for as long as they are.
"""

import datetime
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile

D = datetime.date
TD = datetime.timedelta

# Both callers refuse to load without it and neither fetches at import, so
# this is a placeholder rather than a secret, the same shape the offline
# suites use.
os.environ.setdefault("SEC_USER_AGENT", "probe-cadence-corpus tests@example.invalid")

import build_snapshot as bs
import earnings_calendar as ec
import filing_cadence as fc

REPO = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.basename(os.path.abspath(__file__))

# The files whose behaviour this measures. If none of them differs from the
# ref, the comparison is between a module and itself.
SURFACE = ("filing_cadence.py", "earnings_calendar.py", "build_snapshot.py")

# Every branch the corpus claims to exercise. Zero for any one of these means
# the run is not evidence about that branch, whatever the difference count
# says. Read the module docstring before adding to or removing from this.
BRANCHES = (
    "none_below_periodic_floor",
    "none_no_periodic_family",
    "none_annual_below_floor",
    "annual_only",
    "quarterly",
    "annual_on_quarterly_path",
    "degraded",
    "fy_month_unknown",
    "period_end_december",
    "annual_period_29_feb",
    "expected_rolled_off_weekend",
    "project_kind_10q",
    "project_kind_annual",
    "project_spread_wide",
    "snapshot_unavailable",
    "snapshot_confidence_normal",
    "snapshot_low_via_spread",
    "snapshot_low_via_degraded",
)


# Per-filing offsets applied to a case's base lag, cycling over the filings in
# each form family.
#
# WITHOUT THESE THE CORPUS IS BLIND TO SPREAD. Every case used to hold its lag
# constant within a pool, so `max(lags) - min(lags)` was zero for all but four
# of 2,574 cases: `snapshot.low_via_spread` was reached three times, the
# `~` marker in `earnings_calendar` never, and a change to either would have
# been measured over a population where the quantity does not vary. Reaching a
# branch is the weaker claim, and it was the only one the guard could make.
#
# Found by putting a real candidate change through the corpus. The result read
# as "4 of 2,574 cases moved, one shape", which is a true statement about a
# grid that cannot see the field being changed.
#
# The tight pattern stays inside the 30-day thresholds and the wide one clears
# both; the flat one keeps the original zero-spread population rather than
# replacing it, because a spread of zero is the common real case.
JITTERS = (
    (0, 0, 0, 0, 0, 0),
    (0, 6, -4, 9, -7, 3),
    (0, 25, -15, 40, -30, 12),
)


def month_end(year, month):
    """Last day of a month, crossing the year for December."""
    if month == 12:
        return D(year, 12, 31)
    return D(year, month + 1, 1) - TD(days=1)


def grid():
    """The cases, newest first within each form family.

    That is the order `earnings_calendar.periodic_filings` returns and the
    order `cadence` truncates positionally at LAG_SAMPLE. `cadence`
    deliberately does not sort, so the order here is part of the input rather
    than a detail of how it was built.
    """
    cases = {}

    # Annual and quarterly anchored INDEPENDENTLY. `qshift` moves the
    # quarterly cycle relative to the fiscal year end; anchoring both on the
    # same month is what left the first version of this corpus unable to enter
    # the is_annual branch at all.
    for n_ann, n_qtr, fy, qshift, al, ql, j in itertools.product(
            range(0, 5), range(0, 7), (12, 5, 6, 2), (0, 1, 2),
            (60, 90, 120), (35, 45), range(len(JITTERS))):
        filings = []
        for i in range(n_ann):
            p = D(2026 - i, fy, 28 if fy == 2 else 30)
            filings.append((p, p + TD(days=al + JITTERS[j][i % len(JITTERS[j])]), "10-K"))
        for i in range(n_qtr):
            m = fy - 3 * i - qshift
            y = 2026 + (m - 1) // 12
            m = (m - 1) % 12 + 1
            p = D(y, m, 28)
            filings.append((p, p + TD(days=ql + JITTERS[j][i % len(JITTERS[j])]), "10-Q"))
        cases["a%d_q%d_fy%d_s%d_al%d_ql%d_j%d"
              % (n_ann, n_qtr, fy, qshift, al, ql, j)] = filings

    # TARGETED, because the grid above reaches neither the is_annual nor the
    # degraded branch: it leaves an annual period NEWER than every quarterly
    # one, so `upcoming` never lands on the fiscal month. Real filers are the
    # other way round, with the 10-K covering a year already closed while the
    # quarterlies run ahead of it.
    for fy, n_ann, ql, al, j in itertools.product((12, 5, 6), (1, 2, 3, 5),
                                                  (35, 45), (60, 90),
                                                  range(len(JITTERS))):
        # Newest quarterly one quarter BEFORE the fiscal year end, so the next
        # quarter end lands on it. n_ann == 1 leaves the annual pool too thin
        # to carry a median, which is the degraded branch.
        qm = fy - 3
        qy = 2026 + (qm - 1) // 12
        qm = (qm - 1) % 12 + 1
        filings = []
        for i in range(4):
            m = qm - 3 * i
            y = qy + (m - 1) // 12
            m = (m - 1) % 12 + 1
            pp = D(y, m, 28)
            filings.append((pp, pp + TD(days=ql + JITTERS[j][i % len(JITTERS[j])]), "10-Q"))
        for i in range(n_ann):
            pp = D(2025 - i, fy, 28 if fy == 2 else 30)
            filings.append((pp, pp + TD(days=al + JITTERS[j][i % len(JITTERS[j])]), "10-K"))
        cases["fyend_fy%d_a%d_ql%d_al%d_j%d" % (fy, n_ann, ql, al, j)] = filings

    # Amendments filed long after their period: the shape that separates the
    # two callers' orderings, and the only place their disagreement about
    # which eight filings the median covers can show.
    base = [(D(2026, 6, 30), D(2026, 8, 9), "10-Q"),
            (D(2026, 3, 31), D(2026, 5, 10), "10-Q"),
            (D(2025, 12, 31), D(2026, 2, 20), "10-K"),
            (D(2024, 12, 31), D(2025, 2, 20), "10-K")]
    late = (D(2023, 3, 31), D(2026, 8, 1), "10-Q")
    cases["amend_last"] = base + [late]
    cases["amend_first"] = [late] + base

    # A quarterly cycle ending in September, so `next_period_end` rolls into
    # December and takes the arm that has to cross the year.
    cases["sept_cycle"] = [(month_end(2026, 9), D(2026, 11, 5), "10-Q"),
                           (month_end(2026, 6), D(2026, 8, 5), "10-Q"),
                           (month_end(2026, 3), D(2026, 5, 5), "10-Q")]

    # 29 February, the one period end `next_annual_period_end` cannot simply
    # replace the year on.
    cases["leap_year_end"] = [(D(2024, 2, 29), D(2024, 6, 27), "10-K"),
                              (D(2023, 2, 28), D(2023, 6, 27), "10-K"),
                              (D(2022, 2, 28), D(2022, 6, 27), "10-K")]

    # Two filings of no periodic family at all. The grid cannot express this:
    # it only ever emits 10-K and 10-Q.
    cases["non_periodic_only"] = [(D(2026, 6, 30), D(2026, 7, 1), "8-K"),
                                  (D(2026, 3, 31), D(2026, 4, 1), "8-K")]

    # Lags spread wide enough that HALF the range clears the snapshot's
    # confidence threshold. Every case above holds its lag constant within a
    # pool, so all of them have a spread of zero.
    cases["wide_lags"] = [
        (month_end(2026, 6), month_end(2026, 6) + TD(days=30), "10-Q"),
        (month_end(2026, 3), month_end(2026, 3) + TD(days=120), "10-Q"),
        (month_end(2025, 12), month_end(2025, 12) + TD(days=45), "10-Q"),
        (month_end(2025, 9), month_end(2025, 9) + TD(days=40), "10-Q"),
    ]
    return cases


def encode(v):
    if isinstance(v, D):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [encode(x) for x in v]
    if isinstance(v, dict):
        return {k: encode(x) for k, x in sorted(v.items())}
    return v


def outputs(filings):
    """The three published answers for one case.

    `projection` reads (form, filed, period) out of a wider row and sorts by
    period itself; `project` and `cadence` take the list as given.
    """
    rows = [(form, fd.isoformat(), rd.isoformat(), None, None)
            for rd, fd, form in filings]
    return {
        "cadence": encode(fc.cadence(filings)),
        "project": encode(ec.project("XXXX", "case", filings)),
        "snapshot": encode(bs.projection(rows)),
    }


def branches_of(filings, out):
    """Which of BRANCHES this case reached.

    Derived from the outputs and the input, never from instrumenting the
    modules, so the baseline side of a comparison classifies itself by exactly
    the same rule.
    """
    hit = set()
    c, p, s = out["cadence"], out["project"], out["snapshot"]
    annual = [f for f in filings if f[2] in fc.ANNUAL_FORMS]
    quarterly = [f for f in filings if f[2] in fc.QUARTERLY_FORMS]

    if c is None:
        if len(filings) < fc.MIN_PERIODIC_FILINGS:
            hit.add("none_below_periodic_floor")
        elif not annual and not quarterly:
            hit.add("none_no_periodic_family")
        elif (len(quarterly) < fc.MIN_QUARTERLY_FILINGS
                and len(annual) < fc.MIN_ANNUAL_FILINGS):
            hit.add("none_annual_below_floor")
    else:
        period = D.fromisoformat(c["period"])
        if c["annual_only"]:
            hit.add("annual_only")
            if any(f[0].month == 2 and f[0].day == 29 for f in annual):
                hit.add("annual_period_29_feb")
        elif c["kind"] == "annual":
            hit.add("annual_on_quarterly_path")
        if c["kind"] == "quarterly":
            hit.add("quarterly")
        if c["degraded"]:
            hit.add("degraded")
        if c["fy_month"] is None:
            hit.add("fy_month_unknown")
        if period.month == 12 and not c["annual_only"]:
            hit.add("period_end_december")
        if D.fromisoformat(c["expected"]) != period + TD(days=c["lag"]):
            hit.add("expected_rolled_off_weekend")

    if p is not None:
        hit.add("project_kind_10q" if p["kind"] == "10-Q" else "project_kind_annual")
        # The population the `~` marker fires on. Read through the module's own
        # constant rather than a literal 30, so moving the threshold moves the
        # branch with it instead of silently emptying it.
        if p["spread"] > ec.LOW_CONFIDENCE_SPREAD:
            hit.add("project_spread_wide")

    if not s["available"]:
        hit.add("snapshot_unavailable")
    elif s["confidence"] == "normal":
        hit.add("snapshot_confidence_normal")
    elif (s["spread_days"] or 0) > 30:
        hit.add("snapshot_low_via_spread")
    elif c is not None and c["degraded"]:
        hit.add("snapshot_low_via_degraded")
    return hit


def measure():
    """Every case, its three outputs, and the branch tally."""
    cases, reach = {}, {b: 0 for b in BRANCHES}
    for key, filings in sorted(grid().items()):
        out = outputs(filings)
        cases[key] = out
        for b in branches_of(filings, out):
            reach[b] += 1
    return {"cases": cases, "reach": reach}


def clear_pycache(root):
    shutil.rmtree(os.path.join(root, "__pycache__"), ignore_errors=True)


def emit(path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(measure(), fh)


def git(args):
    """ENCODING IS EXPLICIT, and it has to be. `text=True` alone decodes with
    the locale codec, which on Windows is cp1252: two modules in this repo
    carry bytes it cannot map, and `subprocess` handed back None for those
    rather than raising. A silent None reaches the file write as a TypeError
    several frames away, and the same mismatch made every file with a non
    ASCII character compare unequal to itself, which would have reported the
    working tree as differing from a ref identical to it.
    """
    return subprocess.run(["git"] + args, cwd=REPO, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def surface_differs(ref):
    """True when at least one measured file differs from the ref.

    `git show` rather than `git diff`, so an uncommitted edit and a commit on
    a branch are both seen.
    """
    for name in SURFACE:
        try:
            old = git(["show", "%s:%s" % (ref, name)])
        except subprocess.CalledProcessError:
            return True                   # absent at the ref counts as a change
        with open(os.path.join(REPO, name), encoding="utf-8") as fh:
            if old != fh.read():
                return True
    return False


def measure_side(workdir, label):
    """Run this file's `--emit` inside `workdir` and read the result back."""
    clear_pycache(workdir)
    out = os.path.join(tempfile.mkdtemp(prefix="cadence-out-"), "out.json")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-B", SELF, "--emit", out],
                       cwd=workdir, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        sys.exit("%s side failed to measure:\n%s\n%s" % (label, r.stdout, r.stderr))
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def materialise(ref, dest):
    """The ref's root-level *.py, then THIS file over the top of its own older
    copy, so both sides run the same grid."""
    names = [n for n in git(["ls-tree", "-r", "--name-only", ref]).split()
             if n.endswith(".py") and "/" not in n]
    for n in names:
        # newline="" so the ref's own line endings survive the round trip
        # rather than being rewritten to the platform's.
        with open(os.path.join(dest, n), "w", encoding="utf-8", newline="") as fh:
            fh.write(git(["show", "%s:%s" % (ref, n)]))
    shutil.copyfile(os.path.abspath(__file__), os.path.join(dest, SELF))
    return len(names)


def field_diff(x, y):
    """The keys whose values moved, or one unnamed entry when either side is
    not a dict, which is how an appearing or vanishing projection shows.

    Printing both dicts whole was unreadable: the three functions publish
    about thirty fields between them, and a one day shift in `expected` buried
    itself in two 300-character lines.
    """
    if x == y:
        return []
    if not isinstance(x, dict) or not isinstance(y, dict):
        return [("", x, y)]
    return [(k, x.get(k), y.get(k))
            for k in sorted(set(x) | set(y)) if x.get(k) != y.get(k)]


def report_reach(reach, total):
    print("  %d cases" % total)
    for b in BRANCHES:
        print("    %-30s %5d" % (b, reach.get(b, 0)))
    missed = [b for b in BRANCHES if not reach.get(b)]
    if missed:
        print("\n  NOT EVIDENCE: %d of %d branches were never reached, so this"
              % (len(missed), len(BRANCHES)))
        print("  run says nothing about them and no comparison is printed.")
        print("  " + ", ".join(missed))
    return not missed


def compare(ref):
    if not surface_differs(ref):
        here = measure()
        print("Branch coverage, working tree:")
        report_reach(here["reach"], len(here["cases"]))
        print("\nNOTHING TO COMPARE: %s all match %s, so a difference count"
              % (", ".join(SURFACE), ref))
        print("would be a fact about git rather than about the rule.")
        print("Change the code, or name a ref that predates the change.")
        return 2

    tmp = tempfile.mkdtemp(prefix="cadence-corpus-")
    try:
        n = materialise(ref, tmp)
        print("Baseline: %s, %d modules" % (ref, n))
        old = measure_side(tmp, ref)
        new = measure_side(REPO, "working tree")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nBranch coverage, working tree:")
    covered = report_reach(new["reach"], len(new["cases"]))
    if not covered:
        return 2

    thin = [b for b in BRANCHES if not old["reach"].get(b)]
    if thin:
        print("\n  Baseline never reached %d of them, so those cases are new "
              "rather than moved:" % len(thin))
        print("  " + ", ".join(thin))

    diffs = [(k, old["cases"].get(k), v)
             for k, v in sorted(new["cases"].items()) if old["cases"].get(k) != v]
    print("\n%d of %d cases moved." % (len(diffs), len(new["cases"])))
    if not diffs:
        return 0

    # GROUPED BY SHAPE FIRST, because the count on its own is the least
    # informative number here. A change to the shared rule moves hundreds of
    # cases in a handful of ways, and it is the ways that have to be read: one
    # shape covering 474 cases is a rule that did what was intended, while
    # nine shapes over the same 474 is a rule that did something else too.
    shapes = {}
    for key, a, b in diffs:
        shape = tuple(sorted(
            "%s.%s" % (fn, k) if k else fn
            for fn in ("cadence", "project", "snapshot")
            for k, _, _ in field_diff((a or {}).get(fn), b.get(fn))))
        shapes.setdefault(shape, []).append((key, a, b))

    print("%d distinct shape(s):" % len(shapes))
    for shape, members in sorted(shapes.items(), key=lambda kv: -len(kv[1])):
        key, a, b = members[0]
        print("\n  %d case(s): %s" % (len(members), ", ".join(shape) or "(no fields)"))
        print("    e.g. %s" % key)
        for fn in ("cadence", "project", "snapshot"):
            for k, x, y in field_diff((a or {}).get(fn), b.get(fn)):
                print("      %-26s %s -> %s"
                      % ("%s.%s" % (fn, k) if k else fn,
                         json.dumps(x), json.dumps(y)))
    return 1


def main(argv):
    if len(argv) > 2 and argv[1] == "--emit":
        emit(argv[2])
        return 0
    if len(argv) > 1 and argv[1] == "--branches":
        here = measure()
        print("Branch coverage, working tree:")
        return 0 if report_reach(here["reach"], len(here["cases"])) else 2
    return compare(argv[1] if len(argv) > 1 else "HEAD")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
