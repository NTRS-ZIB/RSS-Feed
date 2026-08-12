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
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests

import watchlist
import earnings_dates as ed
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
# Five different ways, because six companies publish no feed on their own
# newsroom, and each turned out to be a different problem:
#
#   own IR feed          ten companies, IR_FEEDS
#   newswire feed        BGDE — GlobeNewswire's organization feed
#   separate IR host     WYFI — whitefiber.investorroom.com, found by
#                        autodiscovery OUT of a Webflow shell that has no
#                        headlines in it
#   scrape               HUT and GLXY — server-side HTML, scrape_hut8()
#                        and scrape_galaxy(). GLXY ALSO has a feed, on its IR
#                        host; it is the only company read two ways, and the
#                        overlap is deduped by suppress_cross_host()
#   CMS API              DGXX — public Strapi, read_dgxx()
#                        ABTC — public Sanity, read_abtc()
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

# GLXY is the same case as HUT and was established the same way: no feed
# anywhere — autodiscovery, footer anchors, every platform path on this roster
# and the host roots were all tried on 2026-08-08 — and a newsroom that comes
# back complete in a plain fetch. Scraped, see scrape_galaxy().
GLXY_PAGE = "https://www.galaxy.com/newsroom"

# DGXX publishes no feed anywhere — not on its own domain, and not on either
# wire it has used. Its newsroom is a Next.js shell backed by a PUBLIC Strapi
# CMS, which is read directly. A JSON contract, so more stable than the HUT
# scrape, but on infrastructure with a weaker guarantee: see read_dgxx().
DGXX_API = ("https://thankful-miracle-1ed8bdfdaf.strapiapp.com"
            "/api/press-releases")
DGXX_PAGE = "https://www.digipowerx.com/press-releases"

# ABTC publishes no feed either, and is NOT the HUT shape: abtc.com/news is a
# client-rendered infinite scroll. Its first page IS delivered in the HTML, but
# with no date-adjacent-to-title structure, so a cheap scrape does not apply —
# 28 release slugs against 3 loose dates in the markup, which is guesswork
# rather than a hard parse. The list is backed by a PUBLIC SANITY DATASET,
# which is read directly. Same shape as DGXX, same vendor-host caveat: see
# read_abtc().
ABTC_API = ("https://6zk22fw5.apicdn.sanity.io/v2024-01-01"
            "/data/query/production")
ABTC_PAGE = "https://www.abtc.com/news"
ABTC_RELEASE = "https://www.abtc.com/news-and-insights/{slug}"
# 22 pressRelease documents on 2026-08-08. The floor is the failure treatment,
# not a statistic — see read_abtc().
ABTC_FLOOR = 5

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
    #
    # A SECOND COMPONENT ALSO READS THESE, and it is not a duplicate to be
    # removed. holder_events.py parses the structured XML behind every 13D/G
    # and posts arrivals, position changes and declared exits to the INSIDER
    # channel. This component announces that a filing exists; that one reads
    # it. Same source, different question — the relationship regsho_volume.py
    # and short_interest.py already have.
    #
    # Removing either leaves a real gap: without this the filing is not
    # announced at all, and without that the reader learns a 13D was filed and
    # not who crossed what.
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
# ITS JOB CHANGED ON 2026-08-09 AND THE VALUE DID NOT. It used to be the only
# thing standing between a roster addition and a wall of backdated posts;
# baseline_companies() now does that completely and by company, so the floor
# no longer has anything to do with adding a ticker.
#
# What it still does is narrower and is NOT the outage case. A SOURCE THAT
# CHANGES WHAT IT SERVES is the demonstrated risk: read_dgxx() asks for 25 of
# the 197 releases its CMS holds, and a pageSize or default that moved would
# make every one of the other 172 unseen, old, and eligible. The floor records
# them silently instead. Feeds do this too — BGDE's serves 20 where most serve
# 10.
#
# The cost is real and is worth stating rather than leaving implicit: an
# outage longer than seven days would drop everything older than the window,
# silently. That has never happened — it needs seven days of silence against a
# measured maximum gap of about five hours — and it is visible from the run
# history in a way a suppressed post is not. Kept on that trade, not because
# it was already here.
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
# Operational notices only, never market content. The same channel
# failure-notice.yml posts to, and for the reason stated there: infrastructure
# noise in a market channel degrades the thing that makes it worth reading.
OPS_WEBHOOK_URL = os.environ.get("WEBHOOK_URL_OPS", "").strip()
# Dry run: fetch, evaluate, print what WOULD post — but post nothing and,
# critically, do NOT save state. Saving would mark everything seen and the
# next real run would then post nothing at all.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
# SEC requires a descriptive User-Agent with a contact address.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

