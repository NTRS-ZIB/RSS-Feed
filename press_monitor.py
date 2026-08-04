#!/usr/bin/env python3
"""
Press release monitor -> Slack or Discord.

Watches two sources per company:
  1. SEC EDGAR filings (8-K for US issuers, 6-K for foreign private issuers)
  2. The company's own IR newsroom RSS feed, if it has one

Dedupes against state.json so each item is posted exactly once.
"""

import html
import json
import os
import re
import socket
import sys
import time
from calendar import timegm
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests

import watchlist
# ------------------------------------------------------------------ CONFIG

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one.
#
# EXTRA_CIKS is keyed by CIK because CIKs are permanent and tickers are not.
# This sector renames constantly and SEC's ticker lookup file lags renames by
# weeks, so pinning by CIK sidesteps that entirely.
#
# IR_FEEDS is keyed by TICKER. It was previously keyed by display label — a mix
# of tickers and company names — so nothing joined a feed to its company, and a
# company could be dropped from the watchlist while its feed kept being polled.
# Feed URLs are unchanged; only the log labels differ.
TICKERS = []  # Ticker lookup is fragile across renames; see EXTRA_CIKS above.
EXTRA_CIKS = watchlist.ciks()          # {ticker: (cik, name)}
IR_FEEDS = watchlist.ir_feeds()        # {ticker: url}, companies that have one

# EVERY COMPANY ON THE ROSTER IS NOW COVERED BY SOMETHING FASTER THAN EDGAR.
# Four different ways, because four companies publish no feed on their own
# newsroom, and each turned out to be a different problem:
#
#   own IR feed          ten companies, IR_FEEDS
#   newswire feed        BGDE — GlobeNewswire's organization feed
#   separate IR host     WYFI — whitefiber.investorroom.com, found by
#                        autodiscovery OUT of a Webflow shell that has no
#                        headlines in it
#   scrape               HUT — server-side HTML, scrape_hut8()
#   CMS API              DGXX — public Strapi, read_dgxx()
#
# The lesson that took four attempts: a newsroom with no readable HTML does not
# mean no feed. Three of the four had a machine-readable source somewhere other
# than the company's own domain, and checking that domain alone is what kept
# concluding otherwise.
#
# DGXX carries TWO TRAPS that both parse cleanly while being dead, and neither
# must ever be wired up: the old GlobeNewswire organization feed still returns
# 20 items, none newer than 2025-12-24; and digipowerx.com/sitemap.xml lists
# 100 release URLs whose lastmod values are one identical rebuild stamp, with
# nothing since 2025.
#
# HUT also publishes no feed, but is NOT one of those: its releases render
# server-side and come back complete in a plain fetch, so it is scraped instead
# — see scrape_hut8(). That closes a latency gap rather than a blind spot;
# everything material reaches EDGAR as an 8-K eventually, just hours later.
HUT_PAGE = "https://www.hut8.com/news-insights/press-releases"

# DGXX publishes no feed anywhere — not on its own domain, and not on either
# wire it has used. Its newsroom is a Next.js shell backed by a PUBLIC Strapi
# CMS, which is read directly. A JSON contract, so more stable than the HUT
# scrape, but on infrastructure with a weaker guarantee: see read_dgxx().
DGXX_API = ("https://thankful-miracle-1ed8bdfdaf.strapiapp.com"
            "/api/press-releases")
DGXX_PAGE = "https://www.digipowerx.com/press-releases"

# An explicit horizon for DGXX, passed to check_staleness() as a floor. The
# shared check would compute 60d from the 25 items it fetches; this comes from
# the full 197-item history instead — 75 releases over 24 months, median gap 8
# days, LONGEST observed gap 34. Better evidence than a 25-item window, so the
# shared check defers to it. See check_staleness().
DGXX_STALE_DAYS = 90

# ------------------------------------------------------- STALENESS CHECK ----
#
# The loud failures are already handled: a fetch error, a non-200 and a parse
# error each log distinctly. This covers the QUIET one — a source returning
# HTTP 200 with valid content, correct timestamps, and nothing new for months.
#
# That is not hypothetical. Two sources failed exactly this way in one day:
# DGXX's old GlobeNewswire feed served 20 well-formed items with nothing newer
# than 2025-12-24, and digipowerx.com/sitemap.xml listed 100 URLs sharing one
# identical rebuild timestamp. Both would have looked healthy in every log line
# indefinitely. A company changing IR platform, changing newswire, or having a
# feed quietly retired all produce this shape.
#
# NO FIXED HORIZON WORKS, because cadences differ by an order of magnitude
# across this roster — measured, collapsed to distinct publication days:
#
#   NUAI 5d    IREN 6d    WYFI 6d    SLNH 7d    MARA 8d    DGXX 8d
#   WULF 9d    BKKT 13d   BGDE 13d   CIFR 14d   VIP 15d    ANY 15d
#   CLSK 15d   HUT 18d
#
# So each source is judged against ITS OWN median gap, the same principle the
# rest of the repo uses for every metric: never a bare absolute.
#
# THE MULTIPLE AND THE FLOOR DO DIFFERENT JOBS, and neither is redundant.
# Calibrated against all fourteen live sources plus one known-dead control:
#
#   the multiple  makes SLOW feeds wait longer than the floor. CLSK, VIP and
#                 ANY fire at 90d, HUT at 111d. A flat 60d would fire on them
#                 during an ordinary lull.
#   the floor     stops FAST feeds firing during an ordinary quiet spell. At
#                 6x alone NUAI would fire after 30 days of silence, which is
#                 a perfectly normal month for a company that usually
#                 publishes weekly.
#
# 6x is the tightest multiple with no false positives across the fourteen: the
# worst healthy source sits at 5.0x and the dead control at 31.8x.
STALE_MULTIPLE = 6
STALE_FLOOR_DAYS = 60

# Distinct publication days needed before a median means anything. Below this,
# "not enough history to judge" is reported as its own state rather than
# passing silently — a median from two gaps is not evidence.
STALE_MIN_DAYS = 4


