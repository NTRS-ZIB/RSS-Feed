#!/usr/bin/env python3
"""
SEC comment letters -> Discord.

The SEC's Division of Corporation Finance reviews filings and corresponds with
companies about them. That correspondence becomes public on EDGAR as two form
types:

    UPLOAD    a letter from SEC staff to the company
    CORRESP   the company's reply

An open review is regulator scrutiny of the company's disclosure. It is not an
enforcement action and not an allegation of wrongdoing — most reviews close
with no change — but it is a thing worth knowing about, and nothing else in
this repo surfaces it.

WHY THIS IS NOT A press_monitor.py FORM TYPE
The obvious implementation adds UPLOAD and CORRESP to FORM_TYPES. It produces
nothing. Measured across this watchlist on 2026-07-31: 424 comment-letter
filings existed and ZERO fell inside press_monitor.py's windows, which drop
anything older than RETAIN_DAYS (30) and post nothing older than MAX_AGE_DAYS
(7). The newest letter on the entire watchlist was 86 days old.

That is a property of the data, not an accident of timing. The SEC releases
correspondence no earlier than 20 business days after it completes a review,
and letters arrive in BURSTS — several exchanges over a few weeks, then
silence for a year or more. A seven-day window will almost always miss them.

Hence LOOKBACK_DAYS below, which is 180 rather than 7.

WHAT IT REPORTS
Reviews, not letters. One post shows every company with correspondence inside
the window: how many exchanges, when the latest was, and which side sent it.
Six separate posts saying "SLNH filed a CORRESP" is noise; one line saying
"SLNH, 6 exchanges, latest 6 May, company replied" is the signal.

Pairs with the NT 10-K / NT 10-Q late-filing notices that press_monitor.py
watches for. An open review alongside a late filing is a much stronger signal
than either alone.
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import watchlist
from first_run import backfill_note, backfilled, baseline_by_cik, summary

# ------------------------------------------------------------------ CONFIG

# UPLOAD is SEC -> company, CORRESP is company -> SEC. Matched exactly, not by
# prefix: neither has amendment variants and neither collides with another form.
FORMS = {"UPLOAD": "SEC", "CORRESP": "co"}

# How far back a letter counts as part of an active review.
#
# NOT a posting-age filter — every letter inside this window is described in
# every post. It defines what "currently under review" means. 180 days is about
# two review cycles: long enough that a burst stays visible after it ends, short
# enough that a review closed a year ago drops off.
#
# It is also deliberately generous because the SEC publishes correspondence at
# least 20 business days after completing a review, and EDGAR's filingDate is
# the SUBMISSION date, not the publication date. The gap between them is not
# exposed by the submissions API, so the window must be wide enough that the
# component works whether the gap is one day or three months.
LOOKBACK_DAYS = 180

# A company is called out in prose when its burst is at least this many
# exchanges. One letter is often routine; several is a live conversation.
NOTABLE_EXCHANGES = 3

STATE_FILE = Path(os.environ.get("LETTERS_STATE", "letters_state.json"))

# ----------------------------------------------------------------- RUNTIME

# Filings channel, not market data: these are SEC filings. Volume does not
# warrant a channel of its own — most weeks this posts nothing at all.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_INDEX = ("https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
                "{acc}-index.htm")
REQUEST_GAP = 0.2

AMBER, GREY = 0xD29922, 0x5A6672


# ------------------------------------------------------------------- STATE


def load_state():
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            s = {}
    else:
        s = {}
    s.setdefault("seen", [])
    s.setdefault("last_run", "")
    return s


def save_state(state, accessions):
    # Retention is bounded by the window, not by count: anything outside
    # LOOKBACK_DAYS can never appear again, so remembering it is dead weight.
    state["seen"] = sorted(accessions)
    state["last_run"] = date.today().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


# ------------------------------------------------------------------- FETCH


def sec_get(url):
    r = requests.get(
        url,
        headers={"User-Agent": SEC_USER_AGENT or "watchlist-monitor contact@example.com",
                 "Accept-Encoding": "gzip, deflate"},
        timeout=(10, 30),
    )
    r.raise_for_status()
    return r.json()


def letters_for(cik, cutoff):
    """Comment-letter filings inside the window, newest first."""
    recent = sec_get(SUBMISSIONS.format(cik=cik)).get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    # Parallel arrays from the API. Truncate to the shortest rather than
    # trusting them to align — a ragged payload would otherwise IndexError
    # mid-run and lose every company after this one.
    n = min(len(forms), len(dates), len(accs))
    out = []
    for i in range(n):
        form = forms[i]
        if form not in FORMS:
            continue
        try:
            when = date.fromisoformat(dates[i])
        except (ValueError, TypeError):
            continue
        if when < cutoff:
            continue
        acc = accs[i]
        out.append({
            "form": form,
            "date": when,
            "accession": acc,
            "url": FILING_INDEX.format(cik=int(cik), acc_nodash=acc.replace("-", ""),
                                       acc=acc),
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def drop_newly_watched(new, rows, newly_watched):
    """Accessions belonging to companies added since the last run, removed.

    Returns the surviving accessions and a per-ticker count of what was
    dropped. Every letter inside the 180-day window is unseen for such a
    company, and that is the widest window in the repo.
    """
    theirs = {a for r in rows if r["ticker"] in newly_watched
              for a in r["accessions"]}
    per = {r["ticker"]: len(r["accessions"]) for r in rows
           if r["ticker"] in newly_watched}
    return new - theirs, per


# ------------------------------------------------------------------ FORMAT


def build_table(rows):
    """Kept to 23 characters. See the output-width note in the README."""
    out = [f"{'':<5}{'Ltrs':>5}{'Last':>8}{'From':>5}", "-" * 23]
    for r in rows:
        last = f"{r['latest']:%d %b}"
        out.append(f"{r['ticker']:<5}{min(r['count'], 99):>5}"
                   f"{last:>8}{FORMS[r['last_form']]:>5}")
    return "\n".join(out)


def build_embed(rows, new_count, window_start):
    table = build_table(rows)
    lines = [f"```\n{table}\n```"]

    for r in rows:
        if r["count"] >= NOTABLE_EXCHANGES:
            lines.append(
                f"**{r['ticker']}** {r['count']} exchanges since "
                f"{r['earliest']:%d %b} — [latest]({r['newest_url']}) "
                f"{'from SEC staff' if r['last_form'] == 'UPLOAD' else 'company reply'}"
            )

    lines.append(
        f"_`From` is who sent the most recent letter: `SEC` means a staff "
        f"comment is outstanding, `co` means the company has replied. "
        f"Window: {LOOKBACK_DAYS} days, from {window_start:%d %b %Y}._"
    )
    lines.append(
        "_A review is scrutiny of disclosure, not an enforcement action. "
        "Most close with no change. EDGAR publishes correspondence at least "
        "20 business days after a review completes, so this is never timely._"
    )

    return {
        "title": "SEC comment letters",
        "description": "\n".join(lines),
        "color": AMBER if new_count else GREY,
        "footer": {"text": f"EDGAR UPLOAD/CORRESP · {new_count} new this run"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def post(embed):
    try:
        r = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=25)
    except requests.RequestException as e:
        print(f"webhook failed: {type(e).__name__}")
        return False
    if r.status_code >= 300:
        print(f"webhook returned {r.status_code}: {r.text[:200]}")
        return False
    return True


# -------------------------------------------------------------------- MAIN


def main():
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL is not set.")
    if not SEC_USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.\n")

    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    print(f"Comment letters filed since {cutoff:%Y-%m-%d} "
          f"({LOOKBACK_DAYS}-day window)")

    rows, all_accessions, failed = [], set(), []
    for ticker, (cik, name) in sorted(watchlist.ciks().items()):
        try:
            found = letters_for(cik, cutoff)
        except Exception as e:
            print(f"  {ticker}: FAILED {type(e).__name__}: {e}")
            failed.append(ticker)
            continue
        all_accessions |= {f["accession"] for f in found}
        if found:
            rows.append({
                "ticker": ticker, "name": name, "count": len(found),
                "latest": found[0]["date"], "earliest": found[-1]["date"],
                "last_form": found[0]["form"], "newest_url": found[0]["url"],
                "accessions": [f["accession"] for f in found],
            })
            print(f"  {ticker}: {len(found)} letter(s), latest "
                  f"{found[0]['date']} ({found[0]['form']})")
        else:
            print(f"  {ticker}: none in window")
        time.sleep(REQUEST_GAP)

    if failed:
        print(f"\n{len(failed)} company/companies failed: {', '.join(failed)}")
        print("Not posting a partial picture — a company missing from the table")
        print("would read as 'no review', which is the opposite of unknown.")
        return 1

    rows.sort(key=lambda r: (r["latest"], r["count"]), reverse=True)

    state = load_state()
    seen = set(state["seen"])
    first_run = not STATE_FILE.exists()
    new = all_accessions - seen

    # PER COMPANY, NOT PER FILE. `first_run` above is only a log annotation
    # here and suppresses nothing; even as a guard it would cover a cold start
    # and not a company added to a roster this component has watched for
    # months. For such a company EVERY letter inside the 180-day window is
    # new, which is the widest window in the repo and so the largest possible
    # backlog. On 2026-08-14 holder_events posted 86 messages from exactly
    # this shape; this component escaped only because all three companies
    # added that week had no correspondence in window. That is luck, not a
    # guard. Their accessions are still recorded by save_state below, so the
    # next genuine letter posts normally.
    backfill = backfilled(state)
    newly_watched = set(baseline_by_cik(state, watchlist.ciks()))
    if backfill:
        print("\n" + backfill_note("comment_letters", len(watchlist.ciks())))
    if newly_watched:
        new, per = drop_newly_watched(new, rows, newly_watched)
        print("\n" + summary("comment_letters", sorted(newly_watched), per))

    print()
    print(build_table(rows) if rows else "No comment letters in the window.")
    print()
    print(f"{len(all_accessions)} letter(s) in window, {len(new)} new since last run"
          + ("  (no state file — first run)" if first_run else ""))

    if not new:
        print("No change. Nothing to post.")
        # A dry run saves nothing, so there is no reason to withhold the
        # output. Without this the embed is unpreviewable once state exists,
        # and for a component that posts only on new correspondence that could
        # be months.
        if DRY_RUN:
            if rows:
                print("\nDry run: nothing changed, but this is what a post "
                      "would look like.\n")
                print(build_embed(rows, 0, cutoff)["description"])
            else:
                print("\nDry run: no correspondence in the window, so a post "
                      "would have nothing to show.")
        else:
            save_state(state, all_accessions)
        return 0

    embed = build_embed(rows, len(new), cutoff)

    if DRY_RUN:
        print(f"\nDry run: would post {len(rows)} company/companies with active "
              f"correspondence. State not saved.")
        return 0

    if not post(embed):
        print("Post failed — state not saved, will retry next run.")
        return 1

    save_state(state, all_accessions)
    print(f"State written: {STATE_FILE.name} ({len(all_accessions)} accessions)")
    print("Posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