# Several IR platforms sit behind WAFs that stall non-browser User-Agents
# instead of returning an error, so this is the right default for most hosts.
# IT IS NOT A GENERAL RULE: GlobeNewswire does exactly the reverse and stalls
# this header set instead. See HOST_HEADERS above, and never assume a browser
# UA is the safe choice for a new source without measuring it.
IR_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# A BROWSER-LIKE USER-AGENT IS A PER-HOST BET, NOT A SAFE DEFAULT, AND LOSING
# THE BET LOOKS LIKE AN OUTAGE RATHER THAN A REJECTION.
#
# GlobeNewswire stalls a browser-claiming request from this runner and answers
# a plain one in a tenth of a second. Measured 2026-08-11 against both the org
# feed and an ordinary release page, two URLs per case so the result could not
# be read as being about feeds:
#
#   Chrome/126 (what IR_AGENT sends)     ReadTimeout after 15s
#   Chrome/140, browser Accept           ReadTimeout after 15s
#   Firefox/131, browser Accept          ReadTimeout after 15s
#   Feedly's UA                          ReadTimeout after 15s
#   python-requests, curl, no UA at all  200 in 0.0-0.1s, 20 entries
#   an identifying UA naming this tool   200 in 0.0s, 20 entries
#
# The reading is that a browser UA arriving from a datacenter IP with no
# matching fingerprint scores worse than an honest non-browser client. BGDE's
# feed was never dead: it served 20 entries throughout, to anyone not claiming
# to be Chrome. It cost 22 hours of silent outage and five probe dispatches to
# establish, because a stall is indistinguishable from a dead host.
#
# The identifying UA is chosen over curl or an absent header even though all
# three work: it is what a host operator sees in their logs, and this repo
# already identifies itself by name to the SEC for the same reason.
GNW_HEADERS = {
    "User-Agent": "InfraMonitor/1.0 (press release monitor; "
                  "contact via github.com/NTRS-ZIB/RSS-Feed)",
    "Accept": "*/*",
}

# One entry, because this is a bet per host and not a policy. Anything not
# listed gets IR_HEADERS below, which several IR platforms genuinely require.
HOST_HEADERS = {
    "www.globenewswire.com": GNW_HEADERS,
}

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
    # The time EDGAR took the filing, alongside the date it is credited to.
    # Both are carried because they answer different questions: see the
    # horizon note in collect_all() for why the two are not interchangeable.
    accepted = recent.get("acceptanceDateTime") or []

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
            "accepted": accepted[i] if i < len(accepted) else "",
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


