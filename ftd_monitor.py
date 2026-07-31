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
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

# ---------------------------------------------------------------- CONFIG ----

TICKERS = [
    "MARA", "CLSK", "BKKT", "NUAI", "IREN",
    "VIP", "ANY", "SLNH", "BGDE", "WYFI", "DGXX",
]

# Historical or pending symbols -> canonical symbol. This sector renames
# constantly, and unlike the FINRA components this one reads BACKWARDS through
# several months of files, so old symbols genuinely appear in the data. Keep in
# sync with short_interest.py and regsho_volume.py.
ALIASES = {
    "GREE": "VIP",    # Greenidge Generation -> Vulcan Infra & Power, 24 Jul 2026
    "MIGI": "BGDE",   # Mawson Infrastructure -> Big Digital Energy, 30 Apr 2026
    "DRK": "ANY",     # pending: ANY -> DarkHorse
}

# CUSIPs pinned by hand, merged into the learned map at startup. Pinning is the
# permanent fix for a rename: both companies above kept their CUSIP through the
# change (Big Digital's 8-K says so explicitly), so a pinned CUSIP survives
# renames that ALIASES only handles once someone notices them.
CUSIP_PINS = {}

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

CANON = {t: t for t in TICKERS}
CANON.update(ALIASES)

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


def pretty(period):
    return f"{period[:4]}-{period[4:6]}{period[6]}"


def fetch_period(sess, url, cusips):
    """Download one half-month zip and return {ticker: [(date, qty, cusip)]}.

    Matching is by symbol OR by a CUSIP already learned for that ticker, so a
    rename part-way through the baseline window doesn't silently drop history.
    """
    r = sess.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    member = next(n for n in zf.namelist() if not n.endswith("/"))
    raw = zf.read(member).decode("latin-1")

    rows, learned, skipped, seen_syms = {}, {}, 0, {}
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        date, cusip, symbol, qty = (p.strip() for p in parts[:4])
        if not date.isdigit() or len(date) != 8:
            continue          # header and any trailer line
        ticker = CANON.get(symbol.upper()) or cusips.get(cusip)
        if not ticker:
            continue
        try:
            shares = int(qty)
        except ValueError:
            skipped += 1
            continue
        rows.setdefault(ticker, []).append((date, shares, cusip))
        seen_syms.setdefault(ticker, set()).add(symbol.upper())
        if cusip and cusip not in cusips:
            learned[cusip] = ticker
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
        "footer": {"text": "SEC CNS fails"
                           + (f" · settled {span}" if span else "")
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

    state = load_state()
    sess = session()

    print("Reading SEC fails-to-deliver index...")
    periods = fetch_index(sess)
    if not periods:
        print("No cnsfails links found on the index page — layout changed?")
        return 1
    print(f"  {len(periods)} period(s) listed, newest {pretty(periods[0][0])}")

    newest = periods[0][0]
    if newest <= state["last_period"]:
        print(f"Already posted {pretty(newest)}. Nothing new.")
        return 0

    known = set(state["history"])
    cold = not known
    wanted = periods[:BASELINE_PERIODS] if cold else [
        (p, u) for p, u in periods[:BASELINE_PERIODS] if p > state["last_period"]
    ]
    if cold:
        print(f"Cold start: pulling {len(wanted)} periods to build a baseline.")

    span = ""
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

        absent = [t for t in TICKERS if t not in summary]
        print(f"{len(summary)}/{len(TICKERS)}"
              + (f", zero: {' '.join(absent)}" if absent else "")
              + (f", {skipped} unparsable" if skipped else ""))

        # A canonical ticker matched under two different symbols in one period
        # is the signature of a wrong ALIASES entry: the alias and the real
        # symbol are both live, so one company's fails are being merged into
        # another's. Silent otherwise, and it corrupts the series.
        for ticker, syms in seen_syms.items():
            if len(syms) > 1:
                print(f"    WARNING: {ticker} matched {'/'.join(sorted(syms))}"
                      f" — check ALIASES, these may be different companies")
        time.sleep(REQUEST_GAP)

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
