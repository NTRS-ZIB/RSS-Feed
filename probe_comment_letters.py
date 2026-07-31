#!/usr/bin/env python3
"""
THROWAWAY PROBE — not a component. Delete after use.

Answers one question before SEC comment letters are added to press_monitor.py:
would they ever actually post?

Comment letters are released on EDGAR at least 20 business days after the staff
completes its review, but the `filingDate` EDGAR records is the date of the
LETTER, not the date it became visible. If that is right, a letter appearing
today carries a filing date weeks or months old — and press_monitor.py drops it
twice over:

    RETAIN_DAYS  = 30   only filings from the last 30 days enter the dedupe set
    MAX_AGE_DAYS = 7    of those, only ones under a week old can post

which would make the feature a silent, permanent no-op.

This prints every UPLOAD and CORRESP filing on the watchlist with both
timestamps, so the answer is measured rather than assumed.

    SEC_USER_AGENT="Your Name you@example.com" python -u probe_comment_letters.py
"""

import os
import sys
import time
from datetime import date, datetime, timezone

import requests

import watchlist

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FORMS = ("UPLOAD", "CORRESP")
RETAIN_DAYS = 30          # mirrors press_monitor.py
MAX_AGE_DAYS = 7          # mirrors press_monitor.py

USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()


def fetch(cik):
    r = requests.get(
        SUBMISSIONS.format(cik=cik),
        headers={"User-Agent": USER_AGENT or "watchlist-probe contact@example.com",
                 "Accept-Encoding": "gzip, deflate"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def rows(payload):
    """Yield (form, filingDate, acceptanceDateTime) for comment-letter forms."""
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filed = recent.get("filingDate", [])
    accepted = recent.get("acceptanceDateTime", [])
    for i, form in enumerate(forms):
        if form in FORMS:
            yield form, filed[i], (accepted[i] if i < len(accepted) else "")


def main():
    if not USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.\n")

    today = date.today()
    total, postable, retained = 0, 0, 0
    per_company = {}

    for ticker, (cik, name) in sorted(watchlist.ciks().items()):
        print(f"  {ticker} ({name})...", end=" ", flush=True)
        try:
            found = list(rows(fetch(cik)))
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            continue
        per_company[ticker] = found
        print(f"{len(found)} comment-letter filing(s)")
        time.sleep(0.2)

    print()
    if not any(per_company.values()):
        print("No UPLOAD or CORRESP filings on the entire watchlist.")
        print("The feature would be correct but would never fire. That is a")
        print("legitimate outcome for a low-noise signal — but worth knowing")
        print("before adding it, rather than mistaking silence for a bug.")
        return 0

    print(f"{'ticker':8}{'form':10}{'filingDate':13}{'accepted':13}{'age':>6}  verdict")
    print("-" * 74)
    for ticker, found in sorted(per_company.items()):
        for form, filed, accepted in sorted(found, key=lambda r: r[1], reverse=True)[:6]:
            total += 1
            try:
                age = (today - date.fromisoformat(filed)).days
            except ValueError:
                age = None
            acc = accepted[:10] if accepted else "-"
            if age is None:
                verdict = "unparsable date"
            elif age <= MAX_AGE_DAYS:
                verdict = "would post"; postable += 1; retained += 1
            elif age <= RETAIN_DAYS:
                verdict = f"recorded, not posted (>{MAX_AGE_DAYS}d)"; retained += 1
            else:
                verdict = f"DROPPED before dedupe (>{RETAIN_DAYS}d)"
            print(f"{ticker:8}{form:10}{filed:13}{acc:13}{age if age is not None else '?':>6}  {verdict}")

    print()
    print(f"{total} filing(s) shown (newest 6 per company)")
    print(f"  {postable} would post under the current MAX_AGE_DAYS={MAX_AGE_DAYS}")
    print(f"  {retained} would enter the dedupe set under RETAIN_DAYS={RETAIN_DAYS}")
    print()
    print("WHAT TO LOOK FOR: compare `filingDate` against `accepted`. If they")
    print("match, the filing date IS the release date and adding UPLOAD/CORRESP")
    print("to FORM_TYPES is genuinely a one-line change. If `accepted` runs weeks")
    print("later than `filingDate`, the age filters will suppress every one and")
    print("the feature needs an age exemption rather than a form-type entry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
