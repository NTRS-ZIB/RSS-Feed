#!/usr/bin/env python3
"""
Weekly digest — derivation and verdict record. NOTHING IS RENDERED HERE.

This file answers two questions about a week, and it answers them by
RE-DERIVING FROM SOURCE rather than by aggregating the week's Discord posts.

  "what happened"     the summary
  "what did I miss"   the filter, and the more valuable half

WHY IT RE-DERIVES
-----------------
Measured over the run history 2026-07-29 to 2026-08-05: the daily workflows
delivered 3-4 of their 5-6 nominal scheduled fires each, the press monitor 42 of
~102, volume spikes 29 of ~80. `docs/rejected.md` records the same thing as a
rate — GitHub drops 30-45% of scheduled fires on this repo. A digest built from
posts would inherit every one of those gaps and report a quiet monitor as a
quiet week.

Two further reasons, either sufficient on its own:

  * The change-only components post nothing in the interesting case. The
    threshold list, crossings, dilution and comment letters post only on a
    change, so a company sitting on the Reg SHO threshold list all week
    generates ZERO posts while being maximally interesting.
  * Re-deriving decouples the digest from every component's output format. A
    component changing how it renders cannot break this.

THE THREE LAYERS
----------------
    derive  ->  the verdict record  ->  a Discord post
                                    ->  a markdown file

Only the first two exist. The verdict record is not architecture for its own
sake: to say "SLNH, third week running" the digest must know what it concluded
LAST week, and a digest whose only stored output is prose would have to parse
its own prose — which is aggregating posts, one level in. Measured over four
weeks of real short-volume data, SLNH qualifies in weeks 2, 3 and 4. No daily
post can see that. Neither can a renderer without this record.

CADENCE IS LOAD-BEARING
-----------------------
Every contributor declares a cadence, and PERSISTENCE ELIGIBILITY IS DERIVED
FROM IT rather than remembered by whoever writes the next contributor. A
contributor whose source publishes fortnightly cannot emit a persistence claim
about a week — `mk()` raises rather than trusting the author to recall the rule.
That is the whole reason the field exists.

The rule is mechanical: a measure can carry a persistence claim only if it
produces MORE THAN ONE INDEPENDENT OBSERVATION INSIDE THE WEEK BEING DESCRIBED.

Fails-to-deliver is the case that will tempt you. A half-month file holds ~10
settlement dates, so "failed on 8 of 10" IS a persistence statement — about a
period that ended up to six weeks ago. Attaching it to "this week" is exactly
the *number true about something adjacent to the question* failure in
CLAUDE.md, and nothing would flag it. Its verdicts are keyed by PERIOD.

RUNNING IT
----------
    DIGEST_BACKFILL=10 python -u weekly_digest.py

derives the last N complete ISO weeks and prints the convergence distribution.
Do not run it locally: it needs SEC_USER_AGENT and the Alpaca keys, which exist
only in GitHub Actions. Use the workflow:

    gh workflow run "Weekly digest" -f backfill=10

It posts nothing and commits nothing. There is no rendering to post yet.
"""

import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

import watchlist

# The 8-K item taxonomy is press_monitor.py's, imported rather than copied.
#
# The digest asks a DIFFERENT question — "was this week material for this
# company" against "should this be posted right now" — but it must not maintain
# a second copy of the ANSWER. ALWAYS_POST_ITEMS carries measurements taken over
# 1,986 filings (4.02 dropped ten times out of ten, 5.02 considered and
# excluded, never add 9.01); a second copy would drift from those the first time
# either file was edited alone. watchlist.py exists because the roster was
# defined eight times in five shapes. This is the same argument, smaller.
#
# The cost is one import of a 1300-line module and its feedparser dependency.
# press_monitor.py has no module-level side effects — it reads env vars into
# constants and exits nowhere — so importing it is safe.
from press_monitor import (ALWAYS_POST_ITEMS, ITEM_LABELS,  # noqa: E402
                           PRESS_RELEASE_ITEMS)

# Identity guards live in the components that own them. ftd_monitor.fetch_period
# carries all three — refused CUSIPs, symbol-handover dates, and the prefix
# learning rule — and re-implementing them here is the single most dangerous
# thing this file could do: a wrong identifier silently attributes another
# security's rows to a company that never had them. See the SPCX case in
# docs/watchlist.md.
import ftd_monitor                                          # noqa: E402
import dilution                                             # noqa: E402
import regsho_volume                                        # noqa: E402
import short_interest                                       # noqa: E402

# ------------------------------------------------------------------ ROSTER --

TICKERS = watchlist.tickers()
CIKS = watchlist.ciks()
ALIASES = watchlist.alt_by_ticker()
CUSIP_PINS = watchlist.cusip_pins()

# ----------------------------------------------------------------- CADENCE --

# What a source's publication rhythm is. The only thing read from this is
# whether a week contains enough independent observations to support a
# persistence claim.
DAILY = "daily"                  # a value per trading session
EVENT = "event"                  # occurs or does not; no rhythm
PER_FILING = "per-filing"        # updates when the company files
TWICE_MONTHLY = "twice-monthly"  # FINRA short interest
HALF_MONTHLY = "half-monthly"    # SEC fails to deliver

# THE MECHANICAL GATE. Only these cadences may carry a persistence claim.
# Everything else raises in mk() rather than relying on the author to remember.
PERSISTENCE_CADENCES = {DAILY}

# --------------------------------------------------------------- VERDICTS --

NOTABLE = "notable"            # this component would flag this ticker this week
ROUTINE = "routine"            # measured, nothing to say — NOT the same as absent
NOT_TESTABLE = "not-testable"  # too little usable data to apply the rule
SOURCE_FAILED = "source-failed"  # the fetch failed; says nothing about the company

# Only NOTABLE counts toward convergence. NOT_TESTABLE and SOURCE_FAILED are
# carried through to the record rather than collapsed into ROUTINE, because
# "we could not tell" and "we looked and there was nothing" are different
# measurements and this repo does not let them share a label.


class DigestError(Exception):
    pass


def mk(contributor, level, figure=None, basis=None, sources=(),
       persistence=None, detail=None):
    """Build one verdict, enforcing the cadence rule.

    `persistence` is a dict describing a claim that spans sessions — e.g.
    {"hits": 4, "of": 5, "direction": "up"}. Supplying one from a contributor
    whose source does not publish daily is a bug, and it is a bug that nothing
    downstream could catch: the claim would read as true and be about a
    fortnight-old measurement. So it raises here, at the point of construction,
    on the contributor's own declared cadence.
    """
    if persistence is not None and contributor["cadence"] not in PERSISTENCE_CADENCES:
        raise DigestError(
            f"{contributor['key']} declares cadence '{contributor['cadence']}' "
            f"and cannot carry a persistence claim about a week. Its source "
            f"produces at most one observation per week. If this is wrong, the "
            f"cadence is wrong — do not remove the check.")
    return {
        "level": level,
        "figure": figure,
        "basis": basis,
        "sources": list(sources),
        "persistence": persistence,
        "detail": detail or {},
    }


# ------------------------------------------------------------------ WEEKS ---


