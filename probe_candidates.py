#!/usr/bin/env python3
"""What EDGAR currently says about a company someone wants to add.

WHY THIS EXISTS
A roster addition starts as a name somebody remembers, and this repository has
written three separate warnings against acting on that. Six of nineteen
companies renamed in eighteen months; one ticker on the roster was previously
a DIFFERENT company's; and the first audit after SPCX was added proposed the
ticker's previous owner's CUSIP — right shape, right dates, wrong company.

So before a record is written, the questions are: does this ticker still
resolve at all, to which CIK, under what name today, with what former names,
and is the registrant still filing. All of that is in two SEC endpoints and
none of it is in anybody's memory.

WHAT IT DELIBERATELY DOES NOT DO
It does not propose a CUSIP. A CUSIP comes from data a component actually
reads — the FINRA and SEC files ftd_monitor and short_interest parse — never
from a filing and never from here. `audit_identifiers.py` owns that, and it
needs two passes. This probe answers only the questions that come first.

HOW TO READ THE OUTPUT
  ticker does not resolve   acquired, delisted or renamed. Do not add it.
  name differs from yours   you are remembering an old name, or the wrong
                            company. Read formerNames before deciding.
  CIK already on the roster the company is already tracked under another
                            ticker; this would be a duplicate, not an addition
  no recent filings         a registrant that has stopped filing is not a
                            live company for this repo's purposes

Read-only. Needs SEC_USER_AGENT. Posts nothing, writes nothing.
"""

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import watchlist

# Edit this before running. These are the candidates as of 2026-08-13; the
# point of the probe is that none of them is trusted until it answers.
CANDIDATES = ["CRWV"]

# Newsroom URLs to test for a real feed, per candidate. EVERY `None` in
# watchlist.py means a MEASURED absence of a feed, not an unexamined one —
# the roster's closing comment says so in those words — so a record cannot
# honestly be written with `None` until this has run and come back empty.
#
# Several URLs per company on purpose, and every one is REPORTED rather than
# guessed at: a soft-404 answers 200 with the wrong content, so what decides
# is how many entries actually parse, not the status code.
FEED_CANDIDATES = {
    "CORZ": [
        "https://investors.corescientific.com/news-events/press-releases",
        "https://investors.corescientific.com/rss/pressrelease.aspx",
        "https://www.corescientific.com/news",
        "https://www.corescientific.com/feed/",
        "https://ir.corescientific.com/news-events/press-releases",
    ],
}

UA = os.environ.get("SEC_USER_AGENT", "").strip()
GAP = 0.15
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"
RECENT_DAYS = 120
# Half-month fails periods to sweep for a candidate's CUSIP. Six is three
# months, enough for a symbol that trades now; a symbol that does not appear
# has not been ruled out, only unswept.
FTD_PERIODS = 6


def fetch_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        return json.loads(raw)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"    fetch failed: {type(e).__name__} {url[:80]}")
        return None