# EDGAR form types to watch. 8-K = US material events. 6-K = foreign issuers.
# Add "10-Q", "10-K" if you want periodic reports too.
# EDGAR's type filter is a PREFIX match, which does useful work here:
#   "8-K"  also catches 8-K/A       "10-Q" also catches 10-Q/A
#   "424"  catches 424B1 ... 424B8  "SC 13D" also catches SC 13D/A
FORM_TYPES = [
    "8-K",     # US material events; press releases attach as EX-99
    "6-K",     # same, foreign private issuers
    "424",     # prospectus supplements. An offering being priced.
    # Registration statements. 424 catches the prospectus that FOLLOWS one,
    # but the registration itself is filed weeks earlier and is the first
    # public signal that a raise is coming. S-1 is a first-time or ineligible
    # registrant; S-3 is a shelf, which is how most secondaries and ATM
    # programmes here are actually run. Prefix matching covers S-1/A and S-3/A,
    # and amendments matter: a company can sit on a shelf for months and the
    # amendment is often the sign it is about to be used.
    "S-1",
    "S-3",     # shelf registration
    "10-Q",    # quarterly financials
    "10-K",    # annual financials
    "20-F",    # annual, foreign private issuers
    "40-F",    # annual, Canadian MJDS filers
    # BOTH spellings are needed. The SEC moved Schedule 13D/G to structured XML
    # filings and the EDGAR form-type string changed from "SC 13D" to
    # "SCHEDULE 13D" — and "SCHEDULE 13D".startswith("SC 13D") is False,
    # because the fourth character is H rather than a space.
    #
    # The old prefix silently matched nothing from that point on. It was found
    # only because a real 13D on Sphere 3D went unposted. `SC 13D` is retained
    # for filings made before the changeover.
    "SC 13D",
    "SCHEDULE 13D",  # activist / >5% stake disclosures
    # 13G is the PASSIVE counterpart to 13D: same >5% threshold, but filed by
    # holders with no intent to influence control, which in practice means
    # index funds and most institutions. Expect routine February amendments
    # rather than events. Both spellings for the same reason as 13D above.
    #
    # If this proves too noisy in the filings channel, move it to the insider
    # channel rather than dropping it. Ownership changes are a different kind
    # of news from company announcements, which is why Form 4 lives there.
    "SC 13G",
    "SCHEDULE 13G",  # passive / >5% stake disclosures
    # "NT " covers the whole late-filing family under Rule 12b-25: NT 10-K,
    # NT 10-Q, NT 20-F, NT 40-F and any future sibling. Listing two of them
    # individually meant NT 20-F was missing entirely — found by the drift
    # detector on its first run, and it is precisely the form IREN or DGXX
    # would file if an annual report ran late.
    #
    # Low volume, high signal: a company telling the SEC it cannot file on time
    # is worth knowing about whichever annual form it files.
    "NT ",
]

# The EX-99 exhibit check only makes sense for press-release-bearing forms.
# Applying it to a 10-Q or 424 would discard every one of them.
EXHIBIT_CHECK_FORMS = {"8-K", "6-K"}

# If True, an EDGAR filing is only posted when it actually attaches a press
# release (an EX-99 exhibit). Filters out pure administrative 8-Ks.
# Costs one extra HTTP request per new filing.
PRESS_RELEASE_EXHIBIT_ONLY = True

# Optional keyword filter, applied to titles. Empty list = post everything.
# e.g. ["acquisition", "dividend", "guidance"]
KEYWORDS = []

# Hard age floor. A filing older than this is marked seen but NEVER posted,
# whatever the state file says.
#
# The cap alone is not enough. state.json answers "have I seen this?", which
# silently becomes "no" for thousands of old filings whenever the state is
# reset or the data source starts returning deeper history. Migrating from
# browse-edgar (40 filings per form) to the submissions API (~1,000 filings of
# all types) did exactly that: 1,471 historical filings looked new at once and
# the channel got 65 messages of old news.
#
# An age floor is independent of state, so backfill can never be mistaken for
# news. Keep it comfortably above the run interval.
MAX_AGE_DAYS = 7

# Only EDGAR filings from the last N days enter the dedupe set at all.
# Nothing older can post (MAX_AGE_DAYS), so remembering it is pure state-file
# bloat: the submissions endpoint returns ~1,000 filings per company, which
# put 4,275 ids in state.json for a watchlist of eleven.
#
# Must stay comfortably above MAX_AGE_DAYS — the gap is the safety margin for
# a workflow outage. Not applied to IR feed items, which are ~10 per feed and
# whose timestamps are less reliable.
RETAIN_DAYS = 30

# Safety valve: never post more than this in one run, per channel.
# Sized for earnings season: ~10 companies x (8-K + 10-Q + IR item) landing in
# one window. Overflow is discarded, not queued, so leave headroom.
MAX_POSTS_PER_RUN = 40
MAX_INSIDER_POSTS_PER_RUN = 25

# Insider transactions, routed to their own webhook. Only runs when the
# WEBHOOK_URL_INSIDER secret is set, so it's opt-in.
#
# NOTE on the query: EDGAR's type filter is a prefix match, so type=4 also
# returns 40-F and 424B*. Entries are therefore filtered against
# INSIDER_ALLOWED_FORMS using the form type EDGAR reports on each entry.
INSIDER_QUERY_FORM = "4"
# Form 3 is an insider's INITIAL statement of ownership, filed within 10 days
# of becoming an officer, director or >10% holder. It reports no transaction,
# so it is not a trade — but it is the first appearance of a new insider, and
# on a watchlist where boards turn over it is worth seeing. Form 4 is the
# ongoing transaction report.
#
# Form 5 is deliberately excluded: an annual catch-up of small or exempt
# transactions that should have been reported already, filed in bulk after
# year end. High volume, low signal.
INSIDER_ALLOWED_FORMS = {"3", "3/A", "4", "4/A"}

# ------------------------------------------------------------------ RUNTIME