def iso_week_key(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_sessions(monday):
    """Monday to Friday. Market holidays fall out naturally — a source simply
    has no row for them, which is the honest representation."""
    return [monday + timedelta(days=i) for i in range(5)]


def recent_weeks(n, today=None):
    """The last n COMPLETE ISO weeks, oldest first.

    Complete means its Friday has passed. A week still running would report a
    three-session persistence measure as a five-session one, which is the same
    class of error as a short baseline reported as a full one.
    """
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_complete_monday = this_monday - timedelta(days=7)
    if today.weekday() >= 5:          # Sat/Sun: this week's Friday has passed
        last_complete_monday = this_monday
    return [last_complete_monday - timedelta(days=7 * i)
            for i in range(n - 1, -1, -1)]


# ----------------------------------------------------------------- SOURCES --

# Every source is fetched ONCE for the whole backfill span and sliced per week.
# That is what makes a ten-week backfill cost about what one week costs: the
# FINRA short-volume call is one POST for the entire span (measured: 2.1s for
# 2,275 rows over 60 days), and the EDGAR submissions payload for a company
# carries a year of filings in one request.

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()

ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_FEED = "sip"          # NOT iex. See the feed note in fetch_bars().
FINRA_SHOVOL = ("https://api.finra.org/data/group/otcMarket/name/regShoDaily")
FINRA_SHORTINT = ("https://api.finra.org/data/group/otcMarket/name/"
                  "consolidatedShortInterest")
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{acc}-index.htm"
NASDAQ_TH = ("https://www.nasdaqtrader.com/dynamic/symdir/regsho/"
             "nasdaqth{stamp}.txt")
BROWSERISH = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/plain,*/*;q=0.8",
}


def canonical(symbol):
    """Any symbol a company has traded under -> its current ticker.

    Derived from watchlist.alt_by_ticker(), never hand-maintained. Writing this
    map backwards is how GREE was once attributed to Soluna, merging two
    companies under a plausible number with no error raised anywhere.
    """
    symbol = (symbol or "").upper().strip()
    if symbol in TICKERS:
        return symbol
    for ticker, alts in ALIASES.items():
        if symbol in (a.upper() for a in alts):
            return ticker
    return None


def query_symbols():
    out = list(TICKERS)
    for alts in ALIASES.values():
        out.extend(alts)
    return out


class Source:
    """A fetched source plus how the fetch went.

    `status` is carried into the record so a renderer can never mistake "the
    source failed" for "nothing happened". A file with a silent hole in it is
    the failure mode this whole design exists to avoid, and it is worse in an
    article-source artefact than in a post: a post is read once, a file is
    quoted.
    """

    def __init__(self, key):
        self.key = key
        self.data = None
        self.status = "unfetched"
        self.note = ""
        self.seconds = 0.0
        self.requests = 0

    def ok(self):
        return self.status == "ok"

    def summary(self):
        return {"status": self.status, "note": self.note,
                "seconds": round(self.seconds, 1), "requests": self.requests}


# FINRA CAPS EVERY RESPONSE AT 5,000 ROWS AND SAYS NOTHING ABOUT IT. Measured
# 2026-08-05: asking for 20,000, 25,000, 50,000 or 60,000 all return exactly
# 5,000, with HTTP 200 and no marker of any kind. A 60-day window fits inside
# that (2,275 rows) and a 200-day one does not, so this truncates silently at
# exactly the point a backfill gets long enough to be worth running — the
# result would be a baseline built from a fraction of the sessions, reported as
# a full one.
#
# Paginated by `offset`. An offset past the end of the result set returns HTTP
# 400 rather than an empty list, so that is treated as end-of-data ONLY after a
# full page has already come back; a 400 on the first page is a real error.
FINRA_PAGE = 5000
FINRA_MAX_PAGES = 20


def finra_query(url, payload, label):
    """Every row matching `payload`, paginated. (rows, pages, note)."""
    rows, pages = [], 0
    while pages < FINRA_MAX_PAGES:
        body = dict(payload, limit=FINRA_PAGE, offset=pages * FINRA_PAGE)
        r = requests.post(url, json=body, timeout=(10, 90),
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json"})
        if r.status_code == 400 and pages:
            break                       # offset past the end of the result set
        r.raise_for_status()
        page = r.json()
        pages += 1
        rows.extend(page)
        if len(page) < FINRA_PAGE:
            break
    note = f"{len(rows)} rows in {pages} page(s)"
    if pages >= FINRA_MAX_PAGES:
        # Never a silent cap. If this ever prints, the window is too wide for
        # the page budget and the data behind it is incomplete.
        note += f" — HIT THE {FINRA_MAX_PAGES}-PAGE CEILING, {label} TRUNCATED"
    return rows, pages, note


# Calendar days of history to pull BEFORE the backfill span, so the first week
# in the span has a full trailing baseline rather than an empty one. 60 days
# comfortably covers regsho_volume.BASELINE_DAYS sessions plus weekends and
# holidays — its own LOOKBACK_DAYS is 45 for a 20-session baseline.
SHOVOL_REACHBACK = 60


def fetch_short_volume(span_start):
    """FINRA Reg SHO daily short sale volume for the span and its baseline.

    Aggregated across market centres: FINRA reports per reporting facility
    (ADF, the Nasdaq TRFs, the NYSE TRF), so one symbol-day arrives as several
    rows and the quantities must be summed. Treating one row as the day's total
    understates volume badly.
    """
    src = Source("short_volume")
    t0 = time.time()
    since = (span_start - timedelta(days=SHOVOL_REACHBACK)).isoformat()
    payload = {
        "compareFilters": [{"fieldName": "tradeReportDate",
                            "compareType": "gte", "fieldValue": since}],
        "domainFilters": [{"fieldName":
                           "securitiesInformationProcessorSymbolIdentifier",
                           "values": query_symbols()}],
    }
    try:
        rows, pages, note = finra_query(FINRA_SHOVOL, payload, "short volume")
        src.requests = pages
    except (requests.RequestException, ValueError) as e:
        src.status, src.note = "failed", f"{type(e).__name__}"
        src.seconds = time.time() - t0
        return src

    series = defaultdict(dict)
    for row in rows:
        t = canonical(row.get("securitiesInformationProcessorSymbolIdentifier"))
        day = str(row.get("tradeReportDate") or "")[:10]
        total = float(row.get("totalParQuantity") or 0)
        if not t or not day or total <= 0:
            continue
        short = (float(row.get("shortParQuantity") or 0)
                 + float(row.get("shortExemptParQuantity") or 0))
        bucket = series[t].setdefault(day, [0.0, 0.0])
        bucket[0] += short
        bucket[1] += total
    src.data = {t: dict(v) for t, v in series.items()}
    days = sorted({d for v in series.values() for d in v})
    src.status = "ok"
    src.note = (f"{note}, {len(src.data)} tickers, "
                f"{len(days)} sessions {days[0]}..{days[-1]}"
                if days else f"{note}, no sessions parsed")
    src.seconds = time.time() - t0
    return src


def fetch_short_interest():
    """FINRA consolidated short interest. Anonymous — confirmed 2026-08."""
    src = Source("short_interest")
    t0 = time.time()
    payload = {"compareFilters": [],
               "domainFilters": [{"fieldName": "symbolCode",
                                  "values": query_symbols()}]}
    try:
        rows, pages, note = finra_query(FINRA_SHORTINT, payload,
                                        "short interest")
        src.requests = pages
    except (requests.RequestException, ValueError) as e:
        src.status, src.note = "failed", f"{type(e).__name__}"
        src.seconds = time.time() - t0
        return src

    by_date = defaultdict(dict)
    for row in rows:
        t = canonical(row.get("symbolCode"))
        settled = str(row.get("settlementDate") or "")[:10]
        if not t or not settled:
            continue
        try:
            current = float(row.get("currentShortPositionQuantity"))
        except (TypeError, ValueError):
            continue
        by_date[settled][t] = {
            "current": current,
            "change_pct": row.get("changePercent"),
            "days_to_cover": row.get("daysToCoverQuantity"),
            # Both flags invalidate a change computed against the prior period.
            "revised": str(row.get("revisionFlag") or "").upper() in ("Y", "TRUE", "1"),
            "split": str(row.get("stockSplitFlag") or "").upper() in ("Y", "TRUE", "1"),
        }
    src.data = dict(by_date)
    src.status = "ok"
    src.note = f"{note}, {len(by_date)} settlement dates"
    src.seconds = time.time() - t0
    return src


def fetch_bars(span_start):
    """Alpaca daily bars, one paginated call for all symbols.

    SIP, not IEX. volume_spike.py uses the IEX feed and daily_recap.py and
    crossings.py use SIP; their volumes are NOT comparable, because IEX is one
    venue and SIP is consolidated. Mixing them in one table would silently
    compare a fraction of a stock's volume against all of another's. The digest
    picks one and states it — this one.
    """
    src = Source("bars")
    t0 = time.time()
    if not (ALPACA_KEY_ID and ALPACA_SECRET):
        src.status = "unavailable"
        src.note = "ALPACA_KEY_ID / ALPACA_SECRET_KEY not set"
        return src

    # Reach back past the span for the trailing baselines the rules need:
    # 252 sessions for a 52-week range, 20 for the volume baseline.
    start = (span_start - timedelta(days=430)).isoformat()
    end = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    out, token, pages = defaultdict(list), None, 0
    try:
        while pages < 12:
            params = {"symbols": ",".join(TICKERS), "timeframe": "1Day",
                      "start": start, "end": end, "limit": 10000,
                      "feed": ALPACA_FEED, "adjustment": "all"}
            if token:
                params["page_token"] = token
            r = requests.get(ALPACA_BARS, params=params, timeout=(10, 60),
                             headers={"APCA-API-KEY-ID": ALPACA_KEY_ID,
                                      "APCA-API-SECRET-KEY": ALPACA_SECRET})
            src.requests += 1
            r.raise_for_status()
            data = r.json()
            for sym, rows in (data.get("bars") or {}).items():
                out[sym].extend(rows)
            token = data.get("next_page_token")
            pages += 1
            if not token:
                break
    except (requests.RequestException, ValueError) as e:
        src.status, src.note = "failed", f"{type(e).__name__}"
        src.seconds = time.time() - t0
        return src

    series = {}
    for sym, rows in out.items():
        parsed = []
        for b in rows:
            try:
                parsed.append((datetime.fromisoformat(
                    b["t"].replace("Z", "+00:00")).date(),
                    float(b["c"]), float(b.get("v") or 0)))
            except (KeyError, ValueError, TypeError):
                continue
        series[sym] = sorted(parsed)
    src.data = series
    src.status = "ok"
    src.note = (f"{sum(len(v) for v in series.values())} bars, "
                f"{len(series)} tickers, feed={ALPACA_FEED}, {pages} page(s)")
    src.seconds = time.time() - t0
    return src


def fetch_filings():
    """EDGAR submissions, one request per CIK.

    ONE PAYLOAD SERVES THREE CONTRIBUTORS. It carries form, filing date,
    accession, primaryDocDescription, acceptanceDateTime and — the part that
    makes the filings rule possible at all — the 8-K ITEM CODES. Filings,
    comment letters and the material-event classification all come out of this
    single fetch. build_snapshot.py, press_monitor.py, earnings_calendar.py and
    comment_letters.py each fetch it separately today.
    """
    src = Source("filings")
    t0 = time.time()
    if not SEC_USER_AGENT:
        src.status = "unavailable"
        src.note = ("SEC_USER_AGENT not set. SEC's fair-access filter rejects "
                    "a GitHub noreply address and returns 403 from every "
                    "sec.gov endpoint — it wants a plain name and a contact "
                    "address.")
        return src

    headers = {"User-Agent": SEC_USER_AGENT,
               "Accept-Encoding": "gzip, deflate"}
    out, failed = {}, []
    for ticker, (cik, _name) in sorted(CIKS.items()):
        try:
            r = requests.get(SUBMISSIONS.format(cik=cik), headers=headers,
                             timeout=(10, 45))
            src.requests += 1
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            failed.append(f"{ticker}:{type(e).__name__}")
            continue
        recent = (data.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        rows = []
        for i, form in enumerate(forms):
            def at(key, default=""):
                seq = recent.get(key) or []
                return seq[i] if i < len(seq) else default
            acc = at("accessionNumber")
            filed = at("filingDate")
            if not acc or not filed:
                continue
            rows.append({
                "form": form,
                "filed": filed,
                "accepted": at("acceptanceDateTime"),
                "items": at("items"),
                "description": at("primaryDocDescription"),
                "accession": acc,
                "url": ARCHIVE.format(cik=int(cik),
                                      nodash=acc.replace("-", ""), acc=acc),
            })
        out[ticker] = rows
        time.sleep(0.15)          # stay well under SEC's 10 req/sec ceiling
    src.data = out
    # A partial fetch is reported as a partial fetch. comment_letters.py refuses
    # to post at all on any failure, on the grounds that a company missing from
    # a table reads as "no review" rather than "unknown"; here the same fact is
    # carried per company instead, because the record has room to say so.
    src.status = "ok" if not failed else "partial"
    src.note = (f"{len(out)} issuers, "
                f"{sum(len(v) for v in out.values())} filings"
                + (f"; FAILED {', '.join(failed)}" if failed else ""))
    src.seconds = time.time() - t0
    return src


def fetch_threshold(span_start, span_end):
    """Nasdaq Reg SHO threshold files, one per settlement day in the span.

    A non-settlement day 404s, which is expected and not an error. Nasdaq also
    serves a PLACEHOLDER PAGE with HTTP 200 for a date that has not published
    yet, so the header row is checked rather than the status code — the same
    soft-404 shape as Stooq's error body.
    """
    src = Source("threshold")
    t0 = time.time()
    by_day, flagged_totals = {}, {}
    day = span_start
    while day <= span_end:
        if day.weekday() < 5:
            url = NASDAQ_TH.format(stamp=day.strftime("%Y%m%d"))
            try:
                r = requests.get(url, headers=BROWSERISH, timeout=(10, 30))
                src.requests += 1
            except requests.RequestException:
                day += timedelta(days=1)
                continue
            if r.status_code == 200 and "Symbol" in r.text.split("\n", 1)[0]:
                hits, total = {}, 0
                for line in r.text.split("\n")[1:]:
                    parts = line.strip().split("|")
                    if len(parts) < 4 or parts[3].strip().upper() != "Y":
                        continue
                    total += 1
                    t = canonical(parts[0])
                    if t:
                        hits[t] = parts[1].strip()
                by_day[day.isoformat()] = hits
                # The file-wide flagged count is proof the parse worked. This
                # component's normal output is silence, so "nobody on our list"
                # is otherwise indistinguishable from "the layout changed and
                # nobody will ever be on our list again".
                flagged_totals[day.isoformat()] = total
            time.sleep(0.1)
        day += timedelta(days=1)
    src.data = {"by_day": by_day, "flagged_totals": flagged_totals}
    src.status = "ok" if by_day else "failed"
    ever = sorted({t for h in by_day.values() for t in h})
    src.note = (f"{len(by_day)} files, "
                f"median {int(statistics.median(flagged_totals.values()))} "
                f"securities flagged per file, "
                f"roster hits: {', '.join(ever) if ever else 'NONE'}"
                if flagged_totals else "no files parsed")
    src.seconds = time.time() - t0
    return src


def fetch_dilution():
    """Shares outstanding, via dilution.observations() so the concept probing
    and the currency check stay in the component that owns them."""
    src = Source("dilution")
    t0 = time.time()
    if not SEC_USER_AGENT:
        src.status, src.note = "unavailable", "SEC_USER_AGENT not set"
        return src
    out, failed = {}, []
    for ticker, (cik, _name) in sorted(CIKS.items()):
        try:
            series, concept = dilution.observations(cik)
            src.requests += 1
        except Exception as e:                      # noqa: BLE001
            failed.append(f"{ticker}:{type(e).__name__}")
            continue
        # observations() yields (as-of date, shares, form) oldest first. The
        # form is carried through because a count from a 10-K and one from an
        # S-3 cover page are not equally authoritative, and an article will
        # want to say which it was.
        out[ticker] = {
            "series": [(d.isoformat() if hasattr(d, "isoformat") else str(d),
                        int(v), f) for d, v, f in (series or [])],
            "concept": concept,
        }
        time.sleep(0.2)
    src.data = out
    src.status = "ok" if not failed else "partial"
    src.note = (f"{len(out)} issuers"
                + (f"; FAILED {', '.join(failed)}" if failed else ""))
    src.seconds = time.time() - t0
    return src


def fetch_ftd(periods):
    """SEC fails-to-deliver, newest `periods` half-month files.

    Uses ftd_monitor's own fetch_period(), which carries the three identity
    guards — refused CUSIPs, symbol-handover dates and the prefix learning
    rule. Those exist because SPCX was a SPAC ETF until 2026-04-07 and
    SpaceX from 2026-06-15, and in three of the four columns that is
    indistinguishable from a rename.
    """
    src = Source("ftd")
    t0 = time.time()
    if not SEC_USER_AGENT:
        src.status, src.note = "unavailable", "SEC_USER_AGENT not set"
        return src
    sess = ftd_monitor.session()
    try:
        index = ftd_monitor.fetch_index(sess)
        src.requests += 1
    except Exception as e:                          # noqa: BLE001
        src.status, src.note = "failed", f"index: {type(e).__name__}"
        src.seconds = time.time() - t0
        return src

    cusips = dict(CUSIP_PINS)
    out = {}
    for period, url in index[:periods]:
        try:
            rows, _learned, _skipped, _syms = ftd_monitor.fetch_period(
                sess, url, cusips)
            src.requests += 1
        except Exception as e:                      # noqa: BLE001
            out[period] = {"error": type(e).__name__}
            continue
        out[period] = ftd_monitor.summarise(rows)
        time.sleep(ftd_monitor.REQUEST_GAP)
    src.data = out
    src.status = "ok" if out else "failed"
    src.note = f"{len(out)} periods: {', '.join(sorted(out))}"
    src.seconds = time.time() - t0
    return src


# ------------------------------------------------------------- CONTRIBUTORS --

# Each contributor is one function plus one registry entry. Adding a component
# later means adding both and nothing else: the record gains a key, the
# convergence denominator grows by one, and no existing section changes.
#
# `derive(ctx, week, sessions)` returns {ticker: verdict}. Every verdict is
# built through mk(), which is what enforces the cadence rule.

# The floor and the baseline width are regsho_volume.py's, read from it rather
# than restated. The POINTS and DAYS below are the digest's own and deliberately
# differ from its NOTABLE_DELTA_POINTS — a weekly question needs a different
# rule from a daily one, and the measurement for that is in the docstring.
MIN_SHOVOL_VOLUME = regsho_volume.MIN_TOTAL_VOLUME
SHOVOL_BASELINE = regsho_volume.BASELINE_DAYS
SHOVOL_POINTS = 8.0             # calibrated below
SHOVOL_DAYS = 3                 # of five sessions
SHOVOL_MIN_SESSIONS = 3         # fewer than this and the week is not testable


def derive_short_volume(c, ctx, week, sessions):
    """Short volume as a share of reported volume, against each ticker's own
    trailing 20-session average.

    THE RULE IS CALIBRATED, NOT CHOSEN. Measured over four consecutive weeks of
    real FINRA data, 19 tickers:

        any single day |dev| >= 12 pts   12, 8, 9, 12 tickers   <- the shipped
                                                                  single-day rule
        same-sign |dev| >= 8 pts, 3 of 5   4, 4, 3, 3
        that AND |week median| >= 1 SD     3, 2, 2, 1           <- this rule

    The first row is the firehose quantified: over half the roster, every week,
    which is what a digest keyed on "did the component flag it" would inherit.

    BOTH CONDITIONS ARE REQUIRED. Points alone let a chronically noisy ticker
    qualify on ordinary noise; dispersion alone lets a very quiet one qualify on
    a move too small to mean anything. The dispersion half also does a second
    job: docs/rejected.md closed the BTC-correlation weekly table because the
    metric moved when its BASELINE moved, not when the companies did. Expressing
    the claim in the ticker's own dispersion is regime-aware by construction,
    and the baseline and its SD are carried into the record so the arithmetic
    can be disagreed with.
    """
    series = ctx["short_volume"].data or {}
    out = {}
    for t in TICKERS:
        s = series.get(t) or {}
        prior_days = sorted(d for d in s if d < sessions[0].isoformat())
        ratios = [s[d][0] / s[d][1] * 100 for d in prior_days[-SHOVOL_BASELINE:]
                  if s[d][1] >= MIN_SHOVOL_VOLUME]
        week_vals = []
        for d in sessions:
            key = d.isoformat()
            if key in s and s[key][1] >= MIN_SHOVOL_VOLUME:
                week_vals.append((key, s[key][0] / s[key][1] * 100))

        if len(ratios) < 10:
            out[t] = mk(c, NOT_TESTABLE,
                        basis=f"baseline {len(ratios)}/{SHOVOL_BASELINE} sessions",
                        detail={"baseline_sessions": len(ratios)})
            continue
        if len(week_vals) < SHOVOL_MIN_SESSIONS:
            # BGDE is the live case: 4/5, 5/5, 2/5 and 1/5 usable sessions over
            # the four measured weeks, having fallen below the volume floor.
            # Not absent, and the source did not fail — there were too few
            # usable sessions to apply the rule. It gets a count, not a label.
            out[t] = mk(c, NOT_TESTABLE,
                        basis=f"{len(week_vals)}/5 sessions above the "
                              f"{MIN_SHOVOL_VOLUME:,}-share volume floor",
                        detail={"usable_sessions": len(week_vals)})
            continue

        avg = sum(ratios) / len(ratios)
        sd = statistics.pstdev(ratios)
        devs = [(d, v - avg) for d, v in week_vals]
        med = statistics.median(x for _, x in devs)
        up = sum(1 for _, x in devs if x >= SHOVOL_POINTS)
        down = sum(1 for _, x in devs if x <= -SHOVOL_POINTS)
        hits, direction = (up, "up") if up >= down else (down, "down")
        persistent = hits >= SHOVOL_DAYS
        dispersed = sd > 0 and abs(med) >= sd

        detail = {
            "week_median_dev": round(med, 1),
            "baseline_mean": round(avg, 1),
            "baseline_sd": round(sd, 1),
            "baseline_sessions": len(ratios),
            "usable_sessions": len(week_vals),
            "sd_multiple": round(abs(med) / sd, 2) if sd else None,
            "daily_dev": [(d, round(x, 1)) for d, x in devs],
        }
        if persistent and dispersed:
            out[t] = mk(c, NOTABLE,
                        figure=f"{med:+.0f}pts vs its own {len(ratios)}-session "
                               f"average of {avg:.0f}%",
                        basis=f"{hits} of {len(devs)} sessions {direction} by "
                              f">={SHOVOL_POINTS:.0f}pts; week median "
                              f"{abs(med) / sd:.1f}x baseline SD",
                        sources=[f"FINRA regShoDaily {sessions[0]}..{sessions[-1]}"],
                        persistence={"hits": hits, "of": len(devs),
                                     "direction": direction},
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, figure=f"{med:+.0f}pts", detail=detail)
    return out


PRICE_SD_MULTIPLE = 2.0     # week return against its own trailing dispersion
PRICE_BASELINE_WEEKS = 12


def derive_price(c, ctx, week, sessions):
    """Week return, against this ticker's own trailing weekly-return dispersion.

    Never a bare absolute. A 15% week is unremarkable for half this roster and
    unprecedented for the other half, and a reader given a bare number supplies
    a baseline from intuition.
    """
    bars = (ctx["bars"].data or {})
    out = {}
    for t in TICKERS:
        rows = bars.get(t) or []
        if not rows:
            out[t] = mk(c, NOT_TESTABLE, basis="no bars")
            continue
        inside = [(d, close) for d, close, _ in rows
                  if sessions[0] <= d <= sessions[-1]]
        before = [(d, close) for d, close, _ in rows if d < sessions[0]]
        if not inside or not before:
            out[t] = mk(c, NOT_TESTABLE,
                        basis=f"{len(inside)} sessions in week, "
                              f"{len(before)} before it")
            continue
        open_px, close_px = before[-1][1], inside[-1][1]
        ret = (close_px - open_px) / open_px * 100 if open_px else 0.0

        # Trailing weekly returns, built from the same bar series.
        weekly, cursor = [], before
        anchor = sessions[0]
        for i in range(1, PRICE_BASELINE_WEEKS + 1):
            w_start = anchor - timedelta(days=7 * i)
            w_end = w_start + timedelta(days=4)
            seg = [px for d, px in cursor if w_start <= d <= w_end]
            prior = [px for d, px in cursor if d < w_start]
            if seg and prior:
                weekly.append((seg[-1] - prior[-1]) / prior[-1] * 100)
        if len(weekly) < 6:
            out[t] = mk(c, NOT_TESTABLE,
                        figure=f"{ret:+.1f}%",
                        basis=f"{len(weekly)}/{PRICE_BASELINE_WEEKS} trailing "
                              f"weeks — too few for a dispersion baseline",
                        detail={"week_return_pct": round(ret, 1),
                                "baseline_weeks": len(weekly)})
            continue
        sd = statistics.pstdev(weekly)
        detail = {"week_return_pct": round(ret, 1),
                  "baseline_sd_pct": round(sd, 1),
                  "baseline_weeks": len(weekly),
                  "sd_multiple": round(abs(ret) / sd, 2) if sd else None,
                  "sessions_in_week": len(inside)}
        if sd > 0 and abs(ret) >= PRICE_SD_MULTIPLE * sd:
            out[t] = mk(c, NOTABLE,
                        figure=f"{ret:+.1f}%",
                        basis=f"{abs(ret) / sd:.1f}x its own {len(weekly)}-week "
                              f"return SD of {sd:.1f}%",
                        sources=[f"Alpaca {ALPACA_FEED} daily bars"],
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, figure=f"{ret:+.1f}%", detail=detail)
    return out


VOLUME_MULTIPLE = 2.0
VOLUME_DAYS = 3
VOLUME_BASELINE = 30


def derive_volume(c, ctx, week, sessions):
    """Daily volume against a 30-session trailing MEDIAN, persistence-shaped.

    A median rather than a mean, because one 10x session inside the baseline
    window raises a mean enough to hide the next one.

    Deliberately NOT a reconstruction of volume_spike.py. That component
    compares an hour's volume against the same hour on prior sessions, on the
    IEX feed, so it can escalate a same-day alert through tiers without
    spamming. The weekly fact is available from daily bars, and the intraday
    tier structure answers a question the digest is not asking.
    """
    bars = ctx["bars"].data or {}
    out = {}
    for t in TICKERS:
        rows = bars.get(t) or []
        prior = [v for d, _, v in rows if d < sessions[0]][-VOLUME_BASELINE:]
        inside = [(d, v) for d, _, v in rows
                  if sessions[0] <= d <= sessions[-1]]
        if len(prior) < 10 or not inside:
            out[t] = mk(c, NOT_TESTABLE,
                        basis=f"baseline {len(prior)}/{VOLUME_BASELINE} sessions")
            continue
        base = statistics.median(prior)
        if base <= 0:
            out[t] = mk(c, NOT_TESTABLE, basis="zero trailing volume")
            continue
        mult = [(d.isoformat(), v / base) for d, v in inside]
        hits = sum(1 for _, m in mult if m >= VOLUME_MULTIPLE)
        peak = max(m for _, m in mult)
        # `baseline_volume_median`, not `baseline_median`. ftd_monitor's own
        # baseline is a median of half-month fail PEAKS and lands in a detail
        # dict under the second name; a renderer keying on the shorter one
        # matched both and then read a field only one of them has. Detail keys
        # are a shared namespace across contributors even though the dicts are
        # not, so they carry the quantity in the name.
        detail = {"baseline_volume_median": int(base),
                  "baseline_sessions": len(prior),
                  "peak_multiple": round(peak, 1),
                  "daily_multiple": [(d, round(m, 1)) for d, m in mult]}
        if hits >= VOLUME_DAYS:
            out[t] = mk(c, NOTABLE,
                        figure=f"{peak:.1f}x peak",
                        basis=f"{hits} of {len(mult)} sessions at "
                              f">={VOLUME_MULTIPLE:.0f}x its own "
                              f"{len(prior)}-session median volume",
                        sources=[f"Alpaca {ALPACA_FEED} daily bars"],
                        persistence={"hits": hits, "of": len(mult),
                                     "direction": "up"},
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, figure=f"{peak:.1f}x peak", detail=detail)
    return out


CROSSINGS_WINDOW = 252      # crossings.py's WINDOW
CROSSINGS_MIN_BARS = 60     # crossings.py's MIN_BARS


def derive_crossings(c, ctx, week, sessions):
    """A 52-week high or low touched during the week.

    Skips below MIN_BARS rather than caveating, which is crossings.py's own
    judgement and a real difference in meaning: a crossing measured against 37
    sessions is not a 52-week crossing. daily_recap.py keeps the row and marks
    one column, because close, change and volume are unaffected there.
    """
    bars = ctx["bars"].data or {}
    out = {}
    for t in TICKERS:
        rows = bars.get(t) or []
        before = [(d, px) for d, px, _ in rows if d < sessions[0]]
        inside = [(d, px) for d, px, _ in rows
                  if sessions[0] <= d <= sessions[-1]]
        window = [px for _, px in before[-CROSSINGS_WINDOW:]]
        if len(window) < CROSSINGS_MIN_BARS or not inside:
            out[t] = mk(c, NOT_TESTABLE,
                        basis=f"{len(window)}/{CROSSINGS_MIN_BARS} bars "
                              f"minimum for a 52-week window")
            continue
        hi, lo = max(window), min(window)
        highs = [(d.isoformat(), px) for d, px in inside if px > hi]
        lows = [(d.isoformat(), px) for d, px in inside if px < lo]
        detail = {"prior_high": round(hi, 4), "prior_low": round(lo, 4),
                  "window_bars": len(window),
                  "new_highs": highs, "new_lows": lows,
                  "short_window": len(window) < CROSSINGS_WINDOW}
        if highs or lows:
            kind = "52-week high" if highs else "52-week low"
            hit = (highs or lows)[-1]
            out[t] = mk(c, NOTABLE,
                        figure=f"{kind} {hit[1]:.2f} on {hit[0]}",
                        basis=f"against a {len(window)}-bar window"
                              + ("" if len(window) >= CROSSINGS_WINDOW
                                 else " — SHORT of 252, so this is not yet a "
                                      "full 52-week range"),
                        sources=[f"Alpaca {ALPACA_FEED} daily bars"],
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, detail=detail)
    return out


# Form families that make a week material, separate from the 8-K item route.
# Prefix matched, EDGAR-style. BOTH 13D spellings: "SCHEDULE 13D" does not
# start with "SC 13D" — the fourth character is H, not a space — and the legacy
# prefix alone silently missed 117 filings across eleven issuers.
FILING_CLASSES = {
    "capital": ["424", "S-1", "S-3"],
    "control": ["SC 13D", "SCHEDULE 13D"],
    "late": ["NT "],
    # Recorded and measured, but NOT part of the headline rule — see below.
    "periodic": ["10-K", "10-Q", "20-F", "40-F"],
    "passive": ["SC 13G", "SCHEDULE 13G"],
}
# The headline rule. `periodic` is excluded because a quarterly report is
# scheduled, expected and would fire for most of the roster inside a two-week
# earnings window — it belongs in the summary, not in a filter. `passive` is
# excluded because 13G is index funds doing their February housekeeping.
MATERIAL_CLASSES = ["capital", "control", "late"]


def form_in(form, prefixes):
    return any(form.startswith(p) for p in prefixes)


def derive_filings(c, ctx, week, sessions):
    """Material filings in the week, by form class or by 8-K item code.

    PRESENCE IS USELESS AND THAT IS MEASURED: 10 of the 14 issuers then in
    snapshot.json had a filing dated inside the week of 2026-07-30, and all ten
    of those had an 8-K. A convergence input that fires for 71% of the roster
    is not a filter.

    So the rule keys on the ITEM CODES, which arrive free in the same payload.
    ALWAYS_POST_ITEMS is press_monitor.py's, imported rather than restated: a
    restatement (4.02) is the filing least likely to carry a press release and
    was dropped ten times out of ten before that set existed.

    Every sub-rule is recorded separately in `detail` whether or not it fires,
    so the backfill can report which one drives the rate rather than the
    headline hiding it.
    """
    filings = ctx["filings"].data or {}
    lo, hi = sessions[0].isoformat(), sessions[-1].isoformat()
    out = {}
    for t in TICKERS:
        rows = filings.get(t)
        if rows is None:
            out[t] = mk(c, SOURCE_FAILED,
                        basis="EDGAR submissions fetch did not return")
            continue
        week_rows = [r for r in rows if lo <= r["filed"] <= hi]
        classes = defaultdict(list)
        always, press = [], []
        for r in week_rows:
            for name, prefixes in FILING_CLASSES.items():
                if form_in(r["form"], prefixes):
                    classes[name].append(r)
            codes = {x.strip() for x in (r["items"] or "").split(",") if x.strip()}
            if codes & ALWAYS_POST_ITEMS:
                always.append((r, sorted(codes & ALWAYS_POST_ITEMS)))
            if codes & PRESS_RELEASE_ITEMS:
                press.append(r)

        detail = {
            "filings_in_week": len(week_rows),
            "by_class": {k: len(v) for k, v in sorted(classes.items())},
            "always_post_items": [
                {"accession": r["accession"], "form": r["form"],
                 "filed": r["filed"], "items": codes,
                 "labels": [ITEM_LABELS.get(x, x) for x in codes],
                 "url": r["url"]}
                for r, codes in always],
            "press_release_items": len(press),
            "forms": sorted({r["form"] for r in week_rows}),
        }
        material = [r for name in MATERIAL_CLASSES for r in classes.get(name, [])]
        if always or material:
            reasons = []
            if always:
                reasons.append(", ".join(
                    ITEM_LABELS.get(x, x) for _, codes in always for x in codes))
            for name in MATERIAL_CLASSES:
                if classes.get(name):
                    reasons.append(f"{len(classes[name])} {name}")
            out[t] = mk(c, NOTABLE,
                        figure="; ".join(reasons),
                        basis=f"{len(week_rows)} filings in the week",
                        sources=[f"{r['form']} {r['accession']} {r['url']}"
                                 for r in ([x for x, _ in always] + material)],
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE,
                        figure=f"{len(week_rows)} filings",
                        detail=detail)
    return out


LETTER_FORMS = {"UPLOAD": "SEC staff letter", "CORRESP": "company response"}


def derive_letters(c, ctx, week, sessions):
    """SEC review correspondence released during the week.

    THE DATE IS A RELEASE DATE, NOT AN EVENT DATE. SEC publishes correspondence
    at least 20 business days after completing a review, so what this reports
    for "this week" concerns a review that closed about a month earlier. The
    delay is disclosure policy rather than publication lag, and the record says
    so per verdict rather than once in a footer.
    """
    filings = ctx["filings"].data or {}
    lo, hi = sessions[0].isoformat(), sessions[-1].isoformat()
    out = {}
    for t in TICKERS:
        rows = filings.get(t)
        if rows is None:
            out[t] = mk(c, SOURCE_FAILED, basis="EDGAR submissions fetch failed")
            continue
        hits = [r for r in rows
                if r["form"] in LETTER_FORMS and lo <= r["filed"] <= hi]
        if hits:
            out[t] = mk(c, NOTABLE,
                        figure=", ".join(f"{LETTER_FORMS[r['form']]} {r['filed']}"
                                         for r in hits),
                        basis="released this week; the review it concerns "
                              "closed at least 20 business days earlier",
                        sources=[r["url"] for r in hits],
                        detail={"count": len(hits),
                                "accessions": [r["accession"] for r in hits]})
        else:
            out[t] = mk(c, ROUTINE, detail={"count": 0})
    return out


def derive_threshold(c, ctx, week, sessions):
    """Reg SHO threshold list — a security with 13 consecutive settlement days
    of significant fails.

    Natively a persistence measure, and the only contributor whose source
    already counts consecutive days for you.
    """
    data = ctx["threshold"].data or {}
    by_day = data.get("by_day") or {}
    days = [d.isoformat() for d in sessions if d.isoformat() in by_day]
    out = {}
    if not days:
        for t in TICKERS:
            out[t] = mk(c, SOURCE_FAILED,
                        basis="no threshold file parsed for this week")
        return out
    for t in TICKERS:
        listed = [d for d in days if t in by_day[d]]
        detail = {"files_read": len(days), "days_listed": len(listed),
                  "dates": listed}
        if listed:
            out[t] = mk(c, NOTABLE,
                        figure=f"on the threshold list {len(listed)} of "
                               f"{len(days)} settlement days",
                        basis="13 consecutive settlement days of significant "
                              "fails is what puts a security here",
                        sources=[f"nasdaqth{d.replace('-', '')}.txt"
                                 for d in listed],
                        persistence={"hits": len(listed), "of": len(days),
                                     "direction": "listed"},
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, detail=detail)
    return out


def derive_dilution(c, ctx, week, sessions):
    """A new share count observed in the week, stepping by more than
    dilution.NOTABLE_STEP_PCT.

    XBRL share counts are NOT split-adjusted, so a decrease steeper than
    dilution.SPLIT_DROP_PCT is treated as a corporate action rather than a
    buyback — ANY, BGDE, BKKT, SLNH and VIP have all reverse-split, and none of
    these companies has the cash for a buyback of that size.
    """
    data = ctx["dilution"].data or {}
    lo, hi = sessions[0].isoformat(), sessions[-1].isoformat()
    out = {}
    for t in TICKERS:
        entry = data.get(t)
        if entry is None:
            out[t] = mk(c, SOURCE_FAILED, basis="XBRL fetch did not return")
            continue
        series = sorted(entry.get("series") or [])
        inside = [r for r in series if lo <= r[0] <= hi]
        before = [r for r in series if r[0] < lo]
        if not inside:
            out[t] = mk(c, ROUTINE,
                        detail={"observations_in_week": 0,
                                "concept": entry.get("concept"),
                                "latest_before": before[-1] if before else None})
            continue
        newest = inside[-1]
        if not before:
            out[t] = mk(c, NOT_TESTABLE,
                        figure=f"{newest[1]:,.0f} shares",
                        basis="first observation — no prior count to step from",
                        detail={"observations_in_week": len(inside)})
            continue
        prev = before[-1]
        step = (newest[1] - prev[1]) / prev[1] * 100 if prev[1] else 0.0
        detail = {"observations_in_week": len(inside),
                  "from": prev, "to": newest, "step_pct": round(step, 1),
                  "concept": entry.get("concept")}
        if step <= -dilution.SPLIT_DROP_PCT:
            out[t] = mk(c, NOTABLE,
                        figure=f"{step:+.0f}% share count",
                        basis="steeper than a plausible buyback — treated as a "
                              "reverse split, not a reduction",
                        detail=detail)
        elif abs(step) >= dilution.NOTABLE_STEP_PCT:
            out[t] = mk(c, NOTABLE,
                        figure=f"{step:+.1f}% to {newest[1]:,.0f} shares",
                        basis=f"reported {newest[0]}, against {prev[1]:,.0f} "
                              f"on {prev[0]}",
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, figure=f"{step:+.1f}%", detail=detail)
    return out


def period_published_in(period, sessions):
    """Did a half-month fails period become available during this week?

    First half of a month publishes at month end; second half publishes around
    the 15th of the following month. Worst case a settlement date is visible
    about six weeks later.
    """
    year, month, half = int(period[:4]), int(period[4:6]), period[6]
    if half == "a":
        pub = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    else:
        pub = date(year + (month == 12), month % 12 + 1, 15)
    return sessions[0] <= pub <= sessions[-1]


def derive_ftd(c, ctx, week, sessions):
    """Fails to deliver, keyed by PERIOD rather than by week.

    THE CADENCE FIELD IS DOING REAL WORK HERE. A half-month file holds about ten
    settlement dates, so "failed on eight of ten" is a persistence statement —
    about a period that ended up to six weeks before this week began. mk() will
    raise if this function ever tries to attach a persistence claim, and that is
    the point: the temptation is real and nothing downstream could catch it.
    """
    data = ctx["ftd"].data or {}
    fresh = [p for p in sorted(data) if period_published_in(p, sessions)
             and "error" not in (data[p] or {})]
    out = {}
    if not fresh:
        for t in TICKERS:
            out[t] = mk(c, ROUTINE,
                        basis="no new half-month period published this week",
                        detail={"periods_published": []})
        return out
    period = fresh[-1]
    current = data[period] or {}
    prior_periods = [p for p in sorted(data) if p < period
                     and "error" not in (data[p] or {})]
    for t in TICKERS:
        row = current.get(t)
        prior_peaks = [(data[p] or {}).get(t, {}).get("peak")
                       for p in prior_periods]
        prior_peaks = [x for x in prior_peaks if x is not None]
        detail = {"period": period, "peak": (row or {}).get("peak"),
                  "days": (row or {}).get("days"),
                  "baseline_periods": len(prior_peaks)}
        if row is None:
            # Absence in this file is a ZERO net balance on every settlement
            # date in the period, not a gap. The SEC lists only non-zero fails.
            out[t] = mk(c, ROUTINE, figure="0 shares",
                        basis=f"absent from period {ftd_monitor.pretty(period)} "
                              f"— zero fails on every settlement date",
                        detail=detail)
            continue
        if len(prior_peaks) < ftd_monitor.MIN_FLAG_PERIODS:
            out[t] = mk(c, NOT_TESTABLE,
                        figure=f"{row['peak']:,.0f} peak",
                        basis=f"{len(prior_peaks)}/"
                              f"{ftd_monitor.MIN_FLAG_PERIODS} prior periods "
                              f"— median too narrow to flag against",
                        detail=detail)
            continue
        median = statistics.median(prior_peaks)
        detail["baseline_median"] = median
        if (median > 0 and row["peak"] >= ftd_monitor.FLAG_MULTIPLE * median
                and row["peak"] >= ftd_monitor.MIN_FLAG_SHARES):
            out[t] = mk(c, NOTABLE,
                        figure=f"{row['peak']:,.0f} peak fails",
                        basis=f"{row['peak'] / median:.1f}x its own "
                              f"{len(prior_peaks)}-period median, in period "
                              f"{ftd_monitor.pretty(period)} — settlement dates "
                              f"up to six weeks before this week",
                        sources=[f"SEC CNS fails, period {period}"],
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, figure=f"{row['peak']:,.0f} peak",
                        detail=detail)
    return out


# FINRA publishes a short-interest settlement about nine business days later —
# the 2026-07-15 settlement published on 2026-07-27, twelve calendar days.
#
# THIS ASSIGNS EACH SETTLEMENT TO EXACTLY ONE WEEK, and that is the whole point.
# The first version tested whether an 8-to-16-day publication WINDOW overlapped
# the week, which is nine days wide and therefore overlaps two consecutive
# weeks — so one settlement was reported as fresh twice and counted twice
# toward convergence. It showed up as short interest firing 7.3 times a week
# from a source that publishes twice a month, which is the kind of number that
# would have set the threshold wrongly and looked like a finding while doing it.
SHORT_INTEREST_PUBLICATION_LAG = 12


def publication_week(settlement):
    """The Monday of the ISO week a settlement date becomes visible in."""
    try:
        pub = date.fromisoformat(settlement) + timedelta(
            days=SHORT_INTEREST_PUBLICATION_LAG)
    except ValueError:
        return None
    return pub - timedelta(days=pub.weekday())


def derive_short_interest(c, ctx, week, sessions):
    """FINRA consolidated short interest, when a settlement publishes this week.

    A position, not a flow, and about two weeks stale by the time it publishes:
    the 2026-07-15 settlement published on 2026-07-27. It can appear in a
    summary. It can never carry a persistence claim about the week.
    """
    data = ctx["short_interest"].data or {}
    fresh = [s for s in sorted(data) if publication_week(s) == week]
    out = {}
    if not fresh:
        for t in TICKERS:
            out[t] = mk(c, ROUTINE,
                        basis="no settlement published this week",
                        detail={"settlements_published": []})
        return out
    settled = fresh[-1]
    rows = data[settled]
    prior = [d for d in sorted(data) if d < settled]
    for t in TICKERS:
        row = rows.get(t)
        if row is None:
            out[t] = mk(c, ROUTINE,
                        basis=f"not reported for settlement {settled}",
                        detail={"settlement": settled})
            continue
        prev = None
        for d in reversed(prior):
            if t in data[d]:
                prev = (d, data[d][t]["current"])
                break
        change = ((row["current"] - prev[1]) / prev[1] * 100
                  if prev and prev[1] else None)
        detail = {"settlement": settled, "current": row["current"],
                  "previous": prev, "change_pct": round(change, 1) if change
                  is not None else None, "revised": row["revised"],
                  "split": row["split"]}
        if row["revised"] or row["split"]:
            # A change computed across a revision or a split compares two
            # different things.
            out[t] = mk(c, NOT_TESTABLE,
                        figure=f"{row['current']:,.0f} shares short",
                        basis="FINRA flagged this row as revised or split-"
                              "affected, so a change against the prior period "
                              "is not a like-for-like comparison",
                        detail=detail)
        elif (change is not None
                and abs(change) >= short_interest.NOTABLE_CHANGE_PCT):
            out[t] = mk(c, NOTABLE,
                        figure=f"{change:+.0f}% to {row['current']:,.0f} shares",
                        basis=f"settlement {settled}, published ~9 business "
                              f"days later — a position about two weeks stale",
                        sources=[f"FINRA consolidatedShortInterest {settled}"],
                        detail=detail)
        else:
            out[t] = mk(c, ROUTINE, detail=detail)
    return out


# THE REGISTRY. One line per contributor. Adding a component means adding its
# derive function and one entry here; every existing section is untouched, the
# record gains a key, and the convergence denominator grows by one.
#
# btc_context.py and grid_context.py are deliberately absent. They have no
# per-company dimension at all — bitcoin network data and ERCOT demand are not
# facts about a company — so they cannot contribute to a per-company
# convergence count. They belong in the file's market section when a renderer
# exists. THIS IS THE DENOMINATOR CORRECTION: thirteen components, but only
# these contribute per-company verdicts, and two of these publish nothing in a
# typical week.
#
# `publishes` answers "could this contributor have said anything about THIS
# week", which is a different question from "did its fetch work". A source that
# publishes twice a month is silent in most weeks not because nothing happened
# but because nothing was published, and counting it in the denominator would
# make convergence look rarer than it is. Only the two gated contributors
# supply one; everything else is always in the denominator.
def ftd_publishes(ctx, sessions):
    data = ctx["ftd"].data or {}
    return any(period_published_in(p, sessions) for p in data
               if "error" not in (data[p] or {}))


def short_interest_publishes(ctx, sessions):
    return any(publication_week(s) == sessions[0]
               for s in (ctx["short_interest"].data or {}))


CONTRIBUTORS = [
    {"key": "short_volume", "cadence": DAILY, "needs": ["short_volume"],
     "latency": "T+1", "derive": derive_short_volume},
    {"key": "price", "cadence": DAILY, "needs": ["bars"],
     "latency": "same day", "derive": derive_price},
    {"key": "volume", "cadence": DAILY, "needs": ["bars"],
     "latency": "same day", "derive": derive_volume},
    {"key": "crossings", "cadence": DAILY, "needs": ["bars"],
     "latency": "same day", "derive": derive_crossings},
    {"key": "threshold_list", "cadence": DAILY, "needs": ["threshold"],
     "latency": "T+1", "derive": derive_threshold},
    {"key": "filings", "cadence": EVENT, "needs": ["filings"],
     "latency": "minutes to hours", "derive": derive_filings},
    {"key": "comment_letters", "cadence": EVENT, "needs": ["filings"],
     "latency": "released >=20 business days after the review closed",
     "derive": derive_letters},
    {"key": "dilution", "cadence": PER_FILING, "needs": ["dilution"],
     "latency": "as filed; cover-page counts lag the balance sheet",
     "derive": derive_dilution},
    {"key": "short_interest", "cadence": TWICE_MONTHLY, "needs": ["short_interest"],
     "latency": "~2 weeks", "derive": derive_short_interest,
     "publishes": short_interest_publishes},
    {"key": "ftd", "cadence": HALF_MONTHLY, "needs": ["ftd"],
     "latency": "2 to 6 weeks", "derive": derive_ftd,
     "publishes": ftd_publishes},
]


# ------------------------------------------------------------------ RECORD --

SCHEMA = 1

# CONTRIBUTORS ARE NOT ALL INDEPENDENT, AND COUNTING THEM AS THOUGH THEY WERE
# INFLATES CONVERGENCE FOR EXACTLY THE WRONG COMPANY.
#
# price, volume and crossings are three readings of ONE Alpaca bar series. A
# stock that jumps 20% on heavy volume through its 52-week high scores three,
# and it has told you one thing. Measured over the 10-week backfill, the
# co-occurrence against what independence would predict:
#
#     price + volume         5.3x        <- one fact
#     crossings + volume     4.0x        <- one fact
#     short_interest + threshold_list  3.3x
#     short_interest + volume          1.8x
#     short_volume + short_interest    1.4x   <- near-independent, kept apart
#     crossings + short_interest       1.0x
#
# Collapsing the bar-series three into one family moved >=3 from 8 ticker-weeks
# to 5, and dropped VIP's week of four to two — a week whose four components
# were crossings, price, volume and filings, three of them the same event.
#
# The short-side measures are NOT collapsed. Short volume is a flow, short
# interest is a position, fails are a settlement failure and the threshold list
# is a regulatory consequence; they run at 1.0-1.8x, which is what genuinely
# different measurements of a related phenomenon look like. Collapsing those
# would throw away the convergence this digest exists to find.
#
# The filter's whole purpose argues the same way: a big price move on heavy
# volume is the thing a reader CANNOT miss. It should not be what pushes a
# company over the line.
SOURCE_FAMILY = {
    "price": "market",
    "volume": "market",
    "crossings": "market",
}

# MEASURED, NOT CHOSEN. Backfill of 10 complete ISO weeks, 2026-W22 to 2026-W31,
# 19 tickers, 190 ticker-weeks, counting distinct source families:
#
#     families:      0     1     2     3
#     ticker-weeks: 93    60    32     5
#     share:       49%   32%   17%    3%
#
# The decay ratio runs 0.65, 0.53, then 0.16 — a real break between 2 and 3,
# unlike the heartbeat in docs/rejected.md whose healthy and broken populations
# overlapped and admitted no threshold at all.
#
# At >=2 the section names 3.7 companies a week, a fifth of the roster, which is
# a second firehose rather than a filter. At >=3 it names 0.5 a week and is
# EMPTY IN SIX OF THE TEN WEEKS. That is the intended behaviour and not a
# failure: a renderer must print "nothing converged this week" rather than
# dropping the section, because absence is a measurement.
CONVERGENCE_THRESHOLD = 3
CONVERGENCE_BASIS = ("10 complete ISO weeks, 2026-W22..2026-W31, 190 "
                     "ticker-weeks; >=3 families = 5 ticker-weeks, 0.5/wk")

# The tier below the threshold. Named in the output but never promoted into the
# convergence section: at >=2 it runs 3.7 companies a week, a fifth of the
# roster, which is the firehose the threshold exists to prevent.
SECONDARY_TIER = 2

# CONTRIBUTORS WHOSE RULE HAS NEVER FIRED AGAINST A REAL OCCURRENCE.
#
# An empty section from one of these is indistinguishable from a working one,
# which is the same standing trap as a FORM_TYPES entry that has never matched:
# a form matching nothing looks exactly like one whose filings never occur.
# Both renderers carry this, because a reader of the file a year from now has
# no other way to know.
#
# A key is REMOVED FROM HERE the first time the contributor fires. Do not remove
# one because the rule looks right.
UNEXERCISED = {
    "dilution": (
        "0 of 190 ticker-weeks over 2026-W22..2026-W31. Not a wrong rule: only "
        "3 ticker-weeks had a new XBRL observation at all, and the largest step "
        "was HUT at +9.50% against the 10.0% threshold — half a point under the "
        "line."),
}


def demonstrate_cadence_guard():
    """Run the cadence guard with and without itself, and print both.

    THIS IS THE GUARD'S JUSTIFICATION AND IT RUNS ON EVERY INVOCATION, because
    a test that has never failed proves nothing. It is cheap, it needs no
    network, and it is the only place the failure it prevents is visible.

    Restores PERSISTENCE_CADENCES before returning; the widened set must not
    leak into the run.
    """
    reg = {c["key"]: c for c in CONTRIBUTORS}
    print("Cadence guard — persistence eligibility derived from cadence, "
          "not remembered:")
    for key in sorted(reg):
        c = reg[key]
        try:
            mk(c, NOTABLE, persistence={"hits": 4, "of": 5, "direction": "up"})
            verdict = "accepts a persistence claim"
        except DigestError:
            verdict = "REFUSES"
        print(f"    {key:<16} {c['cadence']:<14} {verdict}")

    original = set(PERSISTENCE_CADENCES)
    try:
        PERSISTENCE_CADENCES.update({EVENT, PER_FILING, TWICE_MONTHLY,
                                     HALF_MONTHLY})
        leaked = mk(reg["ftd"], NOTABLE,
                    figure="412,000 peak fails",
                    basis="failed on 8 of 10 settlement dates",
                    persistence={"hits": 8, "of": 10, "direction": "up"})
    finally:
        PERSISTENCE_CADENCES.clear()
        PERSISTENCE_CADENCES.update(original)
    print(f"  With the guard removed, ftd accepts {leaked['persistence']} — "
          f"which reads as a claim about this week and is about a period that "
          f"ended up to six weeks earlier. Nothing downstream could catch it.")
    print()


def build_week(ctx, monday):
    """One week's verdict record. No rendering, no thresholds applied to the
    convergence count — the count is recorded and the threshold is set later,
    from the backfill distribution."""
    sessions = week_sessions(monday)
    record = {
        "schema": SCHEMA,
        "week": iso_week_key(monday),
        "monday": monday.isoformat(),
        "friday": sessions[-1].isoformat(),
        "roster": list(TICKERS),
        "contributors": {},
        "sources": {k: s.summary() for k, s in ctx.items()},
        "verdicts": {},
        "convergence": {},
    }
    counted = []
    for c in CONTRIBUTORS:
        fetched = all(ctx[n].ok() or ctx[n].status == "partial"
                      for n in c["needs"])
        # Two separate reasons a contributor may not be in the denominator, and
        # they are recorded separately because they mean opposite things. A
        # source that FAILED leaves a hole the reader must be told about; a
        # source that simply did not publish this week is behaving normally.
        published = fetched and c.get("publishes", lambda *_: True)(ctx, sessions)
        record["contributors"][c["key"]] = {
            "cadence": c["cadence"],
            "latency": c["latency"],
            "may_claim_persistence": c["cadence"] in PERSISTENCE_CADENCES,
            "fetched": fetched,
            "published_this_week": published,
            "counted_in_denominator": published,
            "sources": c["needs"],
        }
        if not fetched:
            continue
        if published:
            counted.append(c["key"])
        # Derive even when it did not publish: "no new period this week" is a
        # verdict worth recording, and it is what stops a renderer inferring
        # silence from an absent key.
        verdicts = c["derive"](c, ctx, monday, sessions)
        for ticker, v in verdicts.items():
            record["verdicts"].setdefault(ticker, {})[c["key"]] = v

    # The convergence count, recorded WITHOUT a threshold applied. The
    # threshold is set from the backfill distribution, not chosen here.
    for t in TICKERS:
        vs = record["verdicts"].get(t, {})
        hits = sorted(k for k, v in vs.items() if v["level"] == NOTABLE)
        families = sorted({SOURCE_FAMILY.get(k, k) for k in hits})
        record["convergence"][t] = {
            # `count` is the family count and is the one to threshold on.
            # `component_count` is kept beside it because the two disagreeing
            # is itself informative — it means the week's evidence came from
            # one source read several ways.
            "count": len(families),
            "families": families,
            "component_count": len(hits),
            "components": hits,
            "converged": len(families) >= CONVERGENCE_THRESHOLD,
            "not_testable": sorted(k for k, v in vs.items()
                                   if v["level"] == NOT_TESTABLE),
            "source_failed": sorted(k for k, v in vs.items()
                                    if v["level"] == SOURCE_FAILED),
        }
    # THE DENOMINATOR CORRECTION. Thirteen components exist; two have no
    # per-company dimension and are not registered here at all; and of those
    # that are, the fortnightly pair publishes nothing in most weeks. A
    # threshold of "three of thirteen" is really three of about seven, and one
    # set against the wrong denominator is wrong in a way that looks
    # conservative.
    record["denominator"] = {
        "components_in_repo": 13,
        "registered": len(CONTRIBUTORS),
        "families": len({SOURCE_FAMILY.get(k, k) for k in counted}),
        "convergence_threshold": CONVERGENCE_THRESHOLD,
        "threshold_basis": CONVERGENCE_BASIS,
        "fetched": sum(1 for v in record["contributors"].values()
                       if v["fetched"]),
        "counted": len(counted),
        "counted_keys": sorted(counted),
        "not_published": sorted(k for k, v in record["contributors"].items()
                                if v["fetched"] and not v["published_this_week"]),
        "not_fetched": sorted(k for k, v in record["contributors"].items()
                              if not v["fetched"]),
    }
    return record


def monday_of(week_key):
    """'2026-W31' -> the Monday of that ISO week."""
    year, week = week_key.upper().split("-W")
    return date.fromisocalendar(int(year), int(week), 1)


def derive_one(week_key, prior_weeks=1):
    """One week's record, plus the records of the weeks before it.

    `prior_weeks` exists because the interesting claims span weeks — "third
    week running" needs last week's verdict, and the renderers read it from
    here rather than reconstructing it. Live, this is what the stored records
    in digest/ supply; deriving them is only for a dry run of a past week.
    """
    monday = monday_of(week_key)
    weeks = [monday - timedelta(days=7 * i)
             for i in range(prior_weeks, -1, -1)]
    span_start, span_end = weeks[0], weeks[-1] + timedelta(days=4)
    ftd_periods = (len(weeks) // 2) + ftd_monitor.MIN_FLAG_PERIODS + 2
    ctx = gather(span_start, span_end, ftd_periods)
    return [build_week(ctx, m) for m in weeks], ctx


def gather(span_start, span_end, ftd_periods):
    ctx = {}
    print(f"Fetching sources for {span_start} .. {span_end}")
    for name, fn in [
        ("short_volume", lambda: fetch_short_volume(span_start)),
        ("short_interest", fetch_short_interest),
        ("bars", lambda: fetch_bars(span_start)),
        ("filings", fetch_filings),
        ("threshold", lambda: fetch_threshold(span_start, span_end)),
        ("dilution", fetch_dilution),
        ("ftd", lambda: fetch_ftd(ftd_periods)),
    ]:
        src = fn()
        ctx[name] = src
        print(f"  {name:<16} {src.status:<12} {src.seconds:5.1f}s  "
              f"{src.requests:3d} req  {src.note}")
    return ctx


# ---------------------------------------------------------------- BACKFILL --


def report(records, ctx):
    """Print the distributions the threshold has to be set from."""
    print("\n" + "=" * 72)
    print("CONVERGENCE DISTRIBUTION")
    print("=" * 72)
    print(f"{len(records)} weeks, {len(TICKERS)} tickers, "
          f"{len(CONTRIBUTORS)} registered contributors\n")

    counts = defaultdict(int)
    per_week = []
    for rec in records:
        dist = defaultdict(int)
        for t, cv in rec["convergence"].items():
            dist[cv["count"]] += 1
            counts[cv["count"]] += 1
        per_week.append((rec["week"], dist, rec["denominator"]))

    maxn = max(counts) if counts else 0
    print(f"Counting DISTINCT SOURCE FAMILIES, not contributors — "
          f"{', '.join(sorted(set(SOURCE_FAMILY.values())))} collapses "
          f"{', '.join(sorted(SOURCE_FAMILY))}.\n")
    print(f"{'week':<10}{'denom':>6}  " +
          "".join(f"{'=' + str(i):>5}" for i in range(maxn + 1)) +
          f"   names at >={CONVERGENCE_THRESHOLD}")
    for rec, (wk, dist, den) in zip(records, per_week):
        names = sorted(t for t, cv in rec["convergence"].items()
                       if cv["converged"])
        print(f"{wk:<10}{den['families']:>6}  " +
              "".join(f"{dist.get(i, 0):>5}" for i in range(maxn + 1)) +
              "   " + (", ".join(names) if names
                       else "nothing converged this week"))
    total = sum(counts.values())
    print(f"\n{'pooled':<10}{'':>6}  " +
          "".join(f"{counts.get(i, 0):>5}" for i in range(maxn + 1)))
    print(f"{'':<10}{'':>6}  " +
          "".join(f"{counts.get(i, 0) / total * 100:>4.0f}%"
                  for i in range(maxn + 1)) + "   of all ticker-weeks")

    print("\nTicker-weeks naming a company, by threshold:")
    for k in range(1, maxn + 1):
        n = sum(v for i, v in counts.items() if i >= k)
        print(f"  >={k}: {n:4d} ticker-weeks "
              f"({n / len(records):.1f} per week, "
              f"{n / total * 100:.0f}% of the roster-weeks)")

    print("\n" + "=" * 72)
    print("PER-CONTRIBUTOR NOTABLE RATE")
    print("=" * 72)
    print(f"{'contributor':<18}{'cadence':<15}{'persist':<9}"
          f"{'notable':>8}{'/wk':>7}   {'n/testable':>10}{'failed':>8}")
    for c in CONTRIBUTORS:
        n = sum(1 for rec in records for t in TICKERS
                if rec["verdicts"].get(t, {}).get(c["key"], {}).get("level")
                == NOTABLE)
        nt = sum(1 for rec in records for t in TICKERS
                 if rec["verdicts"].get(t, {}).get(c["key"], {}).get("level")
                 == NOT_TESTABLE)
        sf = sum(1 for rec in records for t in TICKERS
                 if rec["verdicts"].get(t, {}).get(c["key"], {}).get("level")
                 == SOURCE_FAILED)
        print(f"{c['key']:<18}{c['cadence']:<15}"
              f"{'yes' if c['cadence'] in PERSISTENCE_CADENCES else 'no':<9}"
              f"{n:>8}{n / len(records):>7.1f}   {nt:>10}{sf:>8}")

    print("\n" + "=" * 72)
    print("FILINGS SUB-RULES — which one drives the rate")
    print("=" * 72)
    subs = defaultdict(int)
    weeks_with = defaultdict(set)
    for rec in records:
        for t in TICKERS:
            d = rec["verdicts"].get(t, {}).get("filings", {}).get("detail") or {}
            if d.get("filings_in_week"):
                subs["any filing (presence)"] += 1
                weeks_with["any filing (presence)"].add((rec["week"], t))
            if d.get("always_post_items"):
                subs["8-K ALWAYS_POST item"] += 1
            if d.get("press_release_items"):
                subs["8-K press-release item"] += 1
            for name, n in (d.get("by_class") or {}).items():
                if n:
                    subs[f"form class: {name}"] += 1
    roster_weeks = len(records) * len(TICKERS)
    for name in sorted(subs, key=lambda k: -subs[k]):
        print(f"  {name:<30}{subs[name]:>5} ticker-weeks "
              f"({subs[name] / roster_weeks * 100:>4.0f}% of roster-weeks, "
              f"{subs[name] / len(records):>4.1f}/wk)")

    print("\n" + "=" * 72)
    print("PERSISTENCE ACROSS WEEKS")
    print("=" * 72)
    runs = defaultdict(list)
    for rec in records:
        for t in TICKERS:
            for c in CONTRIBUTORS:
                v = rec["verdicts"].get(t, {}).get(c["key"], {})
                if v.get("level") == NOTABLE and v.get("persistence"):
                    runs[(t, c["key"])].append(rec["week"])
    multi = {k: v for k, v in runs.items() if len(v) >= 2}
    if multi:
        for (t, key), weeks in sorted(multi.items(), key=lambda kv: -len(kv[1])):
            print(f"  {t:<6}{key:<16}{len(weeks)} weeks: {', '.join(weeks)}")
    else:
        print("  no ticker qualified on a persistence-carrying contributor in "
              "more than one week")

    # DETAIL KEYS ARE A SHARED NAMESPACE even though the dicts are not, and a
    # renderer keys on them. `baseline_median` meant a volume median to one
    # contributor and a fails-peak median to another; a renderer that matched
    # the first then read a field only the second has died on a KeyError, and
    # would have printed a wrong figure had the field happened to exist.
    # Printed so a collision is visible rather than latent.
    print("\n" + "=" * 72)
    print("DETAIL KEYS SHARED BY MORE THAN ONE CONTRIBUTOR")
    print("=" * 72)
    owners = defaultdict(set)
    for rec in records:
        for t in TICKERS:
            for key, v in rec["verdicts"].get(t, {}).items():
                for field in (v.get("detail") or {}):
                    owners[field].add(key)
    shared = {k: v for k, v in owners.items() if len(v) > 1}
    if shared:
        for field, keys in sorted(shared.items()):
            print(f"  {field:<26} {', '.join(sorted(keys))}")
        print("  Shared is fine where the quantity is the same. Where it is "
              "not, rename — the name is all a renderer has.")
    else:
        print("  None.")

    print("\n" + "=" * 72)
    print("CONTRIBUTOR COVERAGE — untested is not the same as working")
    print("=" * 72)
    # Three states, and collapsing any two of them is the error this section
    # exists to prevent. A contributor that never fetched proves nothing about
    # its rule; one that fetched and never fired has an UNTESTED rule; one that
    # fired is exercised. The middle case is the dangerous one, because an
    # empty section from it looks identical to a working one.
    for c in CONTRIBUTORS:
        weeks_counted = sum(1 for rec in records
                            if rec["contributors"][c["key"]]["counted_in_denominator"])
        weeks_fetched = sum(1 for rec in records
                            if rec["contributors"][c["key"]]["fetched"])
        n = sum(1 for rec in records for t in TICKERS
                if rec["verdicts"].get(t, {}).get(c["key"], {}).get("level")
                == NOTABLE)
        if not weeks_fetched:
            print(f"  {c['key']:<18} NOT FETCHED in any week — says nothing "
                  f"about its rule either way.")
        elif n == 0:
            print(f"  {c['key']:<18} UNTESTED — fetched in {weeks_fetched} "
                  f"week(s), counted in {weeks_counted}, and fired for no "
                  f"company in any of them. Its rule has never been exercised "
                  f"against a real occurrence, so an empty section from it "
                  f"cannot yet be read as a working one.")
            if c["key"] not in UNEXERCISED:
                print(f"  {'':<18} ^ NOT IN weekly_digest.UNEXERCISED — add it, "
                      f"or the renderers will present its silence as a result.")
        elif c["key"] in UNEXERCISED:
            print(f"  {c['key']:<18} FIRED {n} time(s) — remove it from "
                  f"weekly_digest.UNEXERCISED. Its rule is now exercised.")
    th = ctx["threshold"].data or {}
    ever = sorted({t for h in (th.get("by_day") or {}).values() for t in h})
    print(f"\n  threshold_list: {len(th.get('by_day') or {})} daily files read, "
          f"roster companies ever listed: {', '.join(ever) if ever else 'NONE'}")


def main():
    n = int(os.environ.get("DIGEST_BACKFILL", "0") or 0)
    if not n:
        sys.exit("Set DIGEST_BACKFILL=<weeks>. There is no renderer yet — this "
                 "file derives and records, and nothing else.")

    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    demonstrate_cadence_guard()
    weeks = recent_weeks(n)
    span_start, span_end = weeks[0], weeks[-1] + timedelta(days=4)
    # Enough half-month periods to cover the span plus MIN_FLAG_PERIODS of
    # baseline behind it.
    ftd_periods = (n // 2) + ftd_monitor.MIN_FLAG_PERIODS + 2

    print(f"Backfilling {n} complete ISO weeks: "
          f"{iso_week_key(weeks[0])} .. {iso_week_key(weeks[-1])}\n")
    t0 = time.time()
    ctx = gather(span_start, span_end, ftd_periods)
    fetch_seconds = time.time() - t0

    records = []
    for monday in weeks:
        rec = build_week(ctx, monday)
        records.append(rec)
        named = sorted(t for t, cv in rec["convergence"].items()
                       if cv["converged"])
        print(f"  {rec['week']}  {rec['monday']}..{rec['friday']}  "
              f"denominator {rec['denominator']['families']} families "
              f"({rec['denominator']['counted']}/"
              f"{rec['denominator']['registered']} contributors)  "
              f"converged: {', '.join(named) if named else 'nothing'}")

    out = {
        "schema": SCHEMA,
        "generated": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "note": ("Verdict record for the weekly digest. Re-derived from source, "
                 "never aggregated from posted messages. Figures under "
                 "'detail' carry the baseline they are measured against; a "
                 "level of 'not-testable' means the rule could not be applied, "
                 "which is not the same as 'routine'."),
        "backfill_weeks": n,
        "fetch_seconds": round(fetch_seconds, 1),
        "total_requests": sum(s.requests for s in ctx.values()),
        "weeks": records,
    }
    path = os.environ.get("DIGEST_OUT", "digest_backfill.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    report(records, ctx)
    print(f"\nFetched in {fetch_seconds:.1f}s, "
          f"{out['total_requests']} requests. Wrote {path} "
          f"({os.path.getsize(path) / 1024:.0f} KB).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