def main():
    if not UA:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

    roster = watchlist.ciks()
    on_roster = {cik.lstrip("0"): t for t, (cik, _n) in roster.items()}

    print(f"Resolving {len(CANDIDATES)} candidate(s) against EDGAR's own "
          f"ticker index...")
    index = fetch_json(TICKERS_URL)
    if not index:
        sys.exit("EDGAR's ticker index did not return; nothing can be checked.")
    by_ticker = {}
    for row in index.values():
        by_ticker.setdefault(str(row.get("ticker", "")).upper(),
                             (str(row.get("cik_str")), row.get("title", "")))
    print(f"  {len(by_ticker)} tickers in the index")

    # VALIDATE THE INSTRUMENT BEFORE TRUSTING ITS SILENCE. "Does not resolve"
    # is this probe's most decisive verdict, and it is only meaningful if the
    # index actually covers companies like the ones being asked about. The
    # roster is the control: nineteen companies known to exist and known to
    # file, several of them foreign private issuers. If some of THEM are
    # missing, absence is a fact about the index rather than about a
    # candidate, and a candidate that does not resolve has not been ruled out.
    missing_roster = sorted(t for t in roster if t.upper() not in by_ticker)
    print(f"  control: {len(roster) - len(missing_roster)} of {len(roster)} "
          f"roster tickers resolve in it")
    if missing_roster:
        print(f"  ROSTER TICKERS THE INDEX DOES NOT CARRY: "
              f"{', '.join(missing_roster)}")
        print("  So a candidate that does not resolve has NOT been ruled out "
              "by this probe.\n")
    else:
        print("  so a candidate missing from it is genuinely missing\n")

    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    for want in CANDIDATES:
        hit = by_ticker.get(want.upper())
        print(f"{want}")
        if not hit:
            # Deliberately does NOT say "acquired, delisted or renamed". The
            # first version did, and that is a cause asserted from an absence:
            # the index is built from cover-page data and need not carry every
            # filer. Read this against the control line above, which says
            # whether the index carries companies like these at all.
            print("  DOES NOT RESOLVE in EDGAR's ticker index. That is a "
                  "reason to look, not a verdict —\n  read the control line "
                  "above before concluding anything.\n")
            continue
        cik, title = hit
        print(f"  CIK {cik.zfill(10)}  {title}")
        if cik.lstrip('0') in on_roster:
            print(f"  ALREADY ON THE ROSTER as {on_roster[cik.lstrip('0')]} — "
                  f"this would be a duplicate, not an addition")
        time.sleep(GAP)
        sub = fetch_json(SUBMISSIONS % cik.zfill(10))
        if not sub:
            print("  submissions index did not return\n")
            continue
        former = [f.get("name") for f in (sub.get("formerNames") or [])]
        if former:
            print(f"  former names: {', '.join(filter(None, former))}")
        print(f"  exchanges: {', '.join(sub.get('exchanges') or []) or '-'}"
              f"   SIC: {sub.get('sicDescription') or '-'}")
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        fresh = [(d, f) for d, f in zip(dates, forms) if d >= cutoff]
        if not fresh:
            print(f"  NO FILINGS in {RECENT_DAYS} days — not a live filer\n")
            continue
        newest = max(fresh)
        kinds = sorted({f for _, f in fresh})
        print(f"  {len(fresh)} filing(s) in {RECENT_DAYS}d, newest "
              f"{newest[0]} {newest[1]}")
        # THE MIX, NOT JUST THE LIST. A high filing count is only a cost if
        # it lands in a channel with a cap: the insider channel posts at most
        # MAX_INSIDER_POSTS_PER_RUN per run, so a heavy Form 4 filer competes
        # with the whole roster for those slots. Counting separates a company
        # that files constantly from one that files constantly IN THE FORMS
        # THIS REPO POSTS.
        from collections import Counter
        mix = Counter(f for _, f in fresh)
        print("  form mix: " + ", ".join(
            f"{f} x{n}" for f, n in mix.most_common(10)))
        insiderish = sum(n for f, n in mix.items() if f in ("3", "4", "4/A", "3/A"))
        pressish = sum(n for f, n in mix.items()
                       if f.startswith(("8-K", "10-", "S-3", "S-1", "424",
                                        "DEF 14A", "PRE 14A", "6-K", "20-F")))
        print(f"  -> {insiderish} would reach the insider channel, "
              f"{pressish} the press channel, over {RECENT_DAYS} days")
        print()

    if FEED_CANDIDATES:
        feeds()
    identifiers()
    return 0


def identifiers():
    """The CUSIP a candidate trades under, from the SEC's own fails files.

    THERE IS NO CIRCLE HERE, though an earlier version of this docstring said
    there was. `watchlist.validate()` REPORTS an empty `cusips` list; it does
    not reject one. `docs/watchlist.md` is explicit that a new company sitting
    at `"cusips": []` is the intended state and that the warning "should be
    left alone", because it is a true statement about what this repo knows.

    What this adds is speed and one column. `audit_identifiers.py` matches on
    symbols already on the roster, so it cannot report a candidate before the
    record exists; sweeping the fails files for the literal symbol answers the
    same question first, which lets a record be written complete rather than
    pending. That is a convenience, NOT a licence to skip the real audit: this
    sweeps six periods where the audit sweeps twenty-four or a hundred and
    twenty, and a shallow window finds a current identifier while missing
    every retired one.

    IT PRINTS THE DESCRIPTION COLUMN, which `audit_identifiers.py` does not
    parse. That column is the only thing that separated SPCX-the-SPAC-ETF from
    SPCX-the-rocket-company when the first sweep proposed the ETF's CUSIP —
    right shape, right dates, wrong company, no collision reported. A CUSIP
    without the description beside it is a number nobody has checked.
    """
    import io as _io
    import zipfile
    import ftd_monitor                                # noqa: E402

    wanted = {t.upper() for t in CANDIDATES}
    print("\n" + "=" * 68)
    print("IDENTIFIERS — from the SEC fails files, never from a filing")
    print("=" * 68)
    sess = ftd_monitor.session()
    try:
        periods = ftd_monitor.fetch_index(sess)[:FTD_PERIODS]
    except Exception as exc:                           # noqa: BLE001
        print(f"  could not read the fails index: {type(exc).__name__} {exc}")
        return
    if not periods:
        print("  no fails periods found — layout changed?")
        return

    seen = {}
    for period, url in sorted(periods):
        try:
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            zf = zipfile.ZipFile(_io.BytesIO(r.content))
            member = next(n for n in zf.namelist() if not n.endswith("/"))
            body = zf.read(member).decode("latin-1")
        except Exception as exc:                       # noqa: BLE001
            print(f"  {period}: {type(exc).__name__}")
            continue
        for line in body.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 5 or not parts[0].isdigit():
                continue
            date, cusip, symbol, _qty, desc = parts[:5]
            if symbol.upper() not in wanted:
                continue
            key = (symbol.upper(), cusip)
            first, last, _ = seen.get(key, (date, date, desc))
            seen[key] = (min(first, date), max(last, date), desc)
        time.sleep(GAP)

    if not seen:
        print(f"  no candidate symbol appears in {len(periods)} periods. "
              f"Absence here is\n  NOT evidence of a wrong ticker: the SEC "
              f"lists only NON-ZERO fails, so a name\n  that simply did not "
              f"fail is missing for the best possible reason.")
        return
    for (symbol, cusip), (first, last, desc) in sorted(seen.items()):
        print(f"\n  {symbol}  {cusip}  {first} to {last}")
        print(f"    DESCRIPTION: {desc}")
        print(f"    -> read that name before pinning it. It is what separated "
              f"SPCX-the-ETF\n       from SPCX-the-rocket-company.")


