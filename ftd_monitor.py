#!/usr/bin/env python3
"""
SEC fails-to-deliver (CNS) -> Discord.

The SEC publishes, twice a month, the aggregate net balance of shares that
failed to deliver in NSCC's Continuous Net Settlement system, per security,
per settlement date. This posts once per new half-month file, showing each
watchlist ticker's peak fail balance against its own trailing median.

Data: https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data
No auth. A contact string in SEC_USER_AGENT is required by SEC policy.

WHAT THIS IS NOT
----------------
1. It is not evidence of naked shorting. The SEC states plainly that fails
   occur on both long and short sales for many reasons, and are not evidence
   of abusive or naked short selling. Most are ordinary settlement friction.

2. It is not a daily flow. The number is a CUMULATIVE BALANCE outstanding on
   that settlement date: everything still unsettled, plus new fails that day,
   less fails that cleared. Consecutive days are not additive and the age of
   a fail cannot be recovered from the series. Summing the column would be
   meaningless.

3. It is not timely. First half of a month publishes at month end; second
   half publishes around the 15th of the following month. Worst case a
   settlement date is visible about six weeks later. Every other component in
   this repo is same-day or next-day; this one is not, and the embed says so.

Absence of a ticker means a zero net balance on every settlement date in the
period, which is the ordinary case and is reported rather than hidden.
"""

import io
import json
import os
import re
import statistics
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

import watchlist
# ---------------------------------------------------------------- CONFIG ----

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one. All three names below are DERIVED.
#
# CANON maps OLD OR PENDING SYMBOL -> canonical ticker, because this component
# filters a bulk file rather than querying by symbol. That is the exact INVERSE
# of what short_interest.py, regsho_volume.py and threshold_list.py need. Both
# directions come from the same `alt_symbols` list, so they cannot disagree —
# hand-maintaining them is how GREE was once mapped to Soluna.
#
# CUSIP_PINS carries every CUSIP, current and retired. More entries than
# tickers is correct: several companies appear more than once, because a CUSIP
# survives a rename but NOT a reverse split. watchlist.py validates the check
# digits.
TICKERS = watchlist.tickers()
CANON = watchlist.symbol_to_ticker()
CUSIP_PINS = watchlist.cusip_pins()

# Identifiers checked and rejected, and the dates symbols changed hands. Both
# are roster facts rather than component settings, so they live in
# watchlist.py — see the three guards in fetch_period().
REFUSED_CUSIPS = watchlist.refused_cusips()
HANDOVER = watchlist.symbol_handover()

# Every pinned identifier grouped by ticker, so the learning guard can ask
# "does this look like one of ours" without rebuilding the map per row.
PINNED_BY_TICKER = {}
for _cu, _t in CUSIP_PINS.items():
    PINNED_BY_TICKER.setdefault(_t, []).append(_cu)

# Leading characters that must match for an unrecorded CUSIP to be adopted
# automatically. Four, because DGXX's genuine 25381D -> 25380B reassignment
# shares exactly that many and must not be quarantined; HUT's 44812T -> 44812J
# shares five. See related_prefix().
STEM = 4

INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"

# Half-month periods retained for the trailing median, plus how many to pull on
# a cold start. Six periods is three months, enough for a median to mean
# something without a first run downloading a year of zips.
BASELINE_PERIODS = 6

# A ticker is flagged when its peak balance is this many times its own trailing
# median AND large enough in absolute terms to matter. MIN_FLAG_PERIODS exists
# because a median over two points is not a baseline — a newly listed company
# would otherwise flag on its second reading. Those rows show `~` instead.
FLAG_MULTIPLE = 3.0
MIN_FLAG_SHARES = 50_000
MIN_BASELINE_PERIODS = 2
MIN_FLAG_PERIODS = 4

STATE_FILE = "ftd_state.json"
REQUEST_GAP = 0.3          # seconds between SEC requests
TIMEOUT = 60               # zips are 1-2 MB

WEBHOOK = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