def filed_time(datestr, accepted=None):
    """When a filing became visible, as an epoch second.

    `acceptanceDateTime` is when EDGAR took the filing. `filingDate` is a DATE
    ONLY, so parsing it alone puts publication at 00:00 UTC and charges the
    item for every hour of the day it was actually filed in. Measured across
    the 122 in-window filings on this roster, that discards a MEAN OF 17.7
    HOURS and a median of 20.1, which is 10.5% of the MAX_AGE_DAYS window, and
    nothing gains less than six hours.

    The reason it is so large is the same fact the schedule is built around:
    48% of filings land between 20:00 and 23:00 UTC. A midnight reading throws
    away almost the whole filing day for half the roster. See
    docs/press-monitor.md.

    ACCEPTANCE CAN SIT MORE THAN 24 HOURS AFTER THAT MIDNIGHT, and that is
    correct rather than a parsing fault. SEC assigns the previous business
    day's `filingDate` to a filing accepted after its cutoff, so an item filed
    late on the 29th can carry `filingDate` 2026-07-29 and acceptance
    2026-07-30T01:42Z. Using acceptance simply dates it when it happened; the
    age is still measured backwards from now, so nothing goes negative and
    nothing reads as filed in the future.

    THE FALLBACK IS DEFENSIVE AND UNDEMONSTRATED. `acceptanceDateTime` was
    present on 10,201 of 10,201 filings across all 19 companies, at every form
    type and every age, so no case has ever exercised the midnight path. It is
    kept because a field observed everywhere is not a field the API guarantees,
    and the alternative to a fallback is an exception rather than a slightly
    worse timestamp. Do not read it as handling a known condition.
    """
    if accepted:
        try:
            # Ends in Z and is UTC. See the trap table in CLAUDE.md: this field
            # is NOT Eastern, and the two confirmations that once said it was
            # were both artefacts of reading the web index instead.
            stamp = accepted.replace("Z", "+00:00")
            dt = datetime.fromisoformat(stamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            pass                      # fall through to the date
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
            # DELIBERATELY THE DATE, not the acceptance time. This is a date
            # comparison against a date horizon and does not want a clock: it
            # decides which filings are worth collecting at all, and a filing
            # credited to a date inside the window belongs in the window
            # whatever hour it was taken. The AGE FLOOR is the thing that
            # needs the real time, and it gets it through filed_time().
            #
            # Making these two consistent is the obvious tidy-up and it would
            # be wrong. It would move a boundary that is correct where it is,
            # and shift RETAIN_DAYS by up to a day for no gain.
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
                "published": filed_time(f["filed"], f.get("accepted")),
                "is_edgar": True,
                # Explicit rather than parsed back out of `source`, because
                # baseline_companies() keys on it and a display string is not
                # an identifier.
                "ticker": ticker,
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


def headers_for(url):
    """The header set this host wants. IR_HEADERS unless it is in HOST_HEADERS.

    Only the two feed-fetching paths consult this. `scrape_hut8()`,
    `scrape_galaxy()`, `read_abtc()` and `read_dgxx()` still pass IR_HEADERS
    directly — correct today because none of their hosts is in the table, and
    the thing to change if one ever joins it.
    """
    return HOST_HEADERS.get(urlparse(url).netloc.lower(), IR_HEADERS)


def discover_feed(page_url):
    """Find a feed URL from a page's <link rel="alternate"> tags."""
    try:
        r = requests.get(page_url, headers=headers_for(page_url),
                         timeout=(10, 30))
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


# Read timeout per attempt, in seconds. The retry is deliberately generous:
# A HOST THAT IS MERELY SLOW AND ONE THAT IS HANGING ARE INDISTINGUISHABLE AT
# A SINGLE TIMEOUT, and which one it is decides whether a dead feed needs a
# replacement source or just patience.
#
# IT WAS ADDED FOR BGDE AND THAT IS NOT WHAT WAS WRONG WITH BGDE. Its
# GlobeNewswire feed began timing out at 2026-08-10T16:06Z after reading 20
# items cleanly at 15:05; 90s failed exactly as 30s had, which ruled out
# slowness, and the actual cause was the WAF stalling our browser User-Agent.
# See HOST_HEADERS. Ruling slowness out in one run is a real result and is
# why this stays, but nothing here fixed that outage and a later reader
# should not infer that it did.
#
# What it is kept for is the next host that is genuinely slow rather than
# blocked, which this one turned out not to be. Cost is bounded and worth
# checking against the step's 780s budget: a feed failing both attempts takes
# 10+30 + 2 + 10+90 = 142s rather than 82s. One hanging feed is affordable;
# this is not a licence to add a third attempt.
READ_TIMEOUTS = (30, 90)


def parse_feed(url):
    """Fetch and parse a feed. Never blocks indefinitely. Retries once, with
    a longer read timeout on the retry."""
    r = None
    for attempt, read_timeout in enumerate(READ_TIMEOUTS):
        started = time.time()
        try:
            r = requests.get(url, headers=headers_for(url),
                             timeout=(10, read_timeout))
            if attempt:
                print(f"    recovered on the {read_timeout}s retry, "
                      f"{time.time() - started:.0f}s to first byte")
            break
        except requests.RequestException as e:
            waited = time.time() - started
            if attempt + 1 < len(READ_TIMEOUTS):
                print(f"    {type(e).__name__} after {waited:.0f}s at a "
                      f"{read_timeout}s read timeout, retrying once")
                time.sleep(2)
            else:
                print(f"    fetch failed: {type(e).__name__} after "
                      f"{waited:.0f}s at a {read_timeout}s read timeout")
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
            "ticker": "HUT",
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


def scrape_galaxy():
    """GLXY's newsroom posts, scraped. Items shaped like collect_ir()'s.

    Same case as HUT and the same failure treatment: HTTP 200 with zero items
    is a parse failure, not a quiet week. This page carries roughly six
    historical announcements and never empties, so zero can only mean the
    markup moved.

    THE MARKUP, read off the delivered HTML rather than guessed. Each card is

        <li class="post-list2__item grid__item newsroom-announcements newsroom">
          <a class="card2__link" href="/newsroom/<slug>">
            <figure><picture> ~1,500 chars of srcset </picture></figure>
            <p class="card2__eyebrow">August 07, 2026</p>
            <h3 class="card2__title">Galaxy and Sharplink Launch ...</h3></a>

    That image block is why this walks forward from the anchor rather than
    pairing a date to a nearby title: both regex directions fail at any window
    small enough to be safe, and any window large enough to span the picture
    reaches into the next card.

    DOCUMENT ORDER IS NOT DATE ORDER ON THIS PAGE, and that is observed rather
    than defended against in the abstract. In the 2026-08-08 fetch a
    January 15, 2026 card sat at byte 93,171 and an August 07, 2026 card at
    99,430 — the older one FIRST. rows[0] happened to be a newest item that
    day by luck. The sort is what makes it true on purpose.

    THE <li> CLASS IS THE FILTER, and an earlier version of this comment said
    the opposite. It claimed nothing in the markup separated Galaxy's own
    releases from third-party write-ups, which is FALSE and was load-bearing
    for the filter below. The class list does it cleanly, measured over the
    276-card archive on 2026-08-08:

        newsroom-announcements   200 cards, 200 dated,   0 off-domain
        newsroom-media            19 cards,  19 dated,  19 off-domain
        newsroom-our-stories      38 cards,  38 dated,   0 off-domain
        newsroom-video            18 cards,  18 dated,   0 off-domain
        research                   1 card

    The mistake was reading `data-newsroom-media-type` and never looking at the
    class two attributes to its left.

    WHAT THE CLASS ACTUALLY MEANS IS NOT WHAT IT LOOKS LIKE, and this is the
    part to keep. `newsroom-announcements` is a reliable ON-DOMAIN CORPORATE
    POST filter and NOT a reliable "company announcement" filter. Galaxy files
    its own IR releases under `newsroom-media`, because they are hosted on
    investor.galaxy.com — so the ERCOT 830 MW Helios approval, a genuine
    company announcement and one of the most relevant items on the roster,
    sits in the media bucket beside third-party write-ups.

    **That exclusion is only harmless because investor.galaxy.com has its own
    feed**, found on 2026-08-08, which carries those releases directly. If that
    feed is ever removed this filter silently stops covering GLXY's material
    announcements, and nothing here would say so.

    Selecting on the class rather than on a `/newsroom/<slug>` path match is
    deliberate — the class survives a change to the slug scheme. **The two are
    NOT equivalent, and the difference was a scope change rather than a
    refactor.** The path match also caught `newsroom-our-stories`, which lives
    under the same path, and swapping to the class took the run from 7 items
    to 4.

    **`newsroom-our-stories` IS EXCLUDED ON PURPOSE.** It is editorial — CEO
    letters, "Written in Code: This code is building rails for the world's
    banks" — and this is a press-release channel, so company announcements
    only. Approved 2026-08-09.

    That is written down because the class filter now does it silently, and
    the narrowing looks exactly like a side effect of the selector. It is not.
    **GLXY is the only company on this roster whose newsroom separates
    announcements from editorial in markup**, so the decision exists here and
    nowhere else, and there is no precedent elsewhere in the repo to point at
    or to argue from.

    Never raises. One scraper must not take down fifteen feeds and the EDGAR
    sweep with it.
    """
    try:
        r = requests.get(GLXY_PAGE, headers=IR_HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"  GLXY: fetch failed: {type(e).__name__}")
        return []
    if r.status_code != 200:
        print(f"  GLXY: HTTP {r.status_code}")
        return []

    items, seen, skipped = [], set(), Counter()
    for cls, body in re.findall(
            r'(?is)<li[^>]*class="([^"]*post-list2__item[^"]*)"[^>]*>'
            r'(.*?)</li>', r.text):

        def part(name):
            g = re.search(rf'class="card2__{name}"[^>]*>(.*?)</', body, re.S)
            if not g:
                return None
            return re.sub(r"\s+", " ",
                          re.sub(r"<[^>]+>", " ", g.group(1))).strip()

        title = part("title")
        if not title:
            continue
        if "newsroom-announcements" not in cls:
            kind = next((k for k in ("newsroom-media", "newsroom-our-stories",
                                     "newsroom-video", "research")
                         if k in cls), "other")
            skipped[kind] += 1
            continue

        href = re.search(r'href="([^"]+)"', body)
        if not href:
            skipped["no href"] += 1
            continue
        link = urljoin(GLXY_PAGE, href.group(1))
        if link in seen:
            continue
        seen.add(link)

        # The eyebrow carries an optional category span before the date, so the
        # date is extracted from the text rather than being the whole of it.
        published = 0
        d = re.search(r"(?:January|February|March|April|May|June|July|August|"
                      r"September|October|November|December)\s+\d{1,2},\s+"
                      r"\d{4}", part("eyebrow") or "")
        if d:
            try:
                published = timegm(time.strptime(d.group(0), "%B %d, %Y"))
            except ValueError:
                pass
        items.append({
            "uid": link,
            "ticker": "GLXY",
            "source": "GLXY \u00b7 IR newsroom",
            "title": html.unescape(title),
            "link": link,
            "published": published,
            "is_edgar": False,
        })

    if not items:
        print(f"  GLXY: PARSE FAILURE \u2014 HTTP 200 but 0 announcements from "
              f"{sum(skipped.values())} other cards. This page lists ~6 "
              f"historical announcements and never empties, so this is the "
              f"markup moving, not a quiet week.")
        return []

    # Observed, not defensive: see the docstring. An older card really does
    # come first in this page's markup.
    items.sort(key=lambda i: i["published"], reverse=True)
    print(f"  GLXY: {len(items)} items (scraped); skipped "
          + ", ".join(f"{v} {k}" for k, v in sorted(skipped.items())))
    check_staleness("GLXY", [i["published"] for i in items])
    return items


def read_abtc():
    """ABTC's releases, read from its Sanity dataset. collect_ir()'s shape.

    THE DATE FIELD IS `date`, NOT `_createdAt`, AND THAT IS NOT A STYLE CHOICE.
    Sanity stamps `_createdAt` and `_updatedAt` mechanically; `date` is the
    editorial publication date the site displays. One document observed on
    2026-08-08 settles it:

        _createdAt  2026-06-03T23:36:38Z
        _updatedAt  2026-06-26T19:22:03Z
        date        2026-04-22T11:37:00.000Z

    Created in June, edited in June, published in April. **Using `_createdAt`
    would have been six weeks wrong on that release**, and it is the field that
    looks more canonical, so this is exactly the substitution a later reader
    makes while tidying. It is recorded here so that reader has the case rather
    than the preference.

    COMPLETENESS IS ESTABLISHED BY THREE INDEPENDENT COUNTS AGREEING, which is
    worth more than any single check because a paginated endpoint returning a
    page looks identical to a complete one returning everything:

        22 pressRelease  +  6 investorPresentation   = 28   (Sanity)
        28 /news-and-insights/ slugs                        (delivered HTML)
        28 release pages with lastmod                       (sitemap.xml)

    So the dataset is the whole set, not a page of it, and no pagination
    parameter is needed or used.

    THE COUNT FLOOR IS THE FAILURE TREATMENT. Twenty-two documents that never
    empty means a zero-length result can only be a renamed type, a moved
    dataset or a project made private — never a quiet month. That matters
    because ABTC publishes irregularly and a silent zero would otherwise sit
    indefinitely looking like no news. Same reasoning as scrape_hut8(), and
    stronger: this is a count from a JSON contract rather than an assumption
    about page furniture.

    VENDOR HOST, SAME CAVEAT AS DGXX. `6zk22fw5.apicdn.sanity.io` is a hosted
    CMS endpoint, undocumented and belonging to a third party. It is a JSON
    contract, so more stable than a scrape — but ABTC could make the project
    private, rename the type or move the dataset without any idea they had
    broken anything downstream. The three states below get three distinct log
    lines for that reason.

    Never raises. One vendor hostname must not take down fifteen feeds, two
    scrapers and the EDGAR sweep.
    """
    query = ('*[_type == "pressRelease"] | order(date desc) [0...25]'
             '{_id, title, "slug": slug.current, date, _createdAt}')
    headers = dict(IR_HEADERS, Accept="application/json")
    try:
        r = requests.get(ABTC_API, params={"query": query}, headers=headers,
                         timeout=(10, 30))
    except requests.RequestException as e:
        # State 1: did not resolve. What a project deletion or a DNS change
        # looks like from here.
        print(f"  ABTC: FETCH FAILED ({type(e).__name__}) — the Sanity host "
              f"did not respond. If this persists the project has moved or "
              f"been made private; it is not a contract on abtc.com.")
        return []
    if r.status_code != 200:
        # State 2: answered and refused. A project switched to private returns
        # 401/403 here rather than an empty result, so it is separable.
        print(f"  ABTC: HTTP {r.status_code} from the Sanity API — "
              f"{'the dataset is no longer public' if r.status_code in (401, 403) else 'unexpected status'}")
        return []
    try:
        rows = (r.json() or {}).get("result") or []
    except ValueError:
        print("  ABTC: non-JSON response from the Sanity API")
        return []

    if len(rows) < ABTC_FLOOR:
        # State 3: answered with too little. The type held 22 documents when
        # this was written and the archive only grows, so a handful means the
        # type was renamed or the dataset moved — NOT a quiet month.
        print(f"  ABTC: FLOOR BREACHED — {len(rows)} document(s), expected at "
              f"least {ABTC_FLOOR}. This type held 22 and an archive does not "
              f"shrink, so the schema moved rather than the company going "
              f"quiet.")
        return []

    items, no_slug = [], 0
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        slug = str(row.get("slug") or "").strip()
        if slug:
            link = ABTC_RELEASE.format(slug=slug)
        else:
            # Not constructed-and-hoped: the 28 slugs in the delivered HTML are
            # exactly these paths, which is what makes the URL verified rather
            # than derived. With no slug there is nothing per-release to point
            # at, and the list page is the honest fallback.
            no_slug += 1
            link = ABTC_PAGE

        published = 0
        when = str(row.get("date") or "")[:10]
        if when:
            try:
                published = timegm(time.strptime(when, "%Y-%m-%d"))
            except ValueError:
                pass
        items.append({
            # The document id, not the link: a slug can be edited after
            # publication and the id cannot, so a retitled release does not
            # repost.
            "uid": f"abtc:{row.get('_id')}",
            "ticker": "ABTC",
            "source": "ABTC \u00b7 IR newsroom",
            "title": html.unescape(title),
            "link": link,
            "published": published,
            "is_edgar": False,
        })

    if no_slug:
        print(f"  ABTC: {no_slug} item(s) had no slug and link to the list "
              f"page")
    print(f"  ABTC: {len(items)} items (Sanity CMS)")
    check_staleness("ABTC", [i["published"] for i in items])
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
            "ticker": "DGXX",
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


# GLXY is read twice — investor.galaxy.com's feed and www.galaxy.com's
# newsroom — so the same release can arrive under two URLs. Seven days, and
# the window is doing more work than it looks like it is; see
# suppress_cross_host().
CROSS_HOST_DAYS = 7
_TITLE_STOP = re.compile(r"\b(?:a|an|the|and|of|to|for|in|on|with|its|at)\b")


def norm_title(t):
    """Lowercase, punctuation and stopwords out. For EXACT comparison only."""
    t = re.sub(r"&[a-z]+;|&#\d+;", " ", (t or "").lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", _TITLE_STOP.sub(" ", t)).strip()


def suppress_cross_host(feed_items, newsroom_items, label):
    """Drop feed items the newsroom already yielded in THIS run.

    WHAT MAKES THIS SAFE IS THE SCOPE, NOT THE MATCHING. Same run, same
    company, two known sources, exact normalised title, and within
    CROSS_HOST_DAYS. Every one of those narrows the population being compared
    until an accidental match cannot happen — and the bias throughout is to
    post twice rather than to suppress.

    THE REASON NOTHING FUZZY IS USED HERE, measured over 23,771 pairs of
    Galaxy releases on 2026-08-08:

        0.984   "Galaxy Digital Announces First Quarter 2022 Financial Results"
                "Galaxy Digital Announces First Quarter 2021 Financial Results"
        0.951   Third Quarter 2021 against First Quarter 2021

    Two genuinely DIFFERENT releases at 98.4% similarity, and the
    near-collisions cluster in quarterly results — the highest-value items the
    channel carries. **A similarity threshold anywhere below 1.000 suppresses
    Q1 2027 as a duplicate of Q1 2026, silently, once a quarter.** The probe
    that measured this reported "worst true match 1.000 vs closest false pair
    0.984 -> a threshold exists", which was a 0.016 margin in one sample
    presented as a finding. It is not a threshold and nothing here uses one.

    THE DATE WINDOW IS WHAT KILLS THAT HAZARD, and it does so BY CONSTRUCTION
    rather than by tuning: Q1 2021 and Q1 2022 are a year apart, so they can
    never both be inside seven days of each other whatever their titles say.

    ONE THING WAS NOT MEASURED AND SHOULD BE SAID PLAINLY. The false-positive
    rate of EXACT title matching is unknown. The probe excluded pairs with
    identical normalised titles as archive duplicates — an assumption, not a
    check — so a pair of genuinely distinct releases sharing a title would not
    have shown up. **The seven-day window is what makes that moot in
    practice**, because two distinct releases would have to share a title
    within a week. Widening the window reintroduces the hole, and that is the
    reason not to.

    HOW BIG THE OVERLAP ACTUALLY IS: 2 of 10 feed items on the live run of
    2026-08-09, against 4 newsroom items. Six of ten was measured against the
    276-card archive at /all-news/announcements, which is NOT what the scraper
    reads — a number true about an adjacent population, and the third time
    this repo has been caught by one.

    DEGRADES TO POSTING TWICE, NEVER TO SUPPRESSING. If the newsroom produced
    nothing this run — fetch failure, parse failure, markup moved — matching
    against it would be matching against an empty set, so it is SKIPPED
    entirely and every feed item posts. A partial scrape is left to run: it
    can only fail to match, which posts a duplicate, and a duplicate is
    visible where a suppression is not.
    """
    if not newsroom_items:
        print(f"  {label}: cross-host dedupe SKIPPED — the newsroom produced "
              f"0 items, so all {len(feed_items)} feed items post. This is "
              f"not {len(feed_items)} unique releases; it is the newsroom "
              f"being unavailable, and duplicates are expected.")
        return feed_items

    index = {}
    for it in newsroom_items:
        index.setdefault(norm_title(it["title"]), []).append(it["published"])

    kept, dropped = [], []
    for it in feed_items:
        when = it["published"]
        twins = index.get(norm_title(it["title"]), [])
        # A missing timestamp on either side cannot satisfy the window, so it
        # falls through to posting. That is the intended direction.
        near = [p for p in twins if when and p
                and abs(p - when) <= CROSS_HOST_DAYS * 86400]
        (dropped if near else kept).append(it)

    print(f"  {label}: cross-host dedupe kept {len(kept)}, suppressed "
          f"{len(dropped)} already carried by the newsroom "
          f"(of {len(newsroom_items)} newsroom items)")
    for it in dropped:
        print(f"    suppressed: {it['title'][:64]}")
    return kept


def baseline_companies(state, roster, items, today=None):
    """Suppress everything from a company appearing for the first time.

    ADDING A TICKER MUST PRODUCE NO BACKDATED POSTS AT ALL. Filings and press
    releases arrive as they happen and never retroactively. MAX_AGE_DAYS
    almost did that and not quite: an item published six days before a roster
    addition is unseen and inside the window, so it posted. On 2026-08-05 that
    produced a handful of backdated posts alongside the twenty items the age
    floor correctly swallowed.

    THE RECORD IS A DICT IN state.json, `baselined`, AND THE REASON IT IS NOT
    "the company has no ids in `seen`" IS MEASURABLE. `seen` is capped at
    max(1000, items_this_run * 3) and is SATURATED at exactly 1000 today, so
    ids are actively being evicted. Worse, a uid is a bare accession number
    and carries no company, so "does this company have ids in seen" cannot be
    asked of the file at all — only of an intersection with the current run,
    which an eviction would silently empty. A company whose ids had aged out
    would look brand new and its real backlog would be suppressed without a
    word. That is the exact failure this function exists to avoid, arriving
    through the mechanism meant to prevent it.

    IT IS ALSO NOT A NEW FILE. `baselined` lives beside `initialized` because
    it is the same kind of fact — this thing has been baselined — and
    state.json is already committed by the workflow, already has a merge
    driver, and is already never hand-edited. A second artefact would need all
    three built again.

    IT SELF-BACKFILLS, so no dates are hand-written for the eighteen companies
    already running. If the key is ABSENT this is the first run under the rule
    and every roster company is established by definition — they have been
    posting for weeks — so all are recorded and NOTHING is suppressed. Only a
    company missing from a PRESENT dict is new.

    IF state.json IS LOST ENTIRELY, `baselined` is empty and `initialized` is
    false, so the whole-file first-run path fires first and posts nothing.
    Degrades exactly as today rather than into a new behaviour.

    Returns (new_companies, suppressed_items). Mutates `state`.
    """
    today = today or date.today().isoformat()
    known = state.get("baselined")
    if known is None:
        state["baselined"] = {t: today for t in sorted(roster)}
        print(f"Per-company baseline: recording {len(roster)} established "
              f"company/companies. Nothing suppressed — the key was absent, "
              f"so this is the backfill run and every company on the roster "
              f"is already running.")
        return [], []

    new = sorted(t for t in roster if t not in known)
    if not new:
        return [], []

    suppressed = [i for i in items if i.get("ticker") in set(new)]
    for t in new:
        state["baselined"][t] = today
    per = Counter(i.get("ticker") for i in suppressed)
    print(f"FIRST RUN for {', '.join(new)} — everything they have is marked "
          f"seen and NOTHING posts. This is the intended behaviour of adding a "
          f"ticker, not a loss:")
    for t in new:
        print(f"    {t}: {per.get(t, 0)} item(s) suppressed")
    return new, suppressed


# Consecutive failed reads before a feed is called an outage rather than a
# blip. DERIVED, over 57 successful press-monitor runs from 2026-08-04T18:25Z
# to 2026-08-11T14:24Z, roughly a thousand feed-reads across 19 sources:
#
#   every TRANSIENT episode was exactly 1 run — four of them, SLNH once and
#   BGDE three times
#   every REAL episode was 4 runs or 24 — both BGDE, the 24 still open
#
# Nothing in the window landed between. Thresholds of 2, 3 and 4 therefore
# fire on exactly the same two episodes, so the value is insensitive across
# that range and 2 is taken for the earliest detection at no cost in false
# alarms. WHAT IT FIRES AT: 2 notices in 7 days on this roster.
#
# Re-derive it if the roster gains a source that fails differently. A feed
# that flaps in twos would make this cry wolf, and the measurement above is
# the only thing standing behind the number.
FEED_FAIL_ALERT = 2


def report_feed_health(state, feed_ok):
    """Say something out loud when a feed goes dark, once per episode.

    THE OUTAGE THIS EXISTS FOR WAS SILENT. BGDE's feed stopped answering at
    2026-08-10T16:06Z and the workflow went on succeeding, because a feed
    returning nothing is not an error — 22 hours later it was noticed only
    because an expected release never appeared. `failure-notice.yml` cannot
    catch this by construction: it fires on a failed run, and these runs pass.

    Once per episode, not once per run: the open BGDE outage would otherwise
    have posted 24 times and taught the reader to mute the channel, which is
    the failure mode that file's own header warns about.
    """
    health = state.setdefault("feeds", {})
    for label in sorted(feed_ok):
        rec = health.setdefault(label, {"fails": 0, "alerted": False})
        if feed_ok[label]:
            if rec["alerted"]:
                _ops_notice(f"✅ **{label}** feed is answering again after "
                            f"{rec['fails']} consecutive failed reads.")
            rec["fails"], rec["alerted"] = 0, False
            continue
        rec["fails"] += 1
        if rec["fails"] >= FEED_FAIL_ALERT and not rec["alerted"]:
            rec["alerted"] = True
            _ops_notice(f"⚠️ **{label}** feed has returned nothing on "
                        f"{rec['fails']} consecutive runs. Its releases now "
                        f"reach Discord only if an 8-K follows.")

    # ALWAYS, even when everything is healthy. A check that prints only when
    # it fires is indistinguishable from a check that never ran, which is the
    # ambiguity this whole change exists to remove — and it would be absurd to
    # reintroduce it in the fix for it. Silence here would also have hidden
    # that a dry run can never advance the counter, because state is not saved.
    failing = {l: r["fails"] for l, r in health.items() if r["fails"]}
    print(f"  feed health: {len(feed_ok)} feed(s) checked, "
          f"{sum(1 for v in feed_ok.values() if v)} answered"
          + (f", failing: {failing}" if failing else "")
          + (" [dry run: counters are not saved, so they cannot reach "
             f"{FEED_FAIL_ALERT}]" if DRY_RUN else ""))


def _ops_notice(text):
    """Post one line to the ops channel. Never raises, never blocks a run."""
    print(f"  feed health: {text}")
    if DRY_RUN:
        print("  feed health: dry run — not posted.")
        return
    if not OPS_WEBHOOK_URL:
        print("  feed health: WEBHOOK_URL_OPS is not set — not posted.")
        return
    try:
        r = requests.post(OPS_WEBHOOK_URL, json={"content": text}, timeout=15)
        if r.status_code >= 300:
            print(f"  feed health: webhook returned {r.status_code}")
    except requests.RequestException as e:
        print(f"  feed health: webhook failed, {type(e).__name__}")


def collect_ir():
    """(items, feed_ok) — feed_ok maps each configured feed to whether it
    yielded anything this run. Scrapers and CMS reads are not included: they
    fail differently and have not been measured."""
    feed_ok = {}
    items = []
    # The scrapers and CMS readers run FIRST because one feed is deduped
    # against one of them: GLXY is read both from investor.galaxy.com's feed
    # and from www.galaxy.com's newsroom. Nothing else depends on the order.
    scraped = []
    scraped += scrape_hut8()      # server-side HTML, scraped
    glxy_newsroom = scrape_galaxy()
    scraped += glxy_newsroom      # server-side HTML, scraped
    scraped += read_dgxx()        # public Strapi, read as JSON
    scraped += read_abtc()        # public Sanity, read as JSON

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
            feed_ok[label] = False
            continue

        feed_ok[label] = True
        print(f"  {label}: {len(entries)} items")
        check_staleness(label, [entry_time(e) for e in entries])
        batch = [{
            "uid": entry.get("id") or entry.get("link"),
            "ticker": label,
            "source": f"{label} · IR newsroom",
            "title": entry.get("title", "Untitled"),
            "link": entry.get("link", ""),
            "published": entry_time(entry),
            "is_edgar": False,
        } for entry in entries]
        if label == "GLXY":
            batch = suppress_cross_host(batch, glxy_newsroom, label)
        items += batch

    return items + scraped, feed_ok


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


# Used by both probe_body_dates.py and record_disclosed_dates() below. It
# lives here because it needs headers_for(), and the per-host header
# knowledge that function carries is not worth duplicating or splitting —
# see HOST_HEADERS.
BODY_TIMEOUT = (10, 15)
BODY_MAX_BYTES = 400_000


def announcement_body(link):
    """The visible text of a release page, or None. Never raises.

    Streams the response and stops reading once BODY_MAX_BYTES is reached, so
    the cap bounds the download itself — not just how much of an already
    fully-buffered response gets decoded. Without stream=True, requests.get
    reads the whole body before this function ever sees it, and a slice
    afterwards would be a cap on decoding, not on the fetch.
    """
    if not link:
        return None
    try:
        r = requests.get(link, headers=headers_for(link), timeout=BODY_TIMEOUT,
                         stream=True)
    except requests.RequestException as e:
        print(f"    body fetch failed: {type(e).__name__} for {link[:70]}")
        return None
    try:
        if r.status_code != 200:
            print(f"    body fetch HTTP {r.status_code} for {link[:70]}")
            return None
        raw = bytearray()
        try:
            for chunk in r.iter_content(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) >= BODY_MAX_BYTES:
                    break
        except requests.RequestException as e:
            print(f"    body fetch failed mid-read: {type(e).__name__} for "
                  f"{link[:70]}")
            return None
    finally:
        r.close()
    html = bytes(raw[:BODY_MAX_BYTES]).decode("utf-8", "replace")
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def record_disclosed_dates(items, fresh_uids):
    """Extract announced reporting dates from item titles and store them.

    Runs over EVERY item, not only the ones that will post. An announcement
    dropped by the age floor or by MAX_POSTS_PER_RUN is still a valid date,
    and the calendar has no other way to learn it.

    `fresh_uids` gates the BODY FETCH only, never the title path. Over every
    item it would re-fetch the same dozen pages on each pass, about eight
    times an hour, indefinitely, for an answer that does not change. That
    gate is also why the body measurement this rule is built on never
    sampled anything from here: the announcements were all old. Backfilling
    is probe_body_dates.py's job, and this is not that.
    """
    today = datetime.now(timezone.utc).date()
    companies, status = ed.load()
    if status == "unreadable":
        # An unreadable store is a SOURCE FAILURE, not a blank slate. Saving
        # now would overwrite it with only what this run's feeds yielded,
        # destroying records for any company whose announcement has since
        # scrolled out of the feed window — see the CRITICAL note above
        # save_state() for the same principle applied to state.json. Skip the
        # write entirely and leave the file exactly as it is; nothing here
        # recovers a corrupt file, and nothing here should make it worse.
        print("  earnings dates: existing file is unreadable — SKIPPING the "
              "write this run so it is not overwritten with a partial "
              "rebuild. Dates were not recorded this run; "
              "earnings_dates.json is left untouched.")
        return
    elif status == "missing":
        print("  earnings dates: no file yet — this run creates it.")

    counts = {"ok": 0, "no-date": 0, "past": 0, "no-match": 0}
    body = {"eligible": 0, "fetched": 0, "failed": 0,
            "ok": 0, "several": 0, "no-candidates": 0, "past": 0,
            "no-baseline": 0}
    no_date_examples = []
    for item in items:
        entry = EXTRA_CIKS.get(item.get("ticker") or "")
        if not entry:
            continue
        body_hit = False
        published = item.get("published")
        released = (datetime.fromtimestamp(published, timezone.utc).date()
                    if published else None)
        when, reason = ed.extract(item.get("title"), today, released)
        counts[reason] += 1
        if reason == "no-date":
            if len(no_date_examples) < 3:
                # The informative miss: an announcement whose date is in the
                # body rather than the title. probe_body_dates.py measures
                # this population in full; this is the sample in the log.
                no_date_examples.append(
                    f"{item['ticker']}: {item.get('title')!r}")
            # A title naming a forthcoming event is the only population the
            # rule was measured over. A results release is dense with dates
            # and was never in scope.
            if ed.names_a_scheduled_event(item.get("title")):
                body["eligible"] += 1
                if item.get("uid") in fresh_uids:
                    text = announcement_body(item.get("link"))
                    if text is None:
                        body["failed"] += 1
                    else:
                        body["fetched"] += 1
                        found, why = ed.date_from_body(text, released, today)
                        body[why] += 1
                        if found is not None:
                            when, reason = found, "ok"
                            body_hit = True
        if when is None:
            continue
        iso = (datetime.fromtimestamp(published, timezone.utc).isoformat()
               if published else None)
        source = "body" if body_hit else "title"
        if ed.upsert(companies, entry[0], item["ticker"], when,
                     item.get("uid"), item.get("title"), iso, source=source):
            print(f"  earnings dates: {item['ticker']} -> {when} "
                  f"({source}) from {item.get('title')!r}")

    print(f"  earnings dates: {counts['ok']} recorded from titles, "
          f"{counts['no-date']} announcement(s) with no parsable date, "
          f"{counts['past']} rejected as past, {len(companies)} on file.")
    if no_date_examples:
        print("  earnings dates: no-date example(s): "
              + "; ".join(no_date_examples))
    # A RUN THAT STORES NOTHING IS NOT EVIDENCE THE RULE WORKS. The previous
    # body measurement logged "Bodies fetched 0" for months and read as
    # working. `eligible` is the number that separates "no candidate item
    # this run" from "fetched and found nothing", so it is printed even when
    # every other number is zero.
    print(f"  earnings dates: body rule — {body['eligible']} in scope "
          f"({body['fetched']} new enough to fetch), {body['failed']} fetch "
          f"failed; {body['ok']} stored, {body['several']} had several "
          f"dates, {body['no-candidates']} had none, {body['past']} were "
          f"past, {body['no-baseline']} had no release date to check "
          f"against.")
    if DRY_RUN:
        print("  earnings dates: dry run — nothing written.")
        return
    ed.save(companies)


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
    ir_items, feed_ok = collect_ir()
    items += ir_items

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

    # After the first-run return: a baseline run has no history to judge a
    # feed against, and calling every feed healthy or broken on that run
    # would either mute a real outage or invent one.
    report_feed_health(state, feed_ok)

    # This must never be able to cost a press post. record_disclosed_dates()
    # touches a second file that has nothing to do with whether an item
    # posts, and it runs before the posting loop below — an unhandled
    # exception here (an ed.save() OSError, an unexpected item shape) would
    # abort main() and silence the whole channel for a failure that has
    # nothing to do with press items.
    try:
        record_disclosed_dates(all_items,
                               {i["uid"] for i in fresh + insider_fresh})
    except Exception as e:
        print(f"  earnings dates: FAILED this run — {type(e).__name__}: {e}. "
              f"Dates were not recorded this run; continuing to post.",
              file=sys.stderr)

    # Mark everything fresh as seen up front. Items we don't post this run are
    # still recorded, so a big backlog can't re-flood on the next run.
    for item in fresh + insider_fresh:
        seen.add(item["uid"])
        state["seen"].append(item["uid"])

    # A company appearing for the first time posts nothing at all, press or
    # insider. This runs AFTER the marking above, so its items are recorded as
    # seen exactly like any other suppressed item and cannot return next run.
    new_companies, _suppressed = baseline_companies(
        state, list(EXTRA_CIKS), fresh + insider_fresh)
    if new_companies:
        blocked = set(new_companies)
        fresh = [i for i in fresh if i.get("ticker") not in blocked]
        insider_fresh = [i for i in insider_fresh
                         if i.get("ticker") not in blocked]

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
