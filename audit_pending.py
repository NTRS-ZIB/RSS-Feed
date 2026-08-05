#!/usr/bin/env python3
"""
Filings a roster change put permanently out of reach.

WHAT THIS EXISTS FOR
press_monitor.py marks every item it sees as seen BEFORE it applies the age
floor, so a filing older than MAX_AGE_DAYS at the moment of a run is recorded
and never posted. That is deliberate — it stops a backlog re-flooding the
channel — and it is irreversible.

The loss it produces is not caused by the monitor failing to run. It is caused
by ADDING A COMPANY whose recent filings are already older than MAX_AGE_DAYS.
On 2026-08-05 five companies were added and seven press items were lost that
way. Every one of them had expired BEFORE the roster commit landed:

    APLD 10-K   filed 2026-07-29, expired 2026-08-05 00:00Z
    roster      commit 946e303   landed 2026-08-05 13:36Z

APLD's 10-K was out of reach thirteen hours and thirty-six minutes before the
company was on the roster. No amount of running would have caught it.

WHY IT IS TRIGGERED BY A PUSH AND NOT A CRON
A heartbeat on a schedule was measured and rejected — see docs/rejected.md.
GitHub drops 30-45% of scheduled fires on this repo, so a scheduled checker
inherits exactly the unreliability it exists to report. This one runs on a push
touching watchlist.py, which is not scheduled, and which is the moment the loss
is created rather than some interval afterwards.

WHY IT ONLY LOOKS AT NEWLY ADDED COMPANIES
Two reasons, and the second is what makes it sound rather than merely narrow.

  1. There is no other case. A filing can also be lost if no run happens for
     longer than MAX_AGE_DAYS. That has never occurred: it needs seven days of
     silence against a measured maximum gap of five fire opportunities, about
     five hours. Building for it would be building a tier with no demonstrated
     case, which is the thing this repo keeps deciding not to do.

  2. `seen` cannot produce a false positive here. state.json retains the last
     max(1000, items_this_run * 3) ids and is currently SATURATED at exactly
     1000, so ids are being evicted. An item posted weeks ago but evicted would
     read as unseen. That would be a false positive for a company already on
     the roster — but not for one just added, because press_monitor has never
     queried that CIK, so nothing under it can ever have entered `seen`. The
     trigger removes the dependency rather than managing it.

     Measured 2026-08-05: 253 of the 1000 slots sit before the earliest 2026
     accession, so the eviction frontier is deep in 2007-2025 baseline entries.
     That buffer erodes, which is precisely why correctness does not rest on it.

WHAT IT DOES NOT DO
No at-risk tier. WARN_HOURS below is the constant it would need; the tier is
not built because it would only ever fire on case 1 above, which has never
happened. Add it when it does.

No general framework. An audit of all fourteen components found one with this
failure mode; see the table in docs/press-monitor.md. A population of one does
not want a framework.

    SEC_USER_AGENT="Your Name you@example.com" python -u audit_pending.py

`--since REF` picks the ref the roster is compared against, default HEAD^.
DRY_RUN evaluates and prints without posting. Posts nothing when nothing is
lost, so an ordinary roster edit is silent.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from calendar import timegm
from datetime import date, datetime, timedelta, timezone

# press_monitor owns the uid format and the two windows. Imported rather than
# restated so the two cannot drift: a uid built differently here would compare
# unequal against every id in state.json and report the whole roster as lost.
from press_monitor import MAX_AGE_DAYS, RETAIN_DAYS, FORM_TYPES, filing_uid

# ------------------------------------------------------------------ CONFIG

INSIDER_FORMS = {"3", "4", "5"}

# The at-risk horizon, defined and deliberately unused. See the module
# docstring: the tier it belongs to has no demonstrated case.
WARN_HOURS = 24

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
STATE_FILE = os.environ.get("PRESS_STATE", "state.json")
REQUEST_GAP = 0.15          # under SEC's 10 req/sec ceiling

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_OPS", "").strip()
USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

RED = 0xF85149


# -------------------------------------------------------------- THE ROSTER


def roster_at(ref):
    """{ticker: (cik, name)} as watchlist.py stood at `ref`, or None.

    The file is read out of git and executed in an empty namespace rather than
    imported, so the version on disk is never what is measured. Returns None
    when the ref does not exist, which is the case on the very first commit.
    """
    try:
        src = subprocess.run(["git", "show", f"{ref}:watchlist.py"],
                             capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    ns = {}
    try:
        exec(compile(src, f"<{ref}:watchlist.py>", "exec"), ns)
    except Exception as e:
        print(f"  could not evaluate watchlist.py at {ref}: {type(e).__name__}")
        return None
    return {c["ticker"]: (c["cik"], c["name"]) for c in ns.get("WATCHLIST", [])}


def added_companies(since_ref):
    """Companies present now and absent at `since_ref`."""
    now = roster_at("HEAD")
    if now is None:
        sys.exit("cannot read watchlist.py at HEAD")
    before = roster_at(since_ref)
    if before is None:
        print(f"no roster at {since_ref}; treating every company as new")
        return now
    return {t: v for t, v in now.items() if t not in before}


# ------------------------------------------------------------------- EDGAR


def sec_get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT or "watchlist-monitor contact@example.com",
        "Accept-Encoding": "identity",
        "Host": "data.sec.gov",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8")
    time.sleep(REQUEST_GAP)
    return json.loads(body)


def matches_press(form):
    """The same prefix rule press_monitor applies to a form type."""
    return any(form.startswith(p) for p in FORM_TYPES)


def filings_for(cik, horizon):
    """[(form, filingDate, accession)] filed on or after `horizon`."""
    try:
        data = sec_get(SUBMISSIONS.format(cik=cik.lstrip("0").zfill(10)))
    except Exception as e:
        print(f"    EDGAR failed: {type(e).__name__}")
        return None
    recent = (data.get("filings") or {}).get("recent") or {}
    out = []
    for form, filed, acc in zip(recent.get("form") or [],
                                recent.get("filingDate") or [],
                                recent.get("accessionNumber") or []):
        try:
            if date.fromisoformat(filed) >= horizon:
                out.append((form, filed, acc))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- ANALYSIS


def expires_at(filed):
    """The moment a filing passes the age floor.

    press_monitor's filed_time() parses filingDate, a DATE-ONLY string, so an
    item's published time is midnight UTC of the filing date and its last
    postable moment is midnight UTC, filingDate + MAX_AGE_DAYS. Nothing here
    depends on the acceptance time, which is a different field.
    """
    return date.fromisoformat(filed) + timedelta(days=MAX_AGE_DAYS)


def load_seen():
    try:
        return set(json.load(open(STATE_FILE, encoding="utf-8")).get("seen", []))
    except (OSError, ValueError):
        print(f"  no readable {STATE_FILE}; treating every id as unseen")
        return set()


def assess(added, seen, today):
    """[(ticker, channel, form, filed, expired_on, accession)] already lost."""
    horizon = today - timedelta(days=RETAIN_DAYS)
    lost = []
    for tk, (cik, name) in sorted(added.items()):
        rows = filings_for(cik, horizon)
        if rows is None:
            continue
        n_lost = 0
        for form, filed, acc in rows:
            channel = ("insider" if form in INSIDER_FORMS
                       else "press" if matches_press(form) else None)
            if channel is None:
                continue
            if filing_uid(acc) in seen:
                continue          # belt and braces; cannot happen for a new CIK
            exp = expires_at(filed)
            if exp <= today:
                lost.append((tk, channel, form, filed, exp.isoformat(), acc))
                n_lost += 1
        print(f"  {tk:6} {len(rows):>3} filing(s) in {RETAIN_DAYS}d, "
              f"{n_lost} already past the age floor")
    return lost


# ------------------------------------------------------------------ OUTPUT


def build_embed(lost, added, since_ref):
    lines = [f"{len(lost)} filing(s) for {len(added)} newly added "
             f"compan{'y' if len(added) == 1 else 'ies'} were already older "
             f"than {MAX_AGE_DAYS} days when the roster changed. They will be "
             f"marked seen and never posted.\n"]
    lines.append("```")
    lines.append(f"{'':6}{'form':14}{'filed':11}{'lost at':11}")
    for tk, ch, form, filed, exp, acc in lost:
        lines.append(f"{tk:6}{form[:13]:14}{filed:11}{exp:11}")
    lines.append("```")
    lines.append(f"\nThese are not a fault and not recoverable. The age floor "
                 f"in `press_monitor.py` is what stops a backlog re-flooding "
                 f"the channel, and an item past it is recorded rather than "
                 f"posted. Compared against `{since_ref}`.")
    return {
        "title": "Filings lost to a roster change",
        "description": "\n".join(lines),
        "color": RED,
        "footer": {"text": f"audit_pending · age floor {MAX_AGE_DAYS}d · "
                           f"window {RETAIN_DAYS}d"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def post(embed):
    import urllib.error
    body = json.dumps({"embeds": [embed]}).encode()
    req = urllib.request.Request(WEBHOOK_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status < 300
    except urllib.error.HTTPError as e:
        print(f"webhook returned {e.code}")
        return False
    except Exception as e:
        print(f"webhook failed: {type(e).__name__}")
        return False


# -------------------------------------------------------------------- MAIN


def main(argv):
    since = "HEAD^"
    if "--since" in argv:
        since = argv[argv.index("--since") + 1]

    if not USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.\n")

    added = added_companies(since)
    if not added:
        # The ordinary case for a roster edit that corrects a CUSIP, fixes a
        # comment or adds an alternate symbol. Silence is the correct output.
        print(f"No company added between {since} and HEAD. Nothing to check.")
        return 0

    print(f"{len(added)} compan{'y' if len(added) == 1 else 'ies'} added since "
          f"{since}: {', '.join(sorted(added))}\n")

    today = datetime.now(timezone.utc).date()
    lost = assess(added, load_seen(), today)

    print()
    if not lost:
        print("Nothing already past the age floor. Every filing in the window "
              "is still reachable.")
        return 0

    print(f"{len(lost)} filing(s) already lost:")
    for tk, ch, form, filed, exp, acc in lost:
        print(f"  {tk:6} {ch:8} {form:14} filed {filed}  lost at {exp} 00:00Z  {acc}")

    if DRY_RUN:
        print("\nDry run: would post.")
        return 0
    if not WEBHOOK_URL:
        print("\nWEBHOOK_URL_OPS not set; not posting.")
        return 0
    print("\nposted." if post(build_embed(lost, added, since)) else "\npost failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