# FTD_REPLAY=<n> re-reads the newest n periods regardless of what has already
# been posted, and is unconditionally read-only: it cannot post and cannot save
# state. Its purpose is auditing history — exercising the rename and
# reverse-split guards over real files without disturbing the live state, which
# a normal run refuses to do because it exits at the dedupe check.
try:
    REPLAY = int(os.environ.get("FTD_REPLAY", "") or 0)
except ValueError:
    REPLAY = 0
if REPLAY:
    DRY_RUN = True

# ------------------------------------------------------------------ STATE ---


def load_state():
    try:
        with open(STATE_FILE) as fh:
            s = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    s.setdefault("last_period", "")
    s.setdefault("cusips", {})      # cusip -> canonical ticker
    s.setdefault("history", {})     # ticker -> {period: {peak, days}}
    s["cusips"].update(CUSIP_PINS)
    return s


def save_state(state):
    keep = sorted({p for t in state["history"].values() for p in t})[-(BASELINE_PERIODS + 2):]
    state["history"] = {
        t: {p: v for p, v in periods.items() if p in keep}
        for t, periods in state["history"].items()
    }
    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)


# ------------------------------------------------------------------ FETCH ---


def session():
    s = requests.Session()
    ua = USER_AGENT or "watchlist-monitor contact-not-set@example.com"
    s.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    return s


PERIOD_RE = re.compile(r'href="([^"]*?cnsfails(\d{4})(\d{2})([ab])[^"]*?\.zip)"', re.I)


def fetch_index(sess):
    """Return [(period_key, url)] newest first.

    The URL path is NOT stable and must not be constructed. Observed shapes:
        /files/data/fails-deliver-data/cnsfails202606b.zip
        /files/data/other/fails-deliver-data/cnsfails202605a.zip
        /files/data/fails-deliver-data/cnsfails202308b_0.zip
        /files/node/add/data_distribution/cnsfails202004a.zip
        /files/data/frequently-requested-foia-document-fails-deliver-data/...
    Four different prefixes, one of them introduced in 2026. Scraping the
    index is the only approach that survives the next reorganisation.
    """
    r = sess.get(INDEX_URL, timeout=TIMEOUT)
    r.raise_for_status()
    found = {}
    for href, yyyy, mm, half in PERIOD_RE.findall(r.text):
        found.setdefault(f"{yyyy}{mm}{half}", urljoin(INDEX_URL, href))
    return sorted(found.items(), reverse=True)


def mmdd(yyyymmdd):
    return f"{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def pretty(period):
    return f"{period[:4]}-{period[4:6]}{period[6]}"


def related_prefix(cusip, known):
    """Does `cusip` share a leading stem with any identifier already ours?

    A genuine change of identifier keeps part of the issuer prefix even when
    the prefix itself moves: HUT went 44812T -> 44812J, sharing five, and DGXX
    25381D -> 25380B, sharing four. STEM is set to the tighter of those.

    This is a REPORTING heuristic, not a truth test, and it is deliberately
    one-directional. ABTC is the counter-example that stops it being anything
    stronger: its chain runs 00973W (Akerna) -> 400510 (Gryphon) -> 02462A,
    three unrelated prefixes on one continuous registrant. Those are pinned in
    the roster, so this function never sees them — which is the point. An
    identifier a HUMAN has checked is recorded; one that merely turned up is
    not adopted on its own say-so.
    """
    return any(cusip[:STEM] == k[:STEM] for k in known if k)


