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
from first_run import (backfill_note, backfilled, baseline_by_cik,
                       prune_unmeasured, summary)

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

# The `1yr` column compares against the closest observation AT LEAST a year
# old — but it must also be bounded above, or a company with sparse reporting
# gets a multi-year change printed in a column labelled one year.
#
# Observed: BKKT has three observations, two of them 2021-11-30 and 2026-03-11.
# Unbounded, its "1yr" figure would span four and a half years. Anything older
# than this is treated as no usable base, which is the honest answer.
MAX_BASE_AGE_DAYS = 550
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


# A period average, NEVER used as a share count. It is fetched only as a
# REFERENCE for the two currency tests below, because it is tagged every
# reporting period by companies that tag it at all, which makes its newest
# observation a reliable answer to "when did this company last report".
#
# It is deliberately absent from CONCEPTS. A weighted average over a period is
# a different quantity from a point-in-time count, and substituting one for the
# other would corrupt both the step and the trailing-year arithmetic while
# looking entirely plausible. GLXY's real figure sits in here at 390,482,653
# and it still does not belong in the table.
REFERENCE = ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")

# How far behind the reference a count may sit before it is not a current
# count. Expressed in the company's OWN reporting periods, derived from the
# spacing of the reference series, so a quarterly filer and an annual one are
# both judged against their own cadence rather than a shared number of days.
STALE_PERIODS = 1.5

# The count and the period average describe the same company in the same
# period, so they cannot differ by orders of magnitude. Ten is loose on
# purpose: a large mid-period issuance can move the two apart legitimately,
# and this is meant to catch a shell artefact, not to police a discrepancy.
IMPLAUSIBLE_RATIO = 10.0


def reference_series(cik):
    """[(as_of, value)] for REFERENCE, oldest first. Empty when not tagged."""
    payload = sec_get(CONCEPT_URL.format(cik=cik, taxonomy=REFERENCE[0],
                                         tag=REFERENCE[1]))
    if not payload:
        return []
    best = {}
    for r in payload.get("units", {}).get("shares", []):
        end, val, filed = r.get("end"), r.get("val"), r.get("filed", "")
        if not end or val is None:
            continue
        if end not in best or filed > best[end][1]:
            best[end] = (val, filed)
    return [(date.fromisoformat(e), int(v)) for e, (v, _) in sorted(best.items())]


