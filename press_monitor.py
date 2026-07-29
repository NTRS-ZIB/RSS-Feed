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
import sys
import time
from calendar import timegm
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests

# ------------------------------------------------------------------ CONFIG

# Just list tickers. CIKs are resolved automatically from SEC's lookup file.
TICKERS = [
    "BGDE",  # Big Digital Energy (formerly Mawson Infrastructure)
    "ANY",   # Sphere 3D
    "NUAI",  # New Era Energy & Digital
    "SLNH",  # Soluna Holdings
    "DGXX",  # Diginex
    "BKKT",  # Bakkt Holdings
    "MARA",  # MARA Holdings
    "WYFI",  # WhiteFiber
    "IREN",  # IREN Limited
    "CLSK",  # CleanSpark
]

# Companies pinned by CIK instead of ticker. Use this when a recent rename or
# symbol change means SEC's ticker lookup file is stale or points elsewhere.
# Format: "LABEL": ("zero-padded CIK", "Display name")
EXTRA_CIKS = {
    # Renamed from Greenidge Generation (GREE -> VIP on 2026-07-24). VEON held
    # the VIP symbol previously, so ticker lookup is unsafe here.
    "VIP": ("0001844971", "Vulcan Infrastructure and Power"),
}

# Company IR feeds. Key is the label shown in the message.
# Leave empty to run EDGAR-only until you've collected these.
IR_FEEDS = {
    # Direct feed URLs. Confirmed or derived from the IR platform's known pattern.
    "MARA": "https://ir.mara.com/news-events/press-releases/rss",
    "CleanSpark": "https://investors.cleanspark.com/rss/pressrelease.aspx",
    "Bakkt": "https://investors.bakkt.com/rss/pressrelease.aspx",
    "IREN": "https://irisenergy.gcs-web.com/rss/news-releases.xml",
    "New Era Energy & Digital": "https://investors.newerainfra.ai/rss/pressrelease.aspx",
    "Vulcan Infrastructure and Power": "https://ir.vulcanip.com/rss/news-releases.xml",

    # News pages. If these aren't feeds, the script autodiscovers the real feed
    # from the page's <link rel="alternate"> tag and uses that instead.
    "Soluna": "https://www.solunacomputing.com/news/",
    "Big Digital Energy": "https://www.bigdigital.energy/",
    "Sphere 3D": "https://www.sphere3d.com/",
    "Diginex": "https://www.diginex.com/",

    # Webflow site, news list rendered client-side, no autodiscovery tag.
    # Expect NO FEED. Left in so it picks up automatically if they add one.
    "WhiteFiber": "https://www.whitefiber.com/investors-news",
}

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

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
# SEC requires a descriptive User-Agent with a contact address.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))

IR_AGENT = "press-monitor/1.0 (personal RSS aggregation)"
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
        r = requests.get(page_url, headers={"User-Agent": IR_AGENT}, timeout=30)
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
    """Parse a URL as a feed. Returns entries, or empty list."""
    try:
        parsed = feedparser.parse(url, agent=IR_AGENT)
        return parsed.entries or []
    except Exception:
        return []


def collect_ir():
    items = []
    for label, url in IR_FEEDS.items():
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
