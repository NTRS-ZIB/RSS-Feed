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
    "Bakkt": "https://investors.bakkt.com/rss/pressrelease.aspx",
    "New Era Energy & Digital": "https://investors.newerainfra.ai/rss/pressrelease.aspx",

    # Notified / gcs-web platform  (/rss/news-releases.xml)
    "IREN": "https://irisenergy.gcs-web.com/rss/news-releases.xml",
    "Vulcan Infrastructure and Power": "https://ir.vulcanip.com/rss/news-releases.xml",
    "Sphere 3D": "https://sphere3d.gcs-web.com/rss/news-releases.xml",

    # WordPress — autodiscovered
    "Soluna": "https://www.solunacomputing.com/news/",
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
FORM_TYPES = ["8-K", "6-K"]

# If True, an EDGAR filing is only posted when it actually attaches a press
# release (an EX-99 exhibit). Filters out pure administrative 8-Ks.
# Costs one extra HTTP request per new filing.
PRESS_RELEASE_EXHIBIT_ONLY = True

# Optional keyword filter, applied to titles. Empty list = post everything.
# e.g. ["acquisition", "dividend", "guidance"]
KEYWORDS = []

# Safety valve: never post more than this in one run.
MAX_POSTS_PER_RUN = 25

# ------------------------------------------------------------------ RUNTIME

socket.setdefaulttimeout(25)

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
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
EDGAR_ATOM = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type={form}&dateb="
    "&owner=include&count=40&output=atom"
)


def sec_headers():
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }


def sec_get(url, tries=3):
    """GET against sec.gov, politely. Returns text or None."""
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=sec_headers(), timeout=30)
            if r.status_code == 200:
                time.sleep(0.15)  # stay well under SEC's 10 req/sec ceiling
                return r.text
            if r.status_code in (429, 503):
                time.sleep(3 * (attempt + 1))
                continue
            print(f"  HTTP {r.status_code} for {url}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            print(f"  request failed ({e}), retrying", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            print("state.json unreadable, treating as first run", file=sys.stderr)
    return {"seen": [], "initialized": False}


def save_state(state):
    # Keep the most recent 4000 ids; plenty of headroom, bounded file size.
    state["seen"] = state["seen"][-4000:]
    STATE_FILE.write_text(json.dumps(state, indent=1))


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


def has_press_release_exhibit(index_url):
    """Fetch a filing's index page and look for an EX-99 exhibit."""
    html = sec_get(index_url)
    if html is None:
        return True  # fail open: better a false positive than a missed release
    return bool(re.search(r"\bEX-99", html))


def collect_edgar(resolved):
    items = []
    for ticker, (cik, name) in resolved.items():
        print(f"  {ticker} (CIK {cik})...")
        for form in FORM_TYPES:
            xml = sec_get(EDGAR_ATOM.format(cik=cik, form=form))
            if not xml:
                continue
            for entry in feedparser.parse(xml).entries:
                items.append({
                    "uid": entry.get("id") or entry.get("link"),
                    "source": f"{name} ({ticker}) · SEC {form}",
                    "title": entry.get("title", "Untitled filing"),
                    "link": entry.get("link", ""),
                    "published": entry_time(entry),
                    "is_edgar": True,
                })
    return items


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


def passes_keywords(item):
    if not KEYWORDS:
        return True
    haystack = item["title"].lower()
    return any(k.lower() in haystack for k in KEYWORDS)


def post(item):
    """Post one item. Payload shape is inferred from the webhook host."""
    if "discord.com" in WEBHOOK_URL or "discordapp.com" in WEBHOOK_URL:
        payload = {
            "embeds": [{
                "title": item["title"][:250],
                "url": item["link"],
                "footer": {"text": item["source"]},
                "color": 0x1F6FEB,
            }]
        }
    else:  # Slack incoming webhook
        payload = {
            "text": f"*{item['source']}*\n<{item['link']}|{item['title']}>"
        }
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        if r.status_code >= 300:
            print(f"  webhook returned {r.status_code}: {r.text[:200]}",
                  file=sys.stderr)
            return False
    except requests.RequestException as e:
        print(f"  webhook failed: {e}", file=sys.stderr)
        return False
    time.sleep(1.0)  # respect Discord/Slack rate limits
    return True


def main():
    if not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL is not set.")
    if not SEC_USER_AGENT:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

    state = load_state()
    seen = set(state["seen"])

    resolved = {}
    if TICKERS:
        print(f"Resolving {len(TICKERS)} tickers...")
        resolved = resolve_ciks(TICKERS)
    for label, (cik, name) in EXTRA_CIKS.items():
        resolved[label] = (cik.zfill(10), name)
        print(f"  {label}: pinned to CIK {cik.zfill(10)} ({name})")
    print(f"Checking EDGAR for {len(resolved)} companies...")
    items = collect_edgar(resolved)
    print(f"Checking {len(IR_FEEDS)} IR feeds...")
    items += collect_ir()

    fresh = [i for i in items if i["uid"] and i["uid"] not in seen]
    print(f"{len(items)} items seen, {len(fresh)} new.")

    # First run: record everything, post nothing. Avoids a wall of backlog.
    if not state.get("initialized"):
        state["seen"] = [i["uid"] for i in items if i["uid"]]
        state["initialized"] = True
        save_state(state)
        print("First run complete — baseline recorded, nothing posted.")
        return

    # Mark everything fresh as seen up front. Items we don't post this run are
    # still recorded, so a big backlog can't re-flood on the next run.
    for item in fresh:
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
        if item["is_edgar"] and PRESS_RELEASE_EXHIBIT_ONLY:
            if not has_press_release_exhibit(item["link"]):
                continue
        to_post.append(item)

    print(f"{len(candidates)} candidate(s) checked, {len(to_post)} to post.")
    sent = sum(1 for item in to_post if post(item))
    print(f"Posted {sent} item(s).")
    save_state(state)


if __name__ == "__main__":
    main()