def feeds():
    """Does this company's own newsroom carry a feed, measured not assumed.

    Uses press_monitor's OWN parse_feed and discover_feed, so what is measured
    is what the component would actually get rather than what a browser shows.
    A URL answering 200 proves nothing on its own: a soft-404 does that too,
    and this repo has already nearly posted two dead links to one. The entry
    count is the answer.
    """
    import press_monitor as pm                       # noqa: E402

    print("=" * 68)
    print("NEWSROOM FEEDS — a None in watchlist.py must be a MEASURED absence")
    print("=" * 68)
    for ticker, urls in FEED_CANDIDATES.items():
        print(f"\n{ticker}")
        found = []
        for url in urls:
            time.sleep(GAP)
            entries = pm.parse_feed(url)
            note = ""
            if not entries:
                # Not a feed itself: ask whether the PAGE advertises one.
                discovered = pm.discover_feed(url)
                if discovered and discovered != url:
                    time.sleep(GAP)
                    entries = pm.parse_feed(discovered)
                    note = f"  (via discovered {discovered})"
                    if entries:
                        url = discovered
            print(f"  {len(entries):>3} entries  {url}{note}")
            if entries:
                # THROUGH entry_time, NOT max() OVER THE DATE STRINGS. The
                # first version did the latter and reported this very feed as
                # 99 days stale: RFC-822 dates start with a weekday, so
                # "Wed, 06 May" sorts above "Tue, 28 Jul" and the newest entry
                # was three days old, not three months. A default sort is not
                # a date sort, and it read as a dead source rather than as a
                # bug. Only printing the titles caught it.
                stamps = [pm.entry_time(e) for e in entries]
                newest = max(stamps) if any(stamps) else 0
                print("            newest entry: " + (
                    time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(newest))
                    if newest else "no usable timestamp"))
                # WHAT IS IN IT, not just how much. A site-wide WordPress feed
                # answers 200 with valid XML and carries blog posts rather
                # than press releases, which is a different source wearing the
                # right shape. DGXX's old feed is the recorded case: 20 valid
                # items, nothing newer than months back, every check passed.
                for e in entries[:8]:
                    title = " ".join((e.get("title") or "").split())[:88]
                    when = (e.get("published") or "")[:16]
                    print(f"              {when:<17}{title}")
                found.append((url, len(entries), newest))
        if found:
            # BY FRESHNESS, NOT BY COUNT. CORZ has two feeds: its investor
            # newsroom, 10 entries and three days old, and a site-wide
            # WordPress blog, 9 entries and SEVENTEEN MONTHS old, carrying
            # "How HPC Hosting Saves Costs for Businesses" rather than any
            # press release. Picking the larger got that right by one entry;
            # a blog with twenty posts would have won. What separates them is
            # recency, so that is what decides, with the count as a tie-break.
            best = max(found, key=lambda r: (r[2], r[1]))
            age = time.strftime("%Y-%m-%d", time.gmtime(best[2])) if best[2] else "?"
            print(f"  -> USE {best[0]}")
            print(f"     ({best[1]} entries, newest {age})")
            for url, n, stamp in sorted(found, key=lambda r: -r[2])[1:]:
                when = time.strftime("%Y-%m-%d", time.gmtime(stamp)) if stamp else "?"
                print(f"     rejected: {url} ({n} entries, newest {when})")
        else:
            print("  -> no feed on any URL tried. `ir_feed: None` would be a "
                  "measured absence,\n     and the company then needs a "
                  "scraper or CMS reader like HUT, GLXY, DGXX and ABTC.")


if __name__ == "__main__":
    sys.exit(main())