def check_currency(series, ref):
    """Is the newest count a current count? Returns (reason, detail) or None.

    THE RULE, before the implementation. A share count is current only if its
    as-of date falls within one reporting period of the company's own most
    recent reporting period. Not within a fixed number of days: a 20-F filer
    reports annually and a 10-Q filer quarterly, and both are entitled to be
    judged against their own cadence.

    GLXY is why this exists. Its first probe misses, its second hits
    `us-gaap:CommonStockSharesOutstanding` and returns 100 shares as of
    2025-03-31, the pre-listing Delaware holdco's nominal count, tagged once in
    the first 10-Q and never superseded because later filings do not carry that
    concept. The value is real, correctly parsed and correctly attributed, and
    wrong by six orders of magnitude against a company with about 390 million
    shares. It is exactly the failure this repo treats as the serious one: a
    number that reads as valid.

    It went unpublished only because SPCX's honest absence stopped the post.
    That is luck, not a defence, which is why the test is here.

    Two independent tests, and either one is enough to withhold the row. The
    reference series carries both, so they cost one request between them.
    """
    if not ref or not series:
        return None                       # no reference: the test cannot run
    count_at, count_val = series[-1][0], series[-1][1]
    ref_at, ref_val = ref[-1][0], ref[-1][1]

    # The company's own reporting period, from the spacing of its own filings.
    gaps = [(b[0] - a[0]).days for a, b in zip(ref, ref[1:]) if (b[0] - a[0]).days > 0]
    if gaps:
        gaps.sort()
        period = gaps[len(gaps) // 2]
        behind = (ref_at - count_at).days
        if period > 0 and behind > STALE_PERIODS * period:
            return ("stale",
                    f"count as of {count_at} is {behind}d behind this company's "
                    f"most recent reported period {ref_at}, which is "
                    f"{behind / period:.1f} of its own {period}d reporting cycle")

    if ref_val > 0 and count_val > 0:
        ratio = max(count_val / ref_val, ref_val / count_val)
        if ratio > IMPLAUSIBLE_RATIO:
            return ("implausible",
                    f"count {count_val:,} differs from the same company's "
                    f"period average {ref_val:,} by {ratio:,.0f}x")
    return None


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
    year_base = None            # (date, shares) the year figure is measured from
    year_reason = None          # why year is absent: "split" or "thin"
    if split:
        year_reason = "split"
    else:
        target = latest_date - timedelta(days=YEAR_DAYS)
        floor = latest_date - timedelta(days=MAX_BASE_AGE_DAYS)
        older = [(d, v) for d, v, _ in series if floor <= d <= target]
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
                year_base = (base_date, base)

    return {"date": latest_date, "shares": latest, "form": form,
            "step": step, "prior": prior, "year": year, "split": split,
            "year_reason": year_reason, "obs": len(series), "drop": drop,
            "year_base": year_base}


def measured_ciks(rows, roster):
    """CIKs this run actually produced a share count for.

    `rows` is exactly the set `record()` writes, so this is the same question
    asked one step earlier: which companies does the state now say something
    about. The three `continue` paths above it — a fetch fault, an untagged
    filer, a count withheld as stale or implausible — all leave the company
    with no count, and none of them may claim it as established.

    The untagged case is the one worth naming, because it is not a fault and
    reads like a settled fact. A company that tags no share-count concept has
    nothing to suppress today; recording it anyway means its FIRST count, the
    day it starts tagging one, compares against nothing and posts as a change.
    ABTC, CRWV, GLXY and SPCX all sat in exactly that state on 2026-08-18.
    """
    cik_of = {t: c for t, (c, _) in roster.items()}
    return {cik_of[r["ticker"]] for r in rows if r["ticker"] in cik_of}


def record(state, rows):
    """Store each company's current count. Called on every saving path.

    `len(state)` is NOT the company count any more — `state` also carries the
    first-run `companies` record — so callers report `len(rows)`.
    """
    for r in rows:
        state[r["ticker"]] = {"shares": r["m"]["shares"],
                              "date": r["m"]["date"].isoformat()}


def is_change(ticker, prev, m, newly_watched):
    """Whether this company's share count moved since the last run.

    A NEWLY WATCHED COMPANY IS NOT A CHANGE. With no prior share count its
    first observation compares against nothing and counts as changed, which
    posts a dilution alert dated to the day it joined the roster rather than
    to any filing. Its count is still recorded by the caller, so the next
    genuine move posts normally.
    """
    if ticker in newly_watched:
        return False
    return (prev.get("shares") != m["shares"]
            or prev.get("date") != m["date"].isoformat())


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
    """Width-capped — but a cap must not swallow the answer.

    Past about 900% a percentage stops being readable and `>999%` hides the
    magnitude entirely: 1,000% and 10,000% render identically. Beyond that
    threshold the figure is shown as a MULTIPLE instead, which is both shorter
    and more informative — `16x` says what `>999%` refuses to.
    """
    if p is None:
        return "-"
    if p > 900:
        return f"{1 + p / 100:.0f}x"
    if p < -99:
        return "<-99%"
    return f"{p:+.0f}%"


def build_table(rows, unavailable=()):
    """Kept to 25 characters. See the output-width note in the README.

    `unavailable` companies are appended as `n/a~` rows rather than omitted. A
    company absent from the table reads as "no dilution", which is the opposite
    of unknown, and that reading is what used to make this component refuse to
    post at all. The `~` sits against the SHARES column because that is the
    figure that is missing; the change and trailing-year columns are blank
    because they are derived from it, not separately unavailable.
    """
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
    # Always last and always alphabetical. A row that is permanently n/a should
    # be boring: it must not move as other companies' growth figures move, and
    # it must not sit among them implying a rank it does not have.
    for tk, _reason in sorted(unavailable):
        # rstrip because the change and trailing-year columns are empty, and
        # thirteen trailing spaces in a code block are invisible padding that
        # only widens the line.
        out.append(f"{tk:<5}{'n/a~':>7}".rstrip())
    return "\n".join(out)


UNAVAILABLE_REASONS = {
    "untagged": "publishes no share count in any concept read here",
    "stale": "last published count predates its own most recent report",
    "implausible": "last published count disagrees with its own period average",
}


def build_embed(rows, changed, splits, unavailable=()):
    lines = [f"```\n{build_table(rows, unavailable)}\n```"]

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

    # One line per reason, never one line for all of them. "Does not publish a
    # count" and "publishes one that is out of date" are different findings
    # about a company, and a reader who cannot tell them apart learns nothing
    # from either.
    by_reason = {}
    for tk, reason in unavailable:
        by_reason.setdefault(reason, []).append(tk)
    for reason, tks in sorted(by_reason.items()):
        lines.append(f"`n/a~` {UNAVAILABLE_REASONS.get(reason, reason)}: "
                     f"{', '.join(sorted(tks))}")

    thin = [r["ticker"] for r in rows if r["m"]["year_reason"] == "thin"]
    if thin:
        lines.append(f"`~` under a year of reported history: {', '.join(thin)}")
    suppressed = [r["ticker"] for r in rows
                  if r["m"]["year_reason"] == "split" and not r["m"]["split"]]
    if suppressed:
        lines.append(f"`split` in the trailing year, growth not comparable: "
                     f"{', '.join(suppressed)}")

    # The column says `1yr`; the spans are whatever each company's filing dates
    # allow. Observed on the first live run: NUAI 365d, SLNH 418d, DGXX 500d —
    # DGXX covering 37% more time than NUAI while sitting in the same column.
    # The log shows each span, but a reader of the post cannot, so say it here.
    spans = [(r["ticker"], (r["m"]["date"] - r["m"]["year_base"][0]).days)
             for r in rows if r["m"]["year_base"]]
    if spans:
        lo, hi = min(d for _, d in spans), max(d for _, d in spans)
        stretched = [f"{t} {d}d" for t, d in sorted(spans, key=lambda x: -x[1])
                     if d > YEAR_DAYS + 20]
        note = (f"_`1yr` spans {lo}–{hi} days, not a uniform year: each figure is "
                f"measured against that company's closest reported count at least "
                f"{YEAR_DAYS} days old, and filing dates differ._")
        if stretched:
            note = note[:-1] + f" Longer than the label implies: {', '.join(stretched)}._"
        lines.append(note)

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
    rows, failed, unavailable, changed, splits = [], [], [], 0, 0
    backfill = backfilled(state)
    newly_watched = set(baseline_by_cik(state, watchlist.ciks()))
    if backfill:
        print("\n" + backfill_note("dilution", len(watchlist.tickers())))
    # The summary moved BELOW the loop, because it now names only companies
    # this run actually measured and that set does not exist yet here.
    any_drop = False

    for ticker, (cik, name) in sorted(watchlist.ciks().items()):
        try:
            series, concept = observations(cik)
        except Exception as e:
            # A FAULT, not a measurement. The company may well publish a count;
            # this run could not find out. Distinct from every case below, and
            # the only one that still refuses to post.
            print(f"  {ticker}: FAILED {type(e).__name__}: {e}")
            failed.append(ticker)
            continue
        if not series:
            print(f"  {ticker}: no share-count concept tagged "
                  f"({', '.join(f'{t}:{g}' for t, g in CONCEPTS)})")
            unavailable.append((ticker, "untagged"))
            continue

        # A count that is present but not current is worse than one that is
        # absent: it reads as valid. Withheld with its own reason, never
        # replaced by the reference, which measures a different quantity.
        try:
            verdict = check_currency(series, reference_series(cik))
        except Exception as e:
            print(f"  {ticker}: currency test unavailable "
                  f"({type(e).__name__}); reporting the count unchecked")
            verdict = None
        if verdict:
            reason, detail = verdict
            print(f"  {ticker}: share count WITHHELD, {reason} — {detail}")
            unavailable.append((ticker, reason))
            continue

        m = summarise(series)
        rows.append({"ticker": ticker, "name": name, "m": m, "concept": concept})
        prev = state.get(ticker, {})
        if is_change(ticker, prev, m, newly_watched):
            changed += 1
        if m["split"]:
            splits += 1
        print(f"  {ticker}: {fmt_shares(m['shares'])} as of {m['date']} "
              f"({m['form'] or '?'}, {len(series)} obs, {concept})")
        if m["year_base"] and m["year"] is not None and m["year"] >= NOTABLE_YEAR_PCT:
            bd, bv = m["year_base"]
            print(f"      1yr base {bd} {bv:,}  ->  {m['shares']:,}  "
                  f"({fmt_pct(m['year'])} over {(m['date'] - bd).days}d)")
        if m["drop"]:
            d = m["drop"]
            (d0, v0, f0), (d1, v1, f1) = d["from"], d["to"]
            ratio = f"{d['ratio']:.1f}:1" if d["ratio"] else "?"
            print(f"      drop {d0} {v0:,} ({f0 or '?'})  ->  "
                  f"{d1} {v1:,} ({f1 or '?'})  {ratio} over {(d1 - d0).days}d")
            any_drop = True
        time.sleep(REQUEST_GAP)

    if any_drop:
        # Printed once. Repeating it under every company was noise, and naming
        # SLNH as the example read oddly on SLNH's own row.
        print("\n  Ratios are a FLOOR on any split — dilution between the two")
        print("  observations pulls them down. The GAP is the sharper tell: a")
        print("  drop straddling filings a quarter apart is a corporate action;")
        print("  one straddling years is a reporting gap with an action inside.")

    if unavailable:
        # POSTED, not withheld. Refusing the whole post was right while there
        # was no way to say "unknown" in the table; there is one now, and
        # blocking sixteen companies' figures to avoid two n/a rows is the
        # wrong trade once the alternative is a sentence rather than ambiguity.
        print(f"\n{len(unavailable)} unavailable, shown as n/a in the table: "
              + ", ".join(f"{t} ({r})" for t, r in sorted(unavailable)))

    if failed:
        # A fetch fault is the one case that still refuses to post. The company
        # may publish a count and this run could not find out, so an n/a row
        # would assert something about the company that was really about the
        # network.
        print(f"\n{len(failed)} could not be fetched: {', '.join(failed)}")
        print("Not posting — this is a fault, not a measurement, and a company")
        print("shown as n/a for a network error asserts the wrong thing.")
        return 1

    # A COMPANY THIS RUN DID NOT MEASURE IS NOT ESTABLISHED. Placed after the
    # loop because that is the first point the measured set exists, and before
    # every save below. A pruned company is suppressed on the day it is first
    # measured instead, which is the whole intent.
    # TWO UNITS, deliberately kept apart. The RECORD is keyed by CIK, because
    # a ticker is a display label; `newly_watched` is tickers, because that is
    # what the loop above and every log line speak. Intersecting one with the
    # other would silently empty the set.
    cik_of = {t: c for t, (c, _) in watchlist.ciks().items()}
    measured_tickers = {r["ticker"] for r in rows}
    # Held state, computed BEFORE record() writes: a company with a stored
    # count has been measured on some earlier run and is established whatever
    # this one managed. Without it, a single withheld or untagged reading
    # would un-establish an established company, and the next run would
    # suppress a real share-count move that record() then overwrites.
    has_state = {cik_of[t] for t in state if t in cik_of}
    deferred = prune_unmeasured(state, measured_ciks(rows, watchlist.ciks()),
                                set(cik_of.values()), has_state)
    if deferred:
        by_cik = {c: t for t, c in cik_of.items()}
        why = dict(unavailable)
        print("\nFirst-run record DEFERRED for "
              + ", ".join(f"{by_cik.get(c, c)} ({why.get(by_cik.get(c, c), 'no count')})"
                          for c in deferred)
              + " — not measured this run, so nothing is claimed about them.")
    # And the log line follows the record: without this, `summary` names a
    # company every run until it is finally measured, which for SPCX at 46 of
    # 60 sessions would be fourteen sessions of a line built to be read once.
    newly_watched &= measured_tickers
    if newly_watched:
        print()
        print(summary("dilution", sorted(newly_watched)))

    rows.sort(key=lambda r: (r["m"]["year"] if r["m"]["year"] is not None else -1e9),
              reverse=True)

    print()
    print(build_table(rows, unavailable))
    print()
    print(f"{changed} of {len(rows)} changed since last run"
          + ("  (no state file — first run)" if first_run else ""))

    if not changed:
        print("No change. Nothing to post.")
        # A dry run saves nothing, so there is no reason to withhold the
        # output. Without this the embed is unpreviewable once state exists —
        # and for a component that posts only on a filing, that could be weeks.
        if DRY_RUN:
            print("\nDry run: nothing changed, but this is what a post would "
                  "look like.\n")
            print(build_embed(rows, 0, splits, unavailable)["description"])
            return 0
        # STATE IS WRITTEN ON THE QUIET PATH TOO. Before this it was written
        # only after a successful post, which for this component can be weeks
        # apart, and that made the first-run rule inert for exactly that long:
        # the `companies` record was rebuilt and thrown away every run, so
        # every run printed "this is the backfill and it happens once" and
        # meant it. The first company added in that window would then be
        # newly watched against an absent record — no suppression — and post
        # a share-count alert dated to the day it joined the roster.
        #
        # Recording every row here is a no-op for established companies,
        # since `changed` is zero, and records the newly watched ones, which
        # is what the suppression above promised.
        record(state, rows)
        save_state(state)
        print(f"State written: {STATE_FILE.name} ({len(rows)} companies)")
        return 0

    embed = build_embed(rows, changed, splits, unavailable)

    if DRY_RUN:
        print(f"\nDry run: would post. State not saved.")
        return 0

    if not post(embed):
        print("Post failed — state not saved, will retry next run.")
        return 1

    record(state, rows)
    save_state(state)
    print(f"State written: {STATE_FILE.name} ({len(rows)} companies)")
    print("Posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