def fetch_period(sess, url, cusips):
    """Download one half-month zip and return {ticker: [(date, qty, cusip)]}.

    Matching is by symbol OR by a CUSIP already learned for that ticker, so a
    rename part-way through the baseline window doesn't silently drop history.

    THREE GUARDS stand between this loop and a recycled ticker, because the
    consequences here are asymmetric and permanent. A missed row under-reports
    one period, visibly. A wrongly matched row attributes another security's
    fails to one of ours, and — before these guards — taught the state file to
    keep doing it:

      1. A REFUSED CUSIP is never ours, whatever symbol it carries. See
         watchlist.REFUSED.
      2. A symbol is only ours AFTER its handover date. SPCX belonged to a
         SPAC ETF until 2026-04-07; without this, an FTD_REPLAY of 8 or more
         periods reaches rows that are not this company's. Symbol matching is
         the only thing gated — a pinned CUSIP is unambiguous and stays
         authoritative.
      3. An unrecorded CUSIP is only LEARNED if it looks related to one
         already ours. Anything else is reported and left unlearned rather
         than written into ftd_state.json, where a wrong entry would outlive
         every run that followed it.
    """
    r = sess.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    member = next(n for n in zf.namelist() if not n.endswith("/"))
    raw = zf.read(member).decode("latin-1")

    rows, learned, skipped, seen_syms = {}, {}, 0, {}
    refused_rows, pre_handover, unlearned = {}, {}, {}
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        date, cusip, symbol, qty = (p.strip() for p in parts[:4])
        if not date.isdigit() or len(date) != 8:
            continue          # header and any trailer line
        sym = symbol.upper()

        # (1) Refused outright — checked before any matching, so no path
        # reaches it.
        if cusip in REFUSED_CUSIPS:
            refused_rows[cusip] = refused_rows.get(cusip, 0) + 1
            continue

        # (2) The symbol is ours only after the handover. Fall through to
        # CUSIP matching rather than dropping the row outright: if it carries
        # an identifier genuinely pinned to us, it is ours despite the date.
        by_symbol = CANON.get(sym)
        if by_symbol and date <= HANDOVER.get(sym, ""):
            pre_handover[sym] = pre_handover.get(sym, 0) + 1
            by_symbol = None

        ticker = by_symbol or cusips.get(cusip)
        if not ticker:
            continue
        try:
            shares = int(qty)
        except ValueError:
            skipped += 1
            continue
        rows.setdefault(ticker, []).append((date, shares, cusip))
        seen_syms.setdefault(ticker, {}).setdefault(sym, set()).add(date)

        # (3) Learn only what looks like ours. `known` is every identifier
        # already attributed to this ticker — pinned, learned earlier, or
        # learned in this period.
        if cusip and cusip not in cusips:
            known = [c for c, t in cusips.items() if t == ticker]
            known += [c for c, t in learned.items() if t == ticker]
            known += [c for c in PINNED_BY_TICKER.get(ticker, ())]
            if related_prefix(cusip, known):
                learned[cusip] = ticker
            else:
                unlearned.setdefault(ticker, {})[cusip] = sym

    if refused_rows:
        for cu, n in sorted(refused_rows.items()):
            rec = REFUSED_CUSIPS[cu]
            print(f"\n    refused {cu}: {n} row(s) skipped — {rec['belongs_to']}, "
                  f"not {rec['symbol']}", end="")
    if pre_handover:
        for sym, n in sorted(pre_handover.items()):
            print(f"\n    {sym}: {n} row(s) at or before its "
                  f"{HANDOVER[sym]} handover, not matched by symbol", end="")
    if unlearned:
        for t, found in sorted(unlearned.items()):
            # A ticker with NO pins at all is the new-company case, and it
            # reads differently from a genuine prefix mismatch: there is
            # nothing to be unrelated to. Refusing to learn is still right —
            # that empty base is exactly how the SPCX ETF's identifier would
            # have been adopted — but the log should say which situation it is.
            bare = not PINNED_BY_TICKER.get(t)
            for cu, sym in sorted(found.items()):
                if bare:
                    print(f"\n    {t}: saw {cu} (as {sym}) but has no pinned "
                          f"identifier to compare against — NOT learned. Run "
                          f"audit_identifiers.py and pin it.", end="")
                else:
                    print(f"\n    {t}: saw {cu} (as {sym}) unrelated to any "
                          f"known identifier — NOT learned. Check its "
                          f"description, then add it to watchlist.py or to "
                          f"REFUSED.", end="")
    return rows, learned, skipped, seen_syms