socket.setdefaulttimeout(25)

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
INSIDER_WEBHOOK_URL = os.environ.get("WEBHOOK_URL_INSIDER", "").strip()
# Dry run: fetch, evaluate, print what WOULD post — but post nothing and,
# critically, do NOT save state. Saving would mark everything seen and the
# next real run would then post nothing at all.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
# SEC requires a descriptive User-Agent with a contact address.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

# Several IR platforms sit behind WAFs that stall non-browser User-Agents
# instead of returning an error. A browser-like header set avoids that.
IR_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
IR_HEADERS = {
    "User-Agent": IR_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9,"
              " text/html;q=0.8, */*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
# One request per company returns every recent filing, replacing what used to
# be ~10 browse-edgar calls plus an index fetch per candidate. The legacy
# cgi-bin/browse-edgar endpoint is slow and times out under load; this is the
# modern JSON API and is markedly more reliable.
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index.htm"

# 8-K item numbers that carry a press release. Replaces fetching each filing's
# index page to look for an EX-99 exhibit — the items are already in the
# submissions payload, so this costs no extra request.
#   2.02 results   7.01 Reg FD   8.01 other events
PRESS_RELEASE_ITEMS = {"2.02", "7.01", "8.01"}

# Material events posted whether or not a press release accompanies them.
# Checked BEFORE the exhibit filter, because the whole point is that these
# usually arrive without one.
#
# The exhibit filter is best at removing the filings you most want. A company
# restating its financials is the case LEAST likely to issue a press release
# about it, so the filter that keys on "is there a press release" removes it
# every time. Measured across all fourteen companies' full histories — 1,986
# 8-K filings as of 2026-08-03. Re-derive with audit_8k_items.py; the totals
# drift upward as filings accumulate, so it is the RATIOS that are the argument:
#
#   4.02  10 appearances, ALL TEN dropped        (a restatement, never announced)
#   4.01  32 appearances, 94% dropped            (auditor change)
#   3.01  65 appearances, 75% dropped            (delisting notice)
#   1.03  never occurred on this roster          (which is the point of watching)
#
# The case that prompted this: NUAI filed `items=4.02` alone on 2026-07-30 — a
# restatement with no other item code and no press release — and it was dropped.
#
# 5.02 director/officer change was CONSIDERED AND EXCLUDED. It is 75% dropped
# across 300 filings, but adding it would post ~1.9/month against ~1.3/month for
# all seven of these combined, and the concentration shows why: BKKT filed 5.02
# six times between 2025-08-12 and 2025-11-14, MARA and SLNH 52 times each. That
# is board churn, not officer departures, and the item code cannot separate "CFO
# resigns abruptly" from "board appoints a fourth independent director". The
# insider channel already covers the people-acting side.
#
# 1.02 (terminated agreement — more often an expiry than a rupture, 59% already
# post with a release) and 2.01 (one dropped filing in nineteen months) were
# also considered and left out.
#
# NEVER ADD 9.01. It is an attachment marker appearing on 1,530 of 1,986
# filings (2026-08-03) and means nothing on its own; including it would post
# essentially every 8-K and silently undo the exhibit filter entirely.
ALWAYS_POST_ITEMS = {
    "1.03",   # Bankruptcy or receivership
    "2.04",   # Obligation accelerated
    "2.06",   # Material impairment
    "3.01",   # Delisting notice / listing rule
    "4.01",   # Auditor change
    "4.02",   # Non-reliance on prior financials
    "5.01",   # Change in control
}

# Always-post items render amber rather than the default blue. A reader's prior
# on a main-channel post is "the company announced something"; these are the
# inverse — material filings the company chose NOT to announce — and that
# inversion is worth a colour rather than another line of prose. The
# ITEM_LABELS text in the title already carries the specifics. No collision
# with the insider channel's amber: different webhook.
UNANNOUNCED_COLOR = 0xD29922

# 8-K item codes in plain English, for Discord titles. SEC only supplies a
# document label (usually just "8-K"), which is redundant next to the form
# type already shown in the footer.
ITEM_LABELS = {
    "1.01": "Material agreement entered",
    "1.02": "Material agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety",
    "1.05": "Cybersecurity incident",
    "2.01": "Acquisition or disposition completed",
    "2.02": "Results of operations",
    "2.03": "Direct financial obligation created",
    "2.04": "Obligation accelerated",
    "2.05": "Exit or disposal costs",
    "2.06": "Material impairment",
    "3.01": "Delisting notice / listing rule",
    "3.02": "Unregistered equity sales",
    "3.03": "Security holder rights modified",
    "4.01": "Auditor change",
    "4.02": "Non-reliance on prior financials",
    "5.01": "Change in control",
    "5.02": "Director or officer change",
    "5.03": "Bylaws or fiscal year change",
    "5.04": "Employee plan trading suspension",
    "5.05": "Code of ethics amended",
    "5.06": "Shell company status change",
    "5.07": "Shareholder vote results",
    "5.08": "Shareholder director nominations",
    "7.01": "Reg FD disclosure",
    "8.01": "Other events",
    "9.01": "Financial statements and exhibits",
}

# Boilerplate: appears on almost any 8-K carrying an attachment, so it says
# nothing on its own. Suppressed unless it is the only item listed.
GENERIC_ITEMS = {"9.01"}

# Plain-English names for the other forms, longest prefix wins.
FORM_LABELS = {
    "NT 10-K": "LATE FILING NOTICE — annual report",
    "NT 10-Q": "LATE FILING NOTICE — quarterly report",
    "SC 13D": "Activist stake disclosure (>5%)",
    "424": "Prospectus supplement — offering",
    "10-Q": "Quarterly report",
    "10-K": "Annual report",
    "20-F": "Annual report (foreign issuer)",
    "40-F": "Annual report (Canadian issuer)",
    "6-K": "Foreign issuer report",
    "8-K": "Material event",
}


def sec_headers(host):
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": host,
    }


