#!/usr/bin/env python3
"""
Press release monitor -> Slack or Discord.

Watches two sources per company:
  1. SEC EDGAR filings (8-K for US issuers, 6-K for foreign private issuers)
  2. The company's own IR newsroom RSS feed, if it has one

Dedupes against state.json so each item is posted exactly once.
"""

import json
import os
import re
import socket
import sys
import time
from calendar import timegm
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests

# ------------------------------------------------------------------ CONFIG

# Just list tickers. CIKs are resolved automatically from SEC's lookup file.
TICKERS = []  # Ticker lookup is fragile across renames; see EXTRA_CIKS below.

# Every company pinned by CIK. CIKs never change, even when a company renames
# or switches ticker — which this sector does constantly. BGDE renamed in Apr
# 2026, VIP in Jul 2026, and ANY has a pending change to DarkHorse (DRK).
# Format: "LABEL": ("zero-padded CIK", "Display name")
EXTRA_CIKS = {
    "BGDE": ("0001218683", "Big Digital Energy"),
    "ANY":  ("0001591956", "Sphere 3D"),
    "NUAI": ("0002028336", "New Era Energy & Digital"),
    "SLNH": ("0000064463", "Soluna Holdings"),
    "DGXX": ("0001854368", "Digi Power X"),
    "BKKT": ("0001820302", "Bakkt Holdings"),
    "MARA": ("0001507605", "MARA Holdings"),
    "WYFI": ("0002042022", "WhiteFiber"),
    "IREN": ("0001878848", "IREN Limited"),
    "CLSK": ("0000827876", "CleanSpark"),
    "VIP":  ("0001844971", "Vulcan Infrastructure and Power"),
}

# Company IR feeds. Key is the label shown in the message.
# Leave empty to run EDGAR-only until you've collected these.
IR_FEEDS = {
    # Equisolve platform
    "MARA": "https://ir.mara.com/news-events/press-releases/rss",

    # Q4 Inc platform  (/rss/pressrelease.aspx)
    "CleanSpark": "https://investors.cleanspark.com/rss/pressrelease.aspx",
    "New Era Energy & Digital": "https://investors.newerainfra.ai/rss/pressrelease.aspx",

    # Notified / gcs-web platform  (/rss/news-releases.xml)
    "IREN": "https://irisenergy.gcs-web.com/rss/news-releases.xml",
    "Vulcan Infrastructure and Power": "https://ir.vulcanip.com/rss/news-releases.xml",
    "Sphere 3D": "https://sphere3d.gcs-web.com/rss/news-releases.xml",
    # Migrated off Q4 to gcs-web; the old /rss/pressrelease.aspx path now 404s.
    "Bakkt": "https://investors.bakkt.com/rss/news-releases.xml",

    # WordPress. The site-wide /feed/ is a near-dormant blog feed (3 items);
    # the press releases live in the /news/ archive, so target its feed directly.
    # If this 404s, autodiscovery can't help and Soluna is EDGAR-only.
    "Soluna": "https://www.solunacomputing.com/news/feed/",
}

# Confirmed to have NO usable feed. Their newsrooms render client-side, so the
# headlines aren't in the HTML and neither autodiscovery nor a plain scraper
# can see them. These companies are covered by EDGAR 8-K only.
#   Big Digital Energy  https://www.bigdigital.energy/news-media/press-releases/
#                       (QuoteMedia widget)
#   WhiteFiber          https://www.whitefiber.com/investors-news  (Webflow)
#   Digi Power X        https://www.digipowerx.com/press-releases  (Next.js)


# EDGAR form types to watch. 8-K = US material events. 6-K = foreign issuers.
# Add "10-Q", "10-K" if you want periodic reports too.
# EDGAR's type filter is a PREFIX match, which does useful work here:
#   "8-K"  also catches 8-K/A       "10-Q" also catches 10-Q/A
#   "424"  catches 424B1 ... 424B8  "SC 13D" also catches SC 13D/A
FORM_TYPES = [
    "8-K",     # US material events; press releases attach as EX-99
    "6-K",     # same, foreign private issuers
    "424",     # prospectus supplements — offerings being priced. Dilution.
    "10-Q",    # quarterly financials
    "10-K",    # annual financials
    "20-F",    # annual, foreign private issuers
    "40-F",    # annual, Canadian MJDS filers
    "SC 13D",  # activist / >5% stake disclosures
    "NT 10-K", # late filing notice — low volume, high signal
    "NT 10-Q",
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
INSIDER_ALLOWED_FORMS = {"4", "4/A"}

# ------------------------------------------------------------------ RUNTIME

socket.setdefaulttimeout(25)

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
INSIDER_WEBHOOK_URL = os.environ.get("WEBHOOK_URL_INSIDER", "").strip()
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
    floor = max(4000, items_this_run * 3)
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


def carries_press_release(form, items):
    """Whether an 8-K's item numbers indicate a press release.

    Replaces fetching each filing's index page to look for an EX-99 exhibit.
    The items are already in the submissions payload, so this is free.
    6-K has no item numbers, so it is never filtered.
    """
    if not form.startswith("8-K"):
        return True
    if not items:
        return True          # no items listed: fail open rather than drop it
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
    for ticker, (cik, name) in resolved.items():
        filings = company_filings(cik)
        if not filings:
            print(f"  {ticker}: no filings returned")
            continue

        kept = ins = 0
        for f in filings:
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
        print(f"  {ticker}: {len(filings)} filing(s) -> {kept} tracked, "
              f"{ins} insider")
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
        for entry in entries:
            items.append({
                "uid": entry.get("id") or entry.get("link"),
                "source": f"{label} · IR newsroom",
                "title": entry.get("title", "Untitled"),
                "link": entry.get("link", ""),
                "published": entry_time(entry),
                "is_edgar": False,
            })
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
    if not WEBHOOK_URL:
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
        save_state(state, len(all_items))
        print("First run complete — baseline recorded, nothing posted.")
        return

    # Mark everything fresh as seen up front. Items we don't post this run are
    # still recorded, so a big backlog can't re-flood on the next run.
    for item in fresh + insider_fresh:
        seen.add(item["uid"])
        state["seen"].append(item["uid"])

    # Only the newest candidates get the expensive exhibit check. Without this
    # cap, a state reset would trigger one SEC fetch per backlog item.
    candidates = [i for i in fresh if passes_keywords(i)]
    candidates.sort(key=lambda i: i.get("published") or 0, reverse=True)
    candidates = candidates[: MAX_POSTS_PER_RUN * 2]

    to_post = []
    for item in candidates:
        if len(to_post) >= MAX_POSTS_PER_RUN:
            break
        if PRESS_RELEASE_EXHIBIT_ONLY and item.get("form") in EXHIBIT_CHECK_FORMS:
            if not carries_press_release(item["form"], item.get("items", "")):
                continue
        to_post.append(item)

    print(f"{len(candidates)} candidate(s) checked, {len(to_post)} to post.")
    failed = []
    sent = 0
    for item in to_post:
        if post(item, WEBHOOK_URL):
            sent += 1
        else:
            failed.append(item["uid"])
    print(f"Posted {sent} press item(s).")

    # Insider channel: no exhibit check, separate cap, separate webhook.
    if insider_fresh:
        insider_fresh.sort(key=lambda i: i.get("published") or 0, reverse=True)
        batch = insider_fresh[:MAX_INSIDER_POSTS_PER_RUN]
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
