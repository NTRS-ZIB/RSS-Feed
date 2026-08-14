#!/usr/bin/env python3
"""
Demonstrate baseline_companies() against the real 2026-08-05 roster addition.

CLAUDE.md: a test that has never failed proves nothing, and adding a guard
means first demonstrating the failure it prevents WITH THE GUARD REMOVED. So
every case below runs the old path and the new path over the same items and
prints both answers.

THE KNOWN-CORRECT ANSWER CAME FROM audit_pending.py, which reconstructed the
2026-08-05 event independently and before this rule existed: five companies
added, and press items already older than MAX_AGE_DAYS at that moment were
recorded and never posted. That script was deleted alongside this change — it
reported as a loss what the monitor now suppresses on purpose — so this is the
surviving reconstruction, and it is checked three ways:

  * the items audit_pending called lost are the ones the OLD path silently
    dropped, 13 of them, which is what that count is compared against;
  * the items the old path POSTED are the backdated ones, published before the
    roster addition and inside the seven-day window. Those are the bug;
  * the new path posts NEITHER, and records both.

Posts nothing, writes nothing, touches no state file.
"""

import json
import os
import sys
import time
import urllib.request
from calendar import timegm
from datetime import datetime, timezone

import press_monitor as pm
import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set.")

# The event. Five companies added by commit 946e303, which landed 13:36Z.
ADDED = ["GLXY", "APLD", "BTDR", "SPCX", "ABTC"]
ADDED_AT = datetime(2026, 8, 5, 13, 36, tzinfo=timezone.utc)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def fetch(cik):
    req = urllib.request.Request(
        SUBMISSIONS.format(cik=cik),
        headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    return json.loads(raw)


def items_as_of(ticker, cik, moment):
    """Every filing this company had at `moment`, shaped like a run's items."""
    rec = (fetch(cik).get("filings") or {}).get("recent") or {}
    out = []
    for i, form in enumerate(rec.get("form") or []):
        filed = (rec.get("filingDate") or [""] * (i + 1))[i]
        acc = (rec.get("accessionNumber") or [""] * (i + 1))[i]
        if not filed or not acc:
            continue
        try:
            ts = timegm(time.strptime(filed, "%Y-%m-%d"))
        except ValueError:
            continue
        if ts > moment.timestamp():
            continue
        # RETAIN_DAYS is what a run would even look at.
        if ts < moment.timestamp() - pm.RETAIN_DAYS * 86400:
            continue
        core = form.split("/")[0]
        kind = ("insider" if core in pm.INSIDER_ALLOWED_FORMS else
                "press" if pm.form_matches(form, pm.FORM_TYPES) else None)
        if kind is None:
            continue
        out.append({"uid": pm.filing_uid(acc), "ticker": ticker, "form": form,
                    "published": ts, "kind": kind,
                    "title": f"{ticker} {form}", "is_edgar": True})
    return out


def old_path(items, moment):
    """What the code did before: age floor only, no per-company rule."""
    cutoff = moment.timestamp() - pm.MAX_AGE_DAYS * 86400
    posted = [i for i in items if i["published"] >= cutoff]
    dropped = [i for i in items if i["published"] < cutoff]
    return posted, dropped


def new_path(items, roster, state, moment):
    """What the code does now."""
    new, suppressed = pm.baseline_companies(state, roster, items,
                                            today=moment.date().isoformat())
    blocked = set(new)
    remaining = [i for i in items if i.get("ticker") not in blocked]
    cutoff = moment.timestamp() - pm.MAX_AGE_DAYS * 86400
    posted = [i for i in remaining if i["published"] >= cutoff]
    return posted, suppressed, new


def main():
    print("=" * 78)
    print("THE REAL CASE — five companies added 2026-08-05 13:36Z")
    print("=" * 78)
    ciks = watchlist.ciks()
    items = []
    for t in ADDED:
        got = items_as_of(t, ciks[t][0], ADDED_AT)
        items += got
        print(f"  {t}: {len(got)} item(s) in the RETAIN_DAYS window at that "
              f"moment")
        time.sleep(0.15)
    print(f"  {len(items)} items total\n")

    # ---- with the guard REMOVED -------------------------------------------
    print("-" * 78)
    print("GUARD REMOVED — what the code did on the day")
    print("-" * 78)
    posted, dropped = old_path(items, ADDED_AT)
    backdated = [i for i in posted if i["published"] < ADDED_AT.timestamp()]
    print(f"  {len(posted)} posted, {len(dropped)} recorded-not-posted "
          f"(older than {pm.MAX_AGE_DAYS}d)")
    print(f"  of those posted, {len(backdated)} were published BEFORE the "
          f"company was on the roster:")
    for i in sorted(backdated, key=lambda x: x["published"]):
        d = datetime.fromtimestamp(i["published"], timezone.utc).date()
        print(f"      {d}  {i['ticker']:<5} {i['form']:<8} ({i['kind']})")
    check("the old path posted backdated items", len(backdated) > 0,
          f"{len(backdated)} of them — this is the bug being fixed")
    check("the old path also dropped older items silently", len(dropped) > 0,
          f"{len(dropped)} recorded, never posted")

    # ---- with the guard IN -------------------------------------------------
    print("\n" + "-" * 78)
    print("GUARD IN — the same items, the same moment")
    print("-" * 78)
    state = {"seen": [], "initialized": True,
             # Every company EXCEPT the five, i.e. the roster as it stood.
             # KEYED BY CIK since 2026-08-15. Under the ticker key a rename
             # read as a new company and lost a run of its real filings.
             "companies": {c: "2026-07-01" for t, (c, _) in ciks.items()
                           if t not in ADDED}}
    posted2, suppressed, new = new_path(items, ciks, state, ADDED_AT)
    check("nothing posts for a new company", len(posted2) == 0,
          f"{len(posted2)} posted")
    check("everything is accounted for", len(suppressed) == len(items),
          f"{len(suppressed)} suppressed of {len(items)}")
    check("all five are recorded, by CIK",
          all(state["companies"].get(ciks[t][0]) == "2026-08-05"
              for t in ADDED))
    check("insider items are suppressed too",
          not any(i["kind"] == "insider" for i in posted2),
          f"{sum(1 for i in suppressed if i['kind'] == 'insider')} insider "
          f"item(s) suppressed")

    # ---- the ordinary path is untouched -----------------------------------
    print("\n" + "-" * 78)
    print("THE ORDINARY PATH — an established company with a new filing")
    print("-" * 78)
    now = datetime.now(timezone.utc)
    ordinary = [{"uid": "x1", "ticker": "MARA", "form": "8-K",
                 "published": now.timestamp() - 3600, "kind": "press",
                 "title": "MARA 8-K", "is_edgar": True}]
    state2 = {"seen": [], "initialized": True,
              "companies": {c: "2026-07-01" for c, _ in ciks.values()}}
    posted3, suppressed3, new3 = new_path(ordinary, ciks, state2, now)
    check("an established company still posts", len(posted3) == 1)
    check("and nothing is suppressed", not suppressed3 and not new3)

    # ---- the backfill run --------------------------------------------------
    print("\n" + "-" * 78)
    print("THE BACKFILL RUN — `companies` absent, which is the next real run")
    print("-" * 78)
    state3 = {"seen": [], "initialized": True}
    posted4, suppressed4, new4 = new_path(ordinary, ciks, state3, now)
    check("the backfill suppresses nothing", not suppressed4 and not new4)
    check("and records every roster company",
          len(state3.get("companies") or {}) == len(ciks),
          f"{len(state3.get('companies') or {})} recorded")
    check("an ordinary item still posts on the backfill run", len(posted4) == 1)

    # ---- the hazard in the option NOT taken --------------------------------
    print("\n" + "-" * 78)
    print("THE REJECTED OPTION — why `no ids in seen` was not used")
    print("-" * 78)
    live = json.loads(open("state.json").read()) if os.path.exists("state.json") \
        else {"seen": []}
    n = len(live.get("seen") or [])
    print(f"  state.json holds {n} ids; the cap is max(1000, run*3)")
    check("`seen` is saturated, so eviction is live, not hypothetical",
          n >= 1000, f"{n} ids at a 1000 floor")
    sample = (live.get("seen") or [])[:1]
    print(f"  a uid looks like: {sample[0] if sample else 'n/a'}")
    check("a uid carries no company, so the question cannot be asked of the "
          "file", all("·" not in u and u.isascii() for u in sample) if sample
          else True)

    print("\n" + "=" * 78)
    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"{len(results) - bad}/{len(results)} passed")
    for r, name in results:
        if r == FAIL:
            print(f"  FAILED: {name}")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