# ------------------------------------------------------------- AGGREGATION --


def summarise(rows):
    """Peak balance, its date, and the count of settlement days with a fail."""
    out = {}
    for ticker, entries in rows.items():
        date, peak, _ = max(entries, key=lambda e: e[1])
        out[ticker] = {"peak": peak, "peak_date": date, "days": len(entries)}
    return out


def baseline(state, ticker, current_period):
    """Median of prior periods' peaks, and how many periods that rests on.

    A period in which the ticker did not appear is stored as a zero, not
    omitted. The SEC only lists securities with a non-zero balance, so absence
    IS the measurement. Dropping those periods would compute the median over
    non-zero periods only, understating every ratio — and would hide the most
    interesting case entirely: a name that never fails suddenly failing.
    """
    prior = [
        v["peak"] for p, v in state["history"].get(ticker, {}).items()
        if p < current_period
    ]
    if len(prior) < MIN_BASELINE_PERIODS:
        return None, len(prior)
    return statistics.median(prior), len(prior)


# ---------------------------------------------------------------- FORMAT ----


def fmt_shares(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def build_rows(current, state, period):
    rows = []
    for ticker, m in current.items():
        med, n = baseline(state, ticker, period)
        # med of 0 means every prior period was clean: the ratio is unbounded
        # rather than unknown, so it sorts to the top and can still flag.
        unbounded = med == 0 and n >= MIN_BASELINE_PERIODS
        ratio = (m["peak"] / med) if med else None
        enough = n >= MIN_FLAG_PERIODS and m["peak"] >= MIN_FLAG_SHARES
        flagged = bool(enough and (unbounded or (ratio and ratio >= FLAG_MULTIPLE)))
        rows.append({
            "ticker": ticker, "peak": m["peak"], "peak_date": m["peak_date"],
            "days": m["days"], "median": med, "ratio": ratio,
            "unbounded": unbounded, "flag": flagged,
            "thin": n < MIN_FLAG_PERIODS, "periods": n,
        })
    rows.sort(
        key=lambda r: (float("inf") if r["unbounded"] else (r["ratio"] or 0), r["peak"]),
        reverse=True,
    )
    return rows


def build_table(rows):
    """Kept to 22 characters. See the output-width note in the README.

    Every field is width-capped rather than trusted: an unusually large peak
    or ratio must not be able to push the table past the mobile wrap point,
    because the one day it happens is the day the table matters most.
    """
    out = [f"{'':<5}{'Peak':>6} {'xMed':>5} {'Dys':>4}"]
    out.append("-" * 22)
    for r in rows:
        if r["unbounded"]:
            ratio = ">99x"
        elif not r["ratio"]:
            ratio = "-"
        elif r["ratio"] > 99.9:
            ratio = ">99x"        # capped so it cannot widen the column
        else:
            ratio = f"{r['ratio']:.1f}x"
        mark = "*" if r["flag"] else ("~" if r["thin"] else " ")
        out.append(
            f"{r['ticker']:<5}{fmt_shares(r['peak']):>6} "
            f"{ratio:>5}{mark}{r['days']:>4}"
        )
    return "\n".join(out)


def build_embed(period, rows, missing, span):
    table = build_table(rows) if rows else "No fails recorded."
    lines = [f"```\n{table}\n```"]

    for r in [x for x in rows if x["flag"]]:
        d = r["peak_date"]
        detail = (f"first fails in {r['periods']} periods" if r["unbounded"]
                  else f"{r['ratio']:.1f}x its {fmt_shares(int(r['median']))} median")
        lines.append(
            f"**{r['ticker']}** {fmt_shares(r['peak'])} on {d[4:6]}-{d[6:]} — {detail}"
        )

    if missing and rows:
        lines.append(f"Zero balance all period: {', '.join(sorted(missing))}")
    if any(r["thin"] for r in rows):
        thin = ", ".join(r["ticker"] for r in rows if r["thin"])
        lines.append(f"`~` too little history for a baseline: {thin}")

    lines.append(
        "_Cumulative balance outstanding, not a daily flow — days are not "
        "additive. Fails occur on long and short sales alike and are not "
        "evidence of naked shorting._"
    )

    return {
        "title": f"Fails to deliver — {pretty(period)}",
        "description": "\n".join(lines),
        "color": 0xC77D2B if any(r["flag"] for r in rows) else 0x5A6672,
        # The baseline length belongs on the post. xMed is not a property of
        # the ticker, it is a property of the window: measured over 12 periods
        # instead of 6, NUAI's first reading moved from 27.0x to 4.3x and
        # DGXX's from 0.4x to 3.4x. A reader cannot judge the number without
        # knowing what it is divided by.
        "footer": {"text": "SEC CNS fails"
                           + (f" · settled {span}" if span else "")
                           + f" · xMed vs <={BASELINE_PERIODS - 1} prior periods"
                           + " · published with a 2-6 week lag"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------ POST ----


def post(embed):
    if "slack.com" in WEBHOOK:
        body = {"text": f"*{embed['title']}*\n{embed['description']}"}
    else:
        body = {"embeds": [embed]}
    for attempt in range(2):
        r = requests.post(WEBHOOK, json=body, timeout=30)
        if r.status_code == 429:
            wait = min(float(r.json().get("retry_after", 5)), 30)
            print(f"  rate limited, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return True
    return False


# ------------------------------------------------------------------ MAIN ----


def main():
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.")
    elif not WEBHOOK:
        print("WEBHOOK_URL_MARKET not set — exiting.")
        return 1
    if not USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.")
    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    state = load_state()
    sess = session()

    print("Reading SEC fails-to-deliver index...")
    periods = fetch_index(sess)
    if not periods:
        print("No cnsfails links found on the index page — layout changed?")
        return 1
    print(f"  {len(periods)} period(s) listed, newest {pretty(periods[0][0])}")

    newest = periods[0][0]
    if REPLAY:
        print(f"REPLAY: re-reading the newest {REPLAY} period(s). "
              f"Read-only — will not post, will not save state.")
    elif newest <= state["last_period"]:
        print(f"Already posted {pretty(newest)}. Nothing new.")
        return 0

    known = set(state["history"])
    cold = not known
    if REPLAY:
        wanted = periods[:REPLAY]
        state["history"] = {}          # baselines rebuilt from the replayed span
    elif cold:
        wanted = periods[:BASELINE_PERIODS]
    else:
        wanted = [(p, u) for p, u in periods[:BASELINE_PERIODS]
                  if p > state["last_period"]]
    if cold and not REPLAY:
        print(f"Cold start: pulling {len(wanted)} periods to build a baseline.")

    span, cusip_hist, overlapped = "", {}, set()
    for period, url in sorted(wanted):
        print(f"  {pretty(period)} ...", end=" ", flush=True)
        rows, learned, skipped, seen_syms = fetch_period(sess, url, state["cusips"])
        state["cusips"].update(learned)
        summary = summarise(rows)

        # Absence is a zero, and it is recorded as one. See baseline().
        for ticker in TICKERS:
            state["history"].setdefault(ticker, {})[period] = summary.get(
                ticker, {"peak": 0, "peak_date": None, "days": 0}
            )

        dates = sorted(d for e in rows.values() for d, _, _ in e)
        if period == newest and dates:
            span = f"{dates[0][4:6]}-{dates[0][6:]} to {dates[-1][4:6]}-{dates[-1][6:]}"

        for t, entries in rows.items():
            cusip_hist.setdefault(t, set()).update(c for _, _, c in entries if c)

        absent = [t for t in TICKERS if t not in summary]
        print(f"{len(summary)}/{len(TICKERS)}"
              + (f", zero: {' '.join(absent)}" if absent else "")
              + (f", {skipped} unparsable" if skipped else ""))

        # Two symbols mapping to one canonical ticker in a single period is
        # either a rename mid-period (benign) or a wrong alt_symbols entry
        # two companies (corrupting). Symbol count alone cannot tell them
        # apart, and neither can CUSIP: renames in this sector frequently
        # arrive alongside a reverse split, which changes the CUSIP too.
        #
        # Time separates them. A rename means the old symbol stops and the new
        # one starts, so the date sets are disjoint. Two live companies trade
        # on the same settlement days.
        for ticker, symmap in sorted(seen_syms.items()):
            if len(symmap) < 2:
                continue
            # Test INTERVAL overlap, not exact shared dates. This data is
            # sparse — only days with a non-zero balance appear — so two live
            # companies frequently miss each other's exact dates by chance. A
            # real observation: MARA 07-01..07-13 and CLSK 07-10..07-10 share
            # no date at all, yet plainly interleave. A rename is the strict
            # case where one symbol's whole range ends before the other begins.
            ordered = sorted(
                ((sym, min(ds), max(ds)) for sym, ds in symmap.items()),
                key=lambda t: t[1],
            )
            concurrent = any(
                ordered[i][2] >= ordered[i + 1][1] for i in range(len(ordered) - 1)
            )
            counts = Counter(d for ds in symmap.values() for d in ds)
            shared = sorted(d for d, n in counts.items() if n > 1)
            spans = ", ".join(f"{sym} {mmdd(lo)}..{mmdd(hi)}" for sym, lo, hi in ordered)
            if concurrent:
                overlapped.add(ticker)
                detail = (f", {len(shared)} shared settlement date(s)"
                          if shared else ", ranges interleave")
                print(f"    WARNING: {ticker} matched {len(symmap)} symbols"
                      f"{detail}: {spans}")
                print("      Concurrent trading means these are different"
                      " securities. Check alt_symbols in watchlist.py.")
            else:
                print(f"    note: {ticker} spans a rename — {spans}")
        time.sleep(REQUEST_GAP)

    # A ticker under two CUSIPs across the window is almost always a reverse
    # split. That matters more than the identifier: the SEC file carries RAW
    # share counts with no split adjustment, so peaks either side of one are
    # not comparable and the median silently misstates every later ratio.
    for t, cs in sorted(cusip_hist.items()):
        # Skip tickers already flagged for same-day symbol overlap: two live
        # securities merged also produces two CUSIPs, and "clear the history"
        # would be the wrong remedy for it.
        if len(cs) > 1 and t not in overlapped:
            print(f"\nWARNING: {t} appears under {len(cs)} CUSIPs: {', '.join(sorted(cs))}")
            print("  Usually a reverse split. Share counts are NOT split-adjusted in")
            print("  this dataset, so this ticker's baseline spans a discontinuity and")
            print("  its xMed is unreliable. Clear its history from ftd_state.json.")

    current = {
        t: v[newest] for t, v in state["history"].items()
        if newest in v and v[newest]["peak"] > 0
    }
    rows = build_rows(current, state, newest)
    missing = [t for t in TICKERS if t not in current]

    embed = build_embed(newest, rows, missing, span)
    print()
    print(build_table(rows) if rows else "No fails recorded.")
    if missing:
        print(f"Zero balance all period: {', '.join(sorted(missing))}")

    unpinned = {c: t for c, t in state["cusips"].items() if c not in CUSIP_PINS}
    if unpinned:
        print("\nCUSIPs seen in the data but absent from watchlist.py. Add each")
        print("to that company's `cusips` list so it survives a state rebuild:")
        for c, t in sorted(unpinned.items(), key=lambda kv: (kv[1], kv[0])):
            print(f'    "{c}": "{t}",')

    if REPLAY:
        print(f"\nReplay complete. Nothing posted, state untouched.")
        return 0
    if DRY_RUN:
        print(f"\nDry run: would post {pretty(newest)}. State not saved.")
        return 0

    if not post(embed):
        print("Post failed — state not advanced, will retry next run.")
        return 1

    state["last_period"] = newest
    save_state(state)
    print(f"\nPosted {pretty(newest)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
