#!/usr/bin/env python3
"""
Shares outstanding -> Discord.

Tracks dilution: the share count each company reports on the cover of its own
filings, and how fast it is growing.

WHY THIS MATTERS FOR THIS WATCHLIST
Bitcoin miners and digital-infrastructure companies fund themselves largely by
issuing stock — at-the-market programmes that sell continuously into the market
rather than in discrete raises. NUAI, for instance, is contracted to establish a
$100M ATM against a company whose whole off-exchange daily volume runs a few
million shares.

The consequence is that share count erodes returns quietly. A stock flat on the
year with 40% more shares outstanding has lost 40% of its per-share claim on the
business, and nothing else in this repo would show that. Price feeds show price.
This shows the denominator.

Data: SEC XBRL companyconcept API, keyed by CIK. No auth beyond a contact
string in SEC_USER_AGENT.

WHAT THIS IS NOT
Not a float, and not a market cap input without care. The cover-page count is
total shares outstanding as of a date near filing — it includes insider and
restricted holdings, and it excludes warrants, options and convertibles that
have not been exercised. For companies with large warrant overhangs, and
several here have them, the fully diluted figure is higher than anything
reported below.
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import watchlist

# ------------------------------------------------------------------ CONFIG

# Probed in order; the first that returns data for a company is used, and the
# choice is reported per company in the log. Filers do not agree on which
# concept carries this: `dei` is the cover-page tag and is present on every
# periodic filing, but foreign private issuers and older filings vary.
CONCEPTS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesIssued"),
]

# A single reported step above this is called out in prose.
NOTABLE_STEP_PCT = 10.0

# Trailing growth above this is flagged in the table.
NOTABLE_YEAR_PCT = 25.0

# CRITICAL: XBRL share counts are NOT split-adjusted. A 1-for-10 reverse split
# drops the reported count by 90%, which reads as a spectacular share buyback.
# Any decrease steeper than this is treated as a corporate action rather than a
# reduction, labelled as such, and excluded from growth arithmetic.
#
# Genuine buybacks in this sector are rare and small; none of these companies
# has the cash. Reverse splits are common — ANY, BGDE, BKKT, SLNH and VIP have
# all done one. A decrease of this size is far more likely to be a split.
SPLIT_DROP_PCT = 35.0

YEAR_DAYS = 365
STATE_FILE = Path(os.environ.get("DILUTION_STATE", "dilution_state.json"))
REQUEST_GAP = 0.2

# ----------------------------------------------------------------- RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

CONCEPT_URL = ("https://data.sec.gov/api/xbrl/companyconcept/"
               "CIK{cik}/{taxonomy}/{tag}.json")

RED, AMBER, GREY = 0xF85149, 0xD29922, 0x5A6672


# ------------------------------------------------------------------- STATE


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


# ------------------------------------------------------------------- FETCH


def sec_get(url):
    r = requests.get(
        url,
        headers={"User-Agent": SEC_USER_AGENT or "watchlist-monitor contact@example.com",
                 "Accept-Encoding": "gzip, deflate"},
        timeout=(10, 30),
    )
    if r.status_code == 404:
        return None                      # concept not tagged by this filer
    r.raise_for_status()
    return r.json()


def observations(cik):
    """[(as_of date, shares, form)] oldest first, plus the concept used.

    One observation per as-of date, preferring the most recently FILED value so
    an amended filing supersedes the original rather than sitting beside it.
    """
    for taxonomy, tag in CONCEPTS:
        payload = sec_get(CONCEPT_URL.format(cik=cik, taxonomy=taxonomy, tag=tag))
        if not payload:
            continue
        rows = payload.get("units", {}).get("shares", [])
        if not rows:
            continue
        best = {}
        for r in rows:
            end, val, filed = r.get("end"), r.get("val"), r.get("filed", "")
            if not end or val is None:
                continue
            if end not in best or filed > best[end][2]:
                best[end] = (end, val, filed, r.get("form", ""))
        series = [(date.fromisoformat(e), int(v), f)
                  for e, v, _, f in sorted(best.values())]
        if series:
            return series, f"{taxonomy}:{tag}"
    return [], None


# --------------------------------------------------------------- ANALYSIS


def pct(new, old):
    return None if not old else (new - old) / old * 100.0


def summarise(series):
    """Latest count, step since the prior observation, and trailing-year growth.

    A step steeper than -SPLIT_DROP_PCT is reported as a corporate action, not
    a reduction, and suppresses the year figure — a series spanning a split is
    not comparable across it.
    """
    latest_date, latest, form = series[-1]
    step = prior = None
    if len(series) >= 2:
        prior = series[-2][1]
        step = pct(latest, prior)

    split = step is not None and step <= -SPLIT_DROP_PCT

    # Which two observations straddle the drop, and the implied ratio. A
    # reverse split lands near a round ratio (1-for-25 -> ~25). A tagging
    # change — a filer switching from reporting all share classes to reporting
    # one — lands on an arbitrary one. The component cannot tell them apart,
    # but the numbers can, so it prints them rather than only its verdict.
    drop = None
    for (d0, v0, f0), (d1, v1, f1) in zip(series, series[1:]):
        p = pct(v1, v0)
        if p is not None and p <= -SPLIT_DROP_PCT:
            drop = {"from": (d0, v0, f0), "to": (d1, v1, f1),
                    "ratio": (v0 / v1) if v1 else None}

    year = None
    year_reason = None          # why year is absent: "split" or "thin"
    if split:
        year_reason = "split"
    else:
        target = latest_date - timedelta(days=YEAR_DAYS)
        older = [(d, v) for d, v, _ in series if d <= target]
        if not older:
            # No observation a year back. Distinct from a split: this company
            # has not been reporting long enough, which is information about
            # the company rather than about the arithmetic.
            year_reason = "thin"
        else:
            base_date, base = older[-1]
            # A split anywhere in the window invalidates the comparison too,
            # not only one in the most recent step.
            window = [v for d, v, _ in series if d >= base_date]
            drops = [pct(b, a) for a, b in zip(window, window[1:])]
            if any(x is not None and x <= -SPLIT_DROP_PCT for x in drops):
                year_reason = "split"
            else:
                year = pct(latest, base)

    return {"date": latest_date, "shares": latest, "form": form,
            "step": step, "prior": prior, "year": year, "split": split,
            "year_reason": year_reason, "obs": len(series), "drop": drop}


# ------------------------------------------------------------------ FORMAT


def fmt_shares(n):
    if n >= 1_000_000_000:
        return f"{n / 1e9:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n / 1e3:.0f}K"
    return str(n)


def fmt_pct(p):
    """Width-capped: an extreme reading must not widen the table."""
    if p is None:
        return "-"
    if p > 999:
        return ">999%"
    if p < -99:
        return "<-99%"
    return f"{p:+.0f}%"


def build_table(rows):
    """Kept to 25 characters. See the output-width note in the README."""
    out = [f"{'':<5}{'Shares':>7}{'Chg':>6}{'1yr':>7}", "-" * 25]
    for r in rows:
        m = r["m"]
        step = "split" if m["split"] else fmt_pct(m["step"])
        # `-` alone conflated two opposite meanings: a split makes the
        # comparison invalid, thin history makes it unavailable.
        if m["year"] is not None:
            year, mark = fmt_pct(m["year"]), ("*" if m["year"] >= NOTABLE_YEAR_PCT else "")
        elif m["year_reason"] == "split":
            year, mark = "split", ""
        else:
            year, mark = "-", "~"
        out.append(f"{r['ticker']:<5}{fmt_shares(m['shares']):>7}"
                   f"{step:>6}{(year + mark):>7}"[:25])
    return "\n".join(out)


def build_embed(rows, changed, splits):
    lines = [f"```\n{build_table(rows)}\n```"]

    for r in rows:
        m = r["m"]
        if m["split"]:
            lines.append(
                f"**{r['ticker']}** reported count fell "
                f"{fmt_shares(m['prior'])} → {fmt_shares(m['shares'])} — almost "
                f"certainly a reverse split, not a buyback. Growth suppressed.")
        elif m["step"] is not None and m["step"] >= NOTABLE_STEP_PCT:
            lines.append(
                f"**{r['ticker']}** +{m['step']:.0f}% in one filing, "
                f"{fmt_shares(m['prior'])} → {fmt_shares(m['shares'])} "
                f"(as of {m['date']:%d %b})")

    thin = [r["ticker"] for r in rows if r["m"]["year_reason"] == "thin"]
    if thin:
        lines.append(f"`~` under a year of reported history: {', '.join(thin)}")
    suppressed = [r["ticker"] for r in rows
                  if r["m"]["year_reason"] == "split" and not r["m"]["split"]]
    if suppressed:
        lines.append(f"`split` in the trailing year, growth not comparable: "
                     f"{', '.join(suppressed)}")

    lines.append(
        "_Cover-page shares outstanding, as of each filing's own date — not a "
        "float, and excluding unexercised warrants, options and convertibles. "
        "XBRL counts are not split-adjusted._")

    colour = RED if splits else (AMBER if changed else GREY)
    return {
        "title": "Shares outstanding",
        "description": "\n".join(lines),
        "color": colour,
        "footer": {"text": f"SEC XBRL · {changed} company/companies changed"},
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
        sys.exit("WEBHOOK_URL_MARKET is not set.")
    if not SEC_USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.\n")

    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    state = load_state()
    first_run = not STATE_FILE.exists()
    rows, failed, changed, splits = [], [], 0, 0

    for ticker, (cik, name) in sorted(watchlist.ciks().items()):
        try:
            series, concept = observations(cik)
        except Exception as e:
            print(f"  {ticker}: FAILED {type(e).__name__}: {e}")
            failed.append(ticker)
            continue
        if not series:
            print(f"  {ticker}: no share-count concept tagged "
                  f"({', '.join(f'{t}:{g}' for t, g in CONCEPTS)})")
            failed.append(ticker)
            continue

        m = summarise(series)
        rows.append({"ticker": ticker, "name": name, "m": m, "concept": concept})
        prev = state.get(ticker, {})
        if prev.get("shares") != m["shares"] or prev.get("date") != m["date"].isoformat():
            changed += 1
        if m["split"]:
            splits += 1
        print(f"  {ticker}: {fmt_shares(m['shares'])} as of {m['date']} "
              f"({m['form'] or '?'}, {len(series)} obs, {concept})")
        if m["drop"]:
            d = m["drop"]
            (d0, v0, f0), (d1, v1, f1) = d["from"], d["to"]
            ratio = f"{d['ratio']:.1f}:1" if d["ratio"] else "?"
            print(f"      drop {d0} {v0:,} ({f0 or '?'})  ->  "
                  f"{d1} {v1:,} ({f1 or '?'})  ratio {ratio}")
            print(f"      near a round ratio = reverse split; "
                  f"arbitrary = possible tagging change")
        time.sleep(REQUEST_GAP)

    if failed:
        print(f"\n{len(failed)} company/companies unavailable: {', '.join(failed)}")
        print("Not posting a partial picture — a company missing from the table")
        print("would read as 'no dilution', which is the opposite of unknown.")
        return 1

    rows.sort(key=lambda r: (r["m"]["year"] if r["m"]["year"] is not None else -1e9),
              reverse=True)

    print()
    print(build_table(rows))
    print()
    print(f"{changed} of {len(rows)} changed since last run"
          + ("  (no state file — first run)" if first_run else ""))

    if not changed:
        print("No change. Nothing to post.")
        return 0

    embed = build_embed(rows, changed, splits)

    if DRY_RUN:
        print(f"\nDry run: would post. State not saved.")
        return 0

    if not post(embed):
        print("Post failed — state not saved, will retry next run.")
        return 1

    for r in rows:
        state[r["ticker"]] = {"shares": r["m"]["shares"],
                              "date": r["m"]["date"].isoformat()}
    save_state(state)
    print(f"State written: {STATE_FILE.name} ({len(state)} companies)")
    print("Posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