def sec_get_json(url, host, tries=2):
    """GET JSON from an SEC host. Returns parsed JSON or None.

    Timeouts are a (connect, read) tuple. A bare scalar applies to BOTH
    phases separately, so a single stalled request could consume 60s rather
    than 30 — which, multiplied by retries and form types, was enough to
    blow the workflow's 10-minute budget.
    """
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=sec_headers(host), timeout=(8, 20))
            if r.status_code == 200:
                time.sleep(0.15)  # stay well under SEC's 10 req/sec ceiling
                return r.json()
            if r.status_code == 404:
                print(f"  not found: {url}", file=sys.stderr)
                return None
            if r.status_code in (429, 503):
                time.sleep(3 * (attempt + 1))
                continue
            print(f"  HTTP {r.status_code} for {url}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            print(f"  {type(e).__name__}, retrying", file=sys.stderr)
            time.sleep(2)
        except ValueError:
            print(f"  unparseable JSON from {url}", file=sys.stderr)
            return None
    return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print("state.json unreadable, treating as first run", file=sys.stderr)
    return {"seen": [], "initialized": False}


def save_state(state, items_this_run=0):
    """Persist state, retaining enough history to cover a full run's visibility.

    The retained list MUST be longer than the number of items one run can see,
    or items age out of state, reappear as "new", and get re-posted. Since
    visibility scales with the watchlist, the cap scales with it too.
    """
    # 3x a run's visibility is the real protection; the constant is just a
    # sane minimum. It was 4000 when a run saw ~4,200 ids. With RETAIN_DAYS a
    # run sees ~130, so 4000 would pin the file at ~250KB of dead history.
    floor = max(1000, items_this_run * 3)
    state["seen"] = state["seen"][-floor:]
    STATE_FILE.write_text(json.dumps(state, indent=1))
    print(f"State: {len(state['seen'])} ids retained (cap {floor}).")


def resolve_ciks(tickers):
    """Map tickers to zero-padded CIKs using SEC's official lookup file."""
    raw = sec_get(TICKER_MAP_URL)
    if not raw:
        print("Could not fetch SEC ticker map; aborting.", file=sys.stderr)
        sys.exit(1)
    data = json.loads(raw)
    by_ticker = {
        row["ticker"].upper(): (str(row["cik_str"]).zfill(10), row["title"])
        for row in data.values()
    }
    resolved, missing = {}, []
    for t in tickers:
        hit = by_ticker.get(t.upper())
        if hit:
            resolved[t.upper()] = hit
        else:
            missing.append(t)
    if missing:
        print(f"Not found on EDGAR (check the ticker): {', '.join(missing)}",
              file=sys.stderr)
    return resolved


def form_matches(form, prefixes):
    """EDGAR-style prefix match: '8-K' also matches '8-K/A'."""
    return any(form.startswith(p) for p in prefixes)


def form_core(form):
    """Alphanumeric core of a form type: 'SC 13D/A' -> 'SC13D'.

    Amendment suffixes and spacing are stripped so that two spellings of the
    same filing can be compared for family resemblance.
    """
    return re.sub(r"[^A-Z0-9]", "", form.upper().split("/")[0])


# Obsolete forms that will never be filed again but still sit in old filing
# histories. Flagging them every run would turn the warning into noise, and a
# warning that always fires is one nobody reads.
DRIFT_IGNORE = {
    "10KSB", "10QSB", "10KSB/A", "10QSB/A",   # small-business forms, ended 2009
    "10-KSB", "10-QSB", "10-K405",
}


def drift_candidates(seen_forms):
    """Forms that resemble something tracked but do not match it.

    A form type that matches nothing produces exactly the same output as one
    whose filings never occur: no posts, no error, no log line. `SC 13D` sat in
    FORM_TYPES matching nothing after the SEC renamed the form type to
    `SCHEDULE 13D`, and it was found only when a real activist stake in a
    watchlist company went unreported.

    The rule that catches it without knowing the new spelling in advance: if an
    unmatched form's core CONTAINS a tracked prefix's core, or vice versa, the
    two are probably the same filing under a changed name. `SCHEDULE 13D` ->
    `SCHEDULE13D` contains `13D`; `SC 13D` -> `SC13D` contains `13D`.
    """
    tracked = list(FORM_TYPES) + sorted(INSIDER_ALLOWED_FORMS)
    # Cores short enough to appear inside unrelated forms would match
    # everything, so require a distinctive stem.
    stems = {p: re.sub(r"^(SC|SCHEDULE|NT|FORM)", "", form_core(p)) for p in tracked}
    out = []
    for form in sorted(seen_forms):
        if form in DRIFT_IGNORE:
            continue
        if form_matches(form, tracked) or form in INSIDER_ALLOWED_FORMS:
            continue
        core = form_core(form)
        for prefix, stem in stems.items():
            if len(stem) >= 3 and stem in core:
                out.append((form, prefix))
                break
    return out


def always_post_items(item):
    """Whether this filing carries an item that posts regardless of a release.

    Set intersection, so a filing listing several items works whatever the
    order — an 8-K is routinely `4.02,9.01` or `3.01` alone, and both must
    match. Never depends on a single item or on position.
    """
    if not str(item.get("form") or "").startswith("8-K"):
        return False
    raw = item.get("items") or ""
    codes = {i.strip() for i in raw.split(",") if i.strip()}
    return bool(codes & ALWAYS_POST_ITEMS)


def carries_press_release(form, items):
    """Whether an 8-K's item numbers indicate a press release.

    Replaces fetching each filing's index page to look for an EX-99 exhibit.
    The items are already in the submissions payload, so this is free.
    6-K has no item numbers, so it is never filtered.
    """
    if not form.startswith("8-K"):
        return True
    if not items:
        # Fail open rather than drop it — the right default, since an 8-K with
        # no item codes is unclassifiable rather than uninteresting.
        #
        # UNTESTED PATH. Every 8-K across the fourteen companies' full
        # histories carries item codes — 1,986 of 1,986 at 2026-08-03, and
        # audit_8k_items.py reports the current count — so this branch has never
        # once executed. Same class as count_run() in the threshold list:
        # correct by construction, never exercised by real data. Left as is
        # deliberately; do not "simplify" it away because it never fires.
        return True
    listed = {i.strip() for i in items.split(",") if i.strip()}
    return bool(listed & PRESS_RELEASE_ITEMS)


def form_label(form):
    """Plain-English name for a form, longest matching prefix wins."""
    for prefix in sorted(FORM_LABELS, key=len, reverse=True):
        if form.startswith(prefix):
            label = FORM_LABELS[prefix]
            return f"{label} (amended)" if form.endswith("/A") else label
    return ""


def filing_title(form, items, description):
    """A title worth reading in Discord.

    For 8-Ks the item codes say what actually happened; SEC's own document
    label is usually just the form name, which the footer already shows.
    """
    if form.startswith("8-K") and items:
        codes = [c.strip() for c in items.split(",") if c.strip()]
        named = [(c, ITEM_LABELS[c]) for c in codes if c in ITEM_LABELS]
        meaningful = [lbl for c, lbl in named if c not in GENERIC_ITEMS]
        chosen = meaningful or [lbl for _, lbl in named]
        if chosen:
            title = ", ".join(dict.fromkeys(chosen))
            return f"{title} (amended)" if form.endswith("/A") else title

    return form_label(form) or description or f"{form} filing"


def company_filings(cik):
    """Every recent filing for a company, in one request."""
    data = sec_get_json(SUBMISSIONS.format(cik=cik), "data.sec.gov")
    if not data:
        return []
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    if not forms:
        return []

    accessions = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    items = recent.get("items") or []
    descriptions = recent.get("primaryDocDescription") or []

    out = []
    for i, form in enumerate(forms):
        try:
            acc = accessions[i]
            filed = dates[i]
        except IndexError:
            continue
        out.append({
            "form": form,
            "accession": acc,
            "filed": filed,
            "items": items[i] if i < len(items) else "",
            "description": descriptions[i] if i < len(descriptions) else "",
        })
    return out


def filing_url(cik, accession):
    return ARCHIVE.format(cik=int(cik), acc_nodash=accession.replace("-", ""),
                          acc=accession)


def filing_uid(accession):
    """Match the id format the old Atom feed produced, so switching data
    sources does not make every historical filing look new."""
    return f"urn:tag:sec.gov,2008:accession-number={accession}"


def filed_time(datestr):
    try:
        return timegm(date.fromisoformat(datestr).timetuple())
    except (ValueError, TypeError):
        return 0


def collect_all(resolved):
    """One submissions request per company; returns (press, insider)."""
    press, insider = [], []
    horizon = date.today() - timedelta(days=RETAIN_DAYS)
    seen_forms = set()
    for ticker, (cik, name) in resolved.items():
        filings = company_filings(cik)
        if not filings:
            print(f"  {ticker}: no filings returned")
            continue

        kept = ins = skipped = 0
        for f in filings:
            seen_forms.add(f["form"])
            try:
                if date.fromisoformat(f["filed"]) < horizon:
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                skipped += 1      # unparseable date: cannot post it anyway
                continue
            form, acc = f["form"], f["accession"]
            base = {
                "uid": filing_uid(acc),
                "accession": acc,
                "link": filing_url(cik, acc),
                "published": filed_time(f["filed"]),
                "is_edgar": True,
            }
            title = filing_title(form, f["items"], f["description"])

            if form in INSIDER_ALLOWED_FORMS:
                ins += 1
                insider.append({**base, "form": form,
                                "source": f"{name} ({ticker}) · Form {form}",
                                "title": title})
            elif form_matches(form, FORM_TYPES):
                kept += 1
                press.append({**base, "form": form,
                              "source": f"{name} ({ticker}) · SEC {form}",
                              "title": title,
                              "items": f["items"]})
        print(f"  {ticker}: {len(filings)} filing(s), {skipped} older than "
              f"{RETAIN_DAYS}d -> {kept} tracked, {ins} insider")

    drift = drift_candidates(seen_forms)
    if drift:
        print(f"\n  WARNING: {len(drift)} form type(s) resemble something in "
              f"FORM_TYPES but do not match it.")
        print("  A renamed form matches nothing and reports nothing — check "
              "whether these")
        print("  are the same filing under a new EDGAR spelling:")
        for form, prefix in drift:
            print(f"    seen {form!r}  vs tracked {prefix!r}")
    return press, insider


def discover_feed(page_url):
    """Find a feed URL from a page's <link rel="alternate"> tags."""
    try:
        r = requests.get(page_url, headers=IR_HEADERS, timeout=(10, 30))
        if r.status_code != 200:
            return None
        tags = re.findall(
            r"<link[^>]+application/(?:rss|atom)\+xml[^>]*>", r.text, re.I
        )
        for tag in tags:
            # Skip comment feeds — WordPress exposes those alongside the real one.
            if "comment" in tag.lower():
                continue
            href = re.search(r"""href=["']([^"']+)["']""", tag)
            if href:
                return urljoin(page_url, href.group(1))
    except requests.RequestException:
        pass
    return None


def parse_feed(url):
    """Fetch and parse a feed. Never blocks indefinitely. Retries once."""
    r = None
    for attempt in range(2):
        try:
            r = requests.get(url, headers=IR_HEADERS, timeout=(10, 30))
            break
        except requests.RequestException as e:
            if attempt == 0:
                print(f"    {type(e).__name__}, retrying once")
                time.sleep(2)
            else:
                print(f"    fetch failed: {type(e).__name__}")
                return []
    if r is None or r.status_code != 200:
        print(f"    HTTP {r.status_code if r is not None else '?'}")
        return []
    try:
        return feedparser.parse(r.content).entries or []
    except Exception as e:
        print(f"    parse failed: {type(e).__name__}")
        return []


def scrape_hut8():
    """HUT's press releases, scraped. Returns items shaped like collect_ir()'s.

    HOW IT FAILS IS THE POINT. A feed that breaks usually errors; a scraper whose
    selectors stop matching returns nothing and looks exactly like a quiet week.
    HUT publishes two to four releases a month, so that could sit for a long time.

    What makes the two states separable here: this page lists roughly nine
    HISTORICAL releases and never empties. A genuinely quiet month still returns
    nine. So zero items from an HTTP 200 cannot mean "no news" — it can only mean
    the markup moved, and it is logged as a parse failure rather than as a count.

    Never raises. One scraper must not take down thirteen feeds and the EDGAR
    sweep with it.
    """
    try:
        r = requests.get(HUT_PAGE, headers=IR_HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"  HUT: fetch failed: {type(e).__name__}")
        return []
    if r.status_code != 200:
        print(f"  HUT: HTTP {r.status_code}")
        return []

    # The page carries two overlapping lists — "Featured Press Releases" and
    # "All Press Releases" — and the same release appears in both. Anchors are
    # collected across the whole document and deduplicated by URL below.
    #
    # Both blocks label their parts with class="date" and class="title", but the
    # featured block wraps them in <p> and the all block in <div>, so the tag is
    # deliberately not matched. Extracting by structure beats splitting the
    # concatenated link text, which also carries a "press release" category
    # label in one block and not the other.
    items, seen = [], set()
    for m in re.finditer(
            r'<a[^>]+href="([^"]*/news-insights/press-releases/[^"]+)"[^>]*>',
            r.text):
        end = r.text.find("</a>", m.start())
        if end < 0:
            continue
        inner = r.text[m.end():end]

        def part(name):
            g = re.search(rf'class="{name}"[^>]*>(.*?)</', inner, re.S)
            if not g:
                return None
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", g.group(1))).strip()

        title, when = part("title"), part("date")
        if not title:
            continue
        # Hrefs are relative — "/news-insights/..." — despite looking absolute
        # in a browser. Joining is what makes the URL usable as a uid.
        link = urljoin(HUT_PAGE, m.group(1))
        if link in seen:
            continue
        seen.add(link)

        published = 0
        if when:
            try:
                published = timegm(time.strptime(when, "%b %d, %Y"))
            except ValueError:
                pass
        items.append({
            "uid": link,
            "source": "HUT · IR newsroom",
            "title": html.unescape(title),
            "link": link,
            "published": published,
            "is_edgar": False,
        })

    if not items:
        print("  HUT: PARSE FAILURE — HTTP 200 but 0 items. This page lists ~9 "
              "historical releases and never empties, so this is the markup "
              "moving, not a quiet week.")
        return []

    # Document order is not date order: the featured block mixes recent items
    # with older ones. Sort rather than trusting position.
    items.sort(key=lambda i: i["published"], reverse=True)
    print(f"  HUT: {len(items)} items (scraped)")
    check_staleness("HUT", [i["published"] for i in items])
    return items


def check_staleness(label, published, override_days=None):
    """Warn when a source parses cleanly but has stopped producing anything new.

    One check for all fourteen sources — feeds, the scraper and the CMS reader
    alike. The strictest treatment had been built for the newest source and the
    twelve oldest had none, which was backwards.

    `override_days` raises the horizon where better evidence exists than the
    fetched window. Only DGXX passes one; see DGXX_STALE_DAYS.

    Logs and returns. Never raises, never suppresses items: a stale source may
    simply be quiet, its items still deduplicate normally, and one source going
    dark must not affect the other thirteen or the EDGAR sweep.
    """
    times = sorted((t for t in published if t), reverse=True)
    if not times:
        return
    age = (time.time() - times[0]) / 86400

    # Collapse to distinct UTC days before measuring. Three releases in one
    # morning are one publication event, and their zero-day gaps drag the
    # median down until a normal quiet spell looks like a failure. Measured:
    # HUT's median reads 5.5d uncollapsed and 18d collapsed, MARA's 4.4d and
    # 8d — so this is load-bearing, not tidiness.
    days = sorted({int(t // 86400) for t in times}, reverse=True)

    if len(days) < STALE_MIN_DAYS:
        print(f"    {label}: insufficient history to judge staleness — "
              f"{len(days)} publication day(s), newest {age:.0f}d old")
        return

    gaps = sorted(days[i] - days[i + 1] for i in range(len(days) - 1))
    mid = len(gaps) // 2
    median = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2

    computed = STALE_MULTIPLE * median
    horizon = max(computed, STALE_FLOOR_DAYS, override_days or 0)

    # Name whichever term actually set the horizon, so the log explains itself.
    if override_days and horizon == override_days:
        basis = f"measured {override_days}d horizon for this source"
    elif horizon == computed:
        basis = f"{median:.0f}d median gap x{STALE_MULTIPLE}"
    else:
        basis = f"{STALE_FLOOR_DAYS}d floor, above its {median:.0f}d median gap"

    if age > horizon:
        print(f"    {label}: STALE — parses cleanly, but the newest item is "
              f"{age:.0f}d old against a {horizon:.0f}d horizon ({basis}). "
              f"A source that has stopped updating looks exactly like a quiet "
              f"one in every other log line — check whether it moved.")


def read_dgxx():
    """DGXX's releases, read from its CMS. Same item shape as collect_ir()'s.

    TWO QUERY PARAMETERS ARE LOAD-BEARING, and neither announces itself:

      sort=date:desc  The default order is NOT by date. An unsorted page 1
                      returns a 2025 item first, so taking rows[0] as "newest"
                      would be wrong and would look right. Same trap as
                      document order on the Hut 8 page.
      populate=*      `pdf_file` is absent from the default field set. Without
                      it every item parses fine and has nothing to link to.

    Linking is to the PDF because it is the only per-release URL that EXISTS in
    the payload. There is no slug field (Strapi returns 400 Invalid key slug),
    and reconstructing the web URL as slugify(title)+"-"+documentId resolves
    only 6 of 8 — while digipowerx.com soft-404s, returning HTTP 200 with the
    wrong content, so a wrong link would be indistinguishable from a right one.
    A value that is present beats a rule that mostly works.

    THREE DISTINCT FAILURES, three distinct log lines. DGXX's median gap between
    releases is 8 days, so a silent failure would sit a long time before anyone
    wondered. The hostname is a Strapi Cloud default rather than a contract on
    the company's own domain, and a redeploy would move it without warning.

    Never raises. Twelve feeds, a scraper and the EDGAR sweep must not go down
    with one vendor hostname.
    """
    headers = dict(IR_HEADERS, Accept="application/json")
    params = {"sort": "date:desc", "populate": "*",
              "pagination[pageSize]": "25"}
    try:
        r = requests.get(DGXX_API, params=params, headers=headers,
                         timeout=(10, 30))
    except requests.RequestException as e:
        # State 1: did not resolve. This is what a Strapi Cloud redeploy looks
        # like — the hostname simply stops existing.
        print(f"  DGXX: FETCH FAILED ({type(e).__name__}) — the CMS host did "
              f"not respond. If this persists, the vendor hostname has moved; "
              f"it is not a contract on digipowerx.com.")
        return []
    if r.status_code != 200:
        print(f"  DGXX: HTTP {r.status_code} from the CMS API")
        return []
    try:
        rows = (r.json() or {}).get("data") or []
    except ValueError:
        print("  DGXX: non-JSON response from the CMS API")
        return []

    if not rows:
        # State 2: answered, but with nothing. Not a quiet month — this endpoint
        # serves the whole history, 197 items reaching back to 2020.
        print("  DGXX: EMPTY RESPONSE — HTTP 200 with 0 items. This endpoint "
              "serves the full history, so zero means the schema or the "
              "collection moved, not that nothing was published.")
        return []

    items, no_pdf = [], 0
    for row in rows:
        # Strapi v4 nests under "attributes"; v5 is flat. Handle both.
        a = row.get("attributes") if isinstance(row.get("attributes"), dict) else row
        title = str(a.get("title") or "").strip()
        if not title:
            continue
        doc = str(row.get("documentId") or a.get("documentId") or "")

        pdf = a.get("pdf_file") or row.get("pdf_file")
        link = pdf.get("url") if isinstance(pdf, dict) else None
        if not link:
            no_pdf += 1
            link = DGXX_PAGE          # nothing per-release to point at

        published = 0
        when = str(a.get("date") or "")[:10]
        if when:
            try:
                published = timegm(time.strptime(when, "%Y-%m-%d"))
            except ValueError:
                pass

        items.append({
            "uid": f"dgxx:{doc}" if doc else link,
            # The label says PDF because the link is one. Every other item in
            # the channel opens a web page; a reader should know before
            # clicking, not after.
            "source": "DGXX · IR newsroom (PDF)",
            "title": html.unescape(title),
            "link": link,
            "published": published,
            "is_edgar": False,
        })

    if no_pdf:
        # Not fatal, but it is how "populate=* stopped working" would surface.
        print(f"  DGXX: {no_pdf} of {len(items)} item(s) carried no pdf_file "
              f"and fall back to the newsroom index. If this is all of them, "
              f"check that populate=* is still honoured.")

    items.sort(key=lambda i: i["published"], reverse=True)
    print(f"  DGXX: {len(items)} items (CMS API)")
    # State 3 — the failure that caught both the dead GlobeNewswire feed and the
    # abandoned sitemap — is now the shared check, with DGXX's measured horizon
    # as a floor because it rests on more history than this window shows.
    check_staleness("DGXX", [i["published"] for i in items],
                    override_days=DGXX_STALE_DAYS)
    return items


def collect_ir():
    items = []
    for label, url in IR_FEEDS.items():
        print(f"  {label}...")
        entries = parse_feed(url)
        source_url = url

        if not entries:
            # Not a feed, or a dead URL. Try to find the real feed on the page.
            found = discover_feed(url)
            if found and found != url:
                entries = parse_feed(found)
                if entries:
                    source_url = found
                    print(f"  {label}: discovered feed at {found}")

        if not entries:
            print(f"  {label}: NO FEED — needs a scraper or manual URL")
            continue

        print(f"  {label}: {len(entries)} items")
        check_staleness(label, [entry_time(e) for e in entries])
        for entry in entries:
            items.append({
                "uid": entry.get("id") or entry.get("link"),
                "source": f"{label} · IR newsroom",
                "title": entry.get("title", "Untitled"),
                "link": entry.get("link", ""),
                "published": entry_time(entry),
                "is_edgar": False,
            })

    # Two companies publish no feed at all and are covered another way, both
    # yielding the same item shape so nothing downstream knows the difference.
    items += scrape_hut8()   # server-side HTML, scraped
    items += read_dgxx()     # public CMS, read as JSON
    return items


def entry_time(entry):
    """Best-effort UTC timestamp for a feed entry. 0 if unavailable."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return timegm(value)
            except (TypeError, ValueError):
                continue
    return 0


def entry_form(entry, fallback=""):
    """The form type EDGAR labels this entry with, e.g. '4' or '8-K'."""
    for tag in entry.get("tags") or []:
        term = tag.get("term")
        if term:
            return term.strip()
    return fallback


def passes_keywords(item):
    if not KEYWORDS:
        return True
    haystack = item["title"].lower()
    return any(k.lower() in haystack for k in KEYWORDS)


def post(item, webhook, color=0x1F6FEB):
    """Post one item to a webhook. Payload shape inferred from the host."""
    if "discord.com" in webhook or "discordapp.com" in webhook:
        payload = {
            "embeds": [{
                "title": item["title"][:250],
                "url": item["link"],
                "footer": {"text": item["source"]},
                "color": color,
            }]
        }
    else:  # Slack incoming webhook
        payload = {
            "text": f"*{item['source']}*\n<{item['link']}|{item['title']}>"
        }
    for attempt in range(2):
        try:
            r = requests.post(webhook, json=payload, timeout=20)
        except requests.RequestException as e:
            print(f"  webhook failed: {e}", file=sys.stderr)
            return False

        if r.status_code == 429:
            # Discord tells us how long to wait. Honour it rather than dropping
            # the item — a burst during earnings season is exactly when this
            # fires, and a dropped item would never be retried.
            wait = 5.0
            try:
                wait = float(r.json().get("retry_after", 5))
            except (ValueError, AttributeError, TypeError):
                pass
            wait = min(wait + 0.5, 30.0)
            if attempt == 0:
                print(f"  rate limited, waiting {wait:.1f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print("  still rate limited; will retry next run", file=sys.stderr)
            return False

        if r.status_code >= 300:
            print(f"  webhook returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            return False

        time.sleep(1.0)  # stay inside Discord's per-webhook burst limit
        return True
    return False


def main():
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL is not set.")
    if not SEC_USER_AGENT:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

    state = load_state()
    seen = set(state["seen"])
    # Older state may hold ids in a different shape. Index by accession number
    # so a change of data source can't make every historical filing look new.
    seen_accessions = {u.rsplit("accession-number=", 1)[-1]
                       for u in state["seen"] if "accession-number=" in u}

    resolved = {}
    if TICKERS:
        print(f"Resolving {len(TICKERS)} tickers...")
        resolved = resolve_ciks(TICKERS)
    for label, (cik, name) in EXTRA_CIKS.items():
        resolved[label] = (cik.zfill(10), name)
        print(f"  {label}: pinned to CIK {cik.zfill(10)} ({name})")
    print(f"Checking EDGAR for {len(resolved)} companies...")
    items, edgar_insider = collect_all(resolved)
    print(f"Checking {len(IR_FEEDS)} IR feeds...")
    items += collect_ir()

    insider_items = []
    if INSIDER_WEBHOOK_URL:
        insider_items = edgar_insider
        print(f"Insider channel: {len(insider_items)} Form 4 filing(s).")
    else:
        print("WEBHOOK_URL_INSIDER not set — skipping insider channel.")

    all_items = items + insider_items
    def is_new(i):
        if not i["uid"] or i["uid"] in seen:
            return False
        return i.get("accession") not in seen_accessions

    fresh = [i for i in items if is_new(i)]
    insider_fresh = [i for i in insider_items if is_new(i)]
    print(f"{len(all_items)} items seen, {len(fresh)} new, "
          f"{len(insider_fresh)} new insider.")

    # First run: record everything, post nothing. Avoids a wall of backlog.
    if not state.get("initialized"):
        state["seen"] = [i["uid"] for i in all_items if i["uid"]]
        state["initialized"] = True
        if DRY_RUN:
            print(f"First run: would baseline {len(state['seen'])} id(s). "
                  f"State not saved.")
            return
        save_state(state, len(all_items))
        print("First run complete — baseline recorded, nothing posted.")
        return

    # Mark everything fresh as seen up front. Items we don't post this run are
    # still recorded, so a big backlog can't re-flood on the next run.
    for item in fresh + insider_fresh:
        seen.add(item["uid"])
        state["seen"].append(item["uid"])

    # Age floor first: old filings are already marked seen, and are dropped
    # here regardless of how many there are.
    cutoff = time.time() - MAX_AGE_DAYS * 86400

    def recent(items):
        return [i for i in items if (i.get("published") or 0) >= cutoff]

    fresh_recent = recent(fresh)
    insider_recent = recent(insider_fresh)
    aged = (len(fresh) - len(fresh_recent)) + (len(insider_fresh) - len(insider_recent))
    if aged:
        print(f"{aged} item(s) older than {MAX_AGE_DAYS}d — recorded, not posted.")

    candidates = [i for i in fresh_recent if passes_keywords(i)]
    candidates.sort(key=lambda i: i.get("published") or 0, reverse=True)
    candidates = candidates[: MAX_POSTS_PER_RUN * 2]

    to_post = []
    for item in candidates:
        if len(to_post) >= MAX_POSTS_PER_RUN:
            break
        # BEFORE the exhibit filter, not inside it. These filings usually
        # arrive without a press release, so running them through
        # carries_press_release() first would defeat the whole change.
        if always_post_items(item):
            item["unannounced"] = True
        elif PRESS_RELEASE_EXHIBIT_ONLY and item.get("form") in EXHIBIT_CHECK_FORMS:
            if not carries_press_release(item["form"], item.get("items", "")):
                continue
        to_post.append(item)

    n_unannounced = sum(1 for i in to_post if i.get("unannounced"))
    print(f"{len(candidates)} candidate(s) checked, {len(to_post)} to post"
          + (f" ({n_unannounced} unannounced material filing(s))"
             if n_unannounced else "") + ".")

    if DRY_RUN:
        for item in to_post:
            tag = "unannounced" if item.get("unannounced") else "press"
            print(f"  [{tag:<11}] {item['source']} — {item['title'][:60]}")
        for item in sorted(insider_recent,
                           key=lambda i: i.get("published") or 0,
                           reverse=True)[:MAX_INSIDER_POSTS_PER_RUN]:
            print(f"  [insider] {item['source']} — {item['title'][:60]}")
        n_ins = min(len(insider_recent), MAX_INSIDER_POSTS_PER_RUN)
        print(f"\nDry run: would post {len(to_post)} press "
              f"and {n_ins} insider item(s). State not saved.")
        return
    failed = []
    sent = 0
    for item in to_post:
        colour = UNANNOUNCED_COLOR if item.get("unannounced") else 0x1F6FEB
        if post(item, WEBHOOK_URL, color=colour):
            sent += 1
        else:
            failed.append(item["uid"])
    print(f"Posted {sent} press item(s).")

    # Insider channel: no exhibit check, separate cap, separate webhook.
    if insider_recent:
        insider_recent.sort(key=lambda i: i.get("published") or 0, reverse=True)
        batch = insider_recent[:MAX_INSIDER_POSTS_PER_RUN]
        sent_i = 0
        for item in batch:
            if post(item, INSIDER_WEBHOOK_URL, color=0xD29922):
                sent_i += 1
            else:
                failed.append(item["uid"])
        print(f"Posted {sent_i} insider item(s).")

    # Un-mark anything that failed to post so the next run tries again.
    # Without this, a rate-limited item is lost permanently.
    if failed:
        lost = set(failed)
        state["seen"] = [u for u in state["seen"] if u not in lost]
        print(f"{len(lost)} item(s) failed to post; will retry next run.")

    save_state(state, len(all_items))


if __name__ == "__main__":
    main()
