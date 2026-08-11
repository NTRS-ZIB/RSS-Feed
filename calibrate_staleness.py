#!/usr/bin/env python3
"""Re-calibrate the staleness thresholds in press_monitor.py against live data.

WHAT THIS ANSWERS
`check_staleness()` fires when a source's newest item is older than
`max(STALE_MULTIPLE x median_gap, STALE_FLOOR_DAYS, override)`. Those two
numbers are not arbitrary and they are not permanent. This measures every
source's real publication cadence and reports what each candidate multiple
would do, so the thresholds can be re-derived rather than re-guessed.

WHEN TO RUN IT
- After adding or removing a source, since the calibration is only as good as
  the population it was measured over.
- When a source is found to have died quietly. That is a new control, and one
  control is thin evidence — see KNOWN_DEAD below.
- If a STALE warning turns out to be a false positive. That means the multiple
  or the floor is too tight, and this shows by how much.

HOW TO READ THE OUTPUT
Every live source is healthy by assumption: they are all currently publishing,
so ANYTHING THAT FIRES IS A FALSE POSITIVE and the multiple is too tight. The
known-dead control must fire, or the detector is not worth having. The usable
window is between the worst healthy ratio and the control's ratio; the chosen
multiple should sit just above the former with room to spare below the latter.

The numbers in press_monitor.py came from this script on 2026-08-03: fourteen
live sources with a worst healthy ratio of 5.0x, one control at 31.8x, and 6x
the tightest multiple with no false positives.

Read-only. Fetches the same feeds the monitor already fetches, posts nothing,
writes nothing, and needs no secrets.
"""

import os
import statistics
import sys
import time
from datetime import datetime, timezone

import press_monitor as pm

# Sources confirmed to have stopped updating while still serving valid content.
# These are the controls: a detector that does not fire on them is useless.
#
# DGXX moved from GlobeNewswire to ACCESS Newswire around 2026-01. This feed
# still returns 20 well-formed items with resolvable ids and correct
# timestamps, none newer than 2025-12-24. It is kept here precisely because it
# has not been fixed and presumably never will be — a permanent control.
KNOWN_DEAD = {
    "DEAD-dgxx-gnw": ("https://www.globenewswire.com/rssfeed/organization/"
                      "zgLApiCrgUf6P184m_M8NA=="),
}

CANDIDATE_MULTIPLES = (2, 3, 4, 5, 6, 8, 10, 12)


def cadence(times):
    """(items, distinct days, median gap, newest age, ratio) for one source.

    Same-day items are collapsed, exactly as check_staleness() does. Three
    releases in one morning are one publication event; their zero-day gaps drag
    the median down until an ordinary quiet spell looks like a failure.
    """
    times = [t for t in times if t]
    if not times:
        return None
    days = sorted({datetime.fromtimestamp(t, timezone.utc).date()
                   for t in times}, reverse=True)
    age = (time.time() - max(times)) / 86400
    if len(days) < 2:
        return (len(times), len(days), None, age, None)
    gaps = [(days[i] - days[i + 1]).days for i in range(len(days) - 1)]
    med = statistics.median(gaps)
    return (len(times), len(days), med, age, (age / med) if med else None)


def raw_median(times):
    """Median gap WITHOUT collapsing same-day items, to show why we collapse."""
    ts = sorted((t for t in times if t), reverse=True)
    if len(ts) < 2:
        return None
    return statistics.median((ts[i] - ts[i + 1]) / 86400
                             for i in range(len(ts) - 1))


def gather():
    """Every source the monitor reads, plus the known-dead controls."""
    out = []
    for label, url in pm.IR_FEEDS.items():
        entries = pm.parse_feed(url)
        out.append((label, "feed", [pm.entry_time(e) for e in entries]))
    out.append(("HUT", "scrape", [i["published"] for i in pm.scrape_hut8()]))
    out.append(("DGXX", "cms", [i["published"] for i in pm.read_dgxx()]))
    for label, url in KNOWN_DEAD.items():
        entries = pm.parse_feed(url)
        out.append((label, "control", [pm.entry_time(e) for e in entries]))
    return out


def main():
    rows = [(label, kind, times, cadence(times)) for label, kind, times in gather()]

    print("\n" + "=" * 82)
    print("CADENCE  (same-day items collapsed, as check_staleness does)")
    print("=" * 82)
    print(f"{'source':<16}{'kind':<9}{'items':>6}{'days':>6}{'median':>8}"
          f"{'newest':>9}{'ratio':>8}")
    print("-" * 82)
    for label, kind, _, c in rows:
        if not c:
            print(f"{label:<16}{kind:<9}  no usable timestamps")
            continue
        n, d, med, age, ratio = c
        print(f"{label:<16}{kind:<9}{n:>6}{d:>6}"
              f"{(f'{med:.0f}d' if med is not None else '-'):>8}"
              f"{age:>8.0f}d"
              f"{(f'{ratio:.1f}x' if ratio is not None else '-'):>8}")

    live = [(l, c) for l, k, _, c in rows if k != "control" and c and c[4]]
    dead = [(l, c) for l, k, _, c in rows if k == "control" and c and c[4]]

    print("\n" + "=" * 82)
    print("WHAT EACH MULTIPLE WOULD DO")
    print("=" * 82)
    print("  Every live source is publishing, so anything that fires is a")
    print("  FALSE POSITIVE. Every control must fire.\n")
    for k in CANDIDATE_MULTIPLES:
        fp = [l for l, c in live if c[4] > k]
        missed = [l for l, c in dead if c[4] <= k]
        verdict = "OK" if not fp and not missed else "no"
        print(f"  x{k:<3} {verdict:<4} false positives: "
              f"{', '.join(fp) if fp else 'none':<34}"
              f"controls missed: {', '.join(missed) if missed else 'none'}")

    if live and dead:
        worst = max(live, key=lambda t: t[1][4])
        best_dead = min(dead, key=lambda t: t[1][4])
        print(f"\n  usable window: {worst[1][4]:.1f}x ({worst[0]}) "
              f".. {best_dead[1][4]:.1f}x ({best_dead[0]})")

    print("\n" + "=" * 82)
    print("WHY SAME-DAY COLLAPSING IS LOAD-BEARING")
    print("=" * 82)
    print(f"  {'source':<16}{'raw median':>12}{'collapsed':>12}")
    print("  " + "-" * 40)
    for label, _, times, c in rows:
        if not c or c[2] is None:
            continue
        raw = raw_median(times)
        if raw is None:
            continue
        mark = "  <-- differs" if abs(raw - c[2]) >= 1 else ""
        print(f"  {label:<16}{raw:>11.1f}d{c[2]:>11.0f}d{mark}")

    print("\n" + "=" * 82)
    print("EFFECTIVE THRESHOLD PER SOURCE, AT THE CONFIGURED SETTINGS")
    print("=" * 82)
    print(f"  STALE_MULTIPLE={pm.STALE_MULTIPLE}  "
          f"STALE_FLOOR_DAYS={pm.STALE_FLOOR_DAYS}  "
          f"STALE_MIN_DAYS={pm.STALE_MIN_DAYS}\n")
    for label, kind, _, c in rows:
        if not c or c[2] is None:
            continue
        override = pm.DGXX_STALE_DAYS if label == "DGXX" else 0
        horizon = max(pm.STALE_MULTIPLE * c[2], pm.STALE_FLOOR_DAYS, override)
        state = "WOULD FIRE" if c[3] > horizon else ""
        print(f"  {label:<16}fires after {horizon:>5.0f}d   "
              f"(newest {c[3]:.0f}d) {state}")

    thin = [l for l, _, _, c in rows if c and c[1] < pm.STALE_MIN_DAYS]
    print(f"\n  below STALE_MIN_DAYS ({pm.STALE_MIN_DAYS} distinct days): "
          f"{', '.join(thin) if thin else 'none'}")
    return 0


BGDE_CANDIDATES = [
    # CONTROL, and the most important line here. An individual GlobeNewswire
    # release page, taken from a search result rather than derived. If this
    # answers while the feed hangs, the endpoint is broken; if it hangs too,
    # GlobeNewswire is refusing this runner and no GNW path will help.
    ("CONTROL gnw release page",
     "https://www.globenewswire.com/news-release/2026/07/29/3335631/0/en/"
     "Big-Digital-Energy-to-Release-Second-Quarter-2026-Results-August-12th.html"),
    # The source in the roster, for comparison in the same run.
    ("the configured org feed",
     "https://www.globenewswire.com/rssfeed/organization/z9WJvxXYqqA-t7lWEcsvqw=="),
    # DERIVED, therefore suspect. A URL that resolves is not evidence it is the
    # right URL — digipowerx.com answers 200 with wrong content for an unknown
    # release path, which is how a derived slug nearly shipped two dead links.
    ("DERIVED gnw org page",
     "https://www.globenewswire.com/en/search/organization/z9WJvxXYqqA-t7lWEcsvqw%3D%3D"),
    # The company's own domain, post-rebrand. The roster's note that BGDE's
    # newsroom cannot be read describes the OLD Mawson site and predates the
    # April 2026 rename, so it is a claim about a site that no longer exists.
    ("company site root", "https://www.bigdigital.energy/"),
    ("company /news", "https://www.bigdigital.energy/news"),
    ("company /press", "https://www.bigdigital.energy/press"),
    ("company /newsroom", "https://www.bigdigital.energy/newsroom"),
    ("company /investors", "https://www.bigdigital.energy/investors"),
]


def probe_bgde():
    """Report what each candidate BGDE source actually does. Concludes nothing.

    Read-only and disposable: this lives on a throwaway branch so it can be
    dispatched through calibrate.yml, which takes no inputs and is the only
    read-only workflow already on main. Delete the branch afterwards.
    """
    print("=" * 72)
    print("BGDE SOURCE PROBE — status, elapsed, type, size, entries, feed link")
    print("=" * 72)
    for name, url in BGDE_CANDIDATES:
        started = time.time()
        try:
            r = pm.requests.get(url, headers=pm.IR_HEADERS, timeout=(10, 20),
                                allow_redirects=True)
        except Exception as e:
            print(f"  {name:<26} FAILED {type(e).__name__} "
                  f"after {time.time() - started:.0f}s")
            continue
        took = time.time() - started
        body = r.content or b""
        try:
            entries = len(pm.feedparser.parse(body).entries or [])
        except Exception:
            entries = -1
        text = body.decode("utf-8", "replace")
        # Autodiscovery marker: does the HTML advertise a feed at all?
        has_link = 'rel="alternate"' in text and "rss" in text.lower()
        print(f"  {name:<26} {r.status_code} {took:>5.1f}s "
              f"{r.headers.get('Content-Type', '?')[:24]:<24} "
              f"{len(body):>8}b entries={entries:<4} feedlink={has_link}")
        if r.url != url:
            print(f"      redirected to {r.url}")
    print("=" * 72 + "\n")


def probe_bgde_news():
    """Does bigdigital.energy/news actually CARRY headlines in its HTML?

    60KB of HTML is not evidence of readable content. This repo has already
    recorded the inverse mistake twice — "278 cards, 0 dated" and "0 bundles,
    0 chars of JS" were both broken tools reporting as findings about the
    source. So this looks for named releases known to exist from elsewhere,
    rather than for a count that could mean anything.
    """
    import re
    # A browser Accept. The monitor's IR_HEADERS asks for feed types first and
    # this host answers 415 to that, which is a header problem and not a
    # missing page.
    headers = dict(pm.IR_HEADERS)
    headers["Accept"] = ("text/html,application/xhtml+xml,application/xml;"
                         "q=0.9,*/*;q=0.8")
    # Known to exist, from GlobeNewswire search results. If the HTML is
    # server-rendered these strings are in it; if it is a JS shell they are not.
    KNOWN = ["Hood County", "Endeavor", "Second Quarter 2026", "10NetZero"]

    for url in ("https://www.bigdigital.energy/news-media/press-releases/",
                "https://www.bigdigital.energy/news-media/news/",
                "https://www.bigdigital.energy/news-media/press-releases/rss",
                "https://www.bigdigital.energy/rss"):
        print("=" * 72)
        print(f"BGDE NEWS PAGE — {url}")
        print("=" * 72)
        try:
            r = pm.requests.get(url, headers=headers, timeout=(10, 20))
        except Exception as e:
            print(f"  FAILED {type(e).__name__}")
            continue
        text = (r.content or b"").decode("utf-8", "replace")
        print(f"  HTTP {r.status_code}  {len(text)} chars  final url {r.url}")
        for s in KNOWN:
            print(f"    contains {s!r}: {s.lower() in text.lower()}")
        hrefs = re.findall(r'href="([^"]+)"', text)
        news_hrefs = sorted({h for h in hrefs if "/news" in h.lower()})
        print(f"    {len(hrefs)} anchors, {len(news_hrefs)} pointing at /news")
        for h in news_hrefs[:12]:
            print(f"      {h[:96]}")
        dates = re.findall(
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s"
            r"+\d{1,2},?\s+20\d\d\b", text)
        print(f"    {len(dates)} date-like strings, first few: {dates[:6]}")
        # A JS shell is small in text and large in script. Both numbers, so
        # neither can be read as the whole story.
        scripts = sum(len(s) for s in re.findall(r"<script[^>]*>(.*?)</script>",
                                                 text, re.S))
        stripped = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ",
                                                  text, flags=re.S))
        visible = " ".join(stripped.split())
        print(f"    {scripts} chars of inline script, {len(visible)} chars of "
              f"visible text")
        print(f"    visible text starts: {visible[:220]!r}")
    print("=" * 72 + "\n")


def probe_bgde_backend():
    """What renders the press-release shell? DGXX and ABTC were both solved
    this way: the newsroom was unreadable HTML and the CMS behind it was a
    public JSON endpoint. Three of the four unreadable newsrooms on this
    roster had a machine-readable source somewhere other than the page."""
    import re
    headers = dict(pm.IR_HEADERS)
    headers["Accept"] = ("text/html,application/xhtml+xml,application/xml;"
                         "q=0.9,*/*;q=0.8")
    url = "https://www.bigdigital.energy/news-media/press-releases/"
    print("=" * 72)
    print(f"BGDE BACKEND PROBE — {url}")
    print("=" * 72)
    try:
        r = pm.requests.get(url, headers=headers, timeout=(10, 20))
    except Exception as e:
        print(f"  FAILED {type(e).__name__}")
        return
    text = (r.content or b"").decode("utf-8", "replace")

    srcs = sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', text)))
    print(f"  {len(srcs)} script src(s):")
    for s in srcs[:20]:
        print(f"      {s[:110]}")

    # Any absolute URL in the markup that is not the site itself. The endpoint
    # that feeds the shell is usually one of these.
    urls = sorted({u for u in re.findall(r'https?://[^\s"\'<>()]+', text)
                   if "bigdigital.energy" not in u})
    print(f"\n  {len(urls)} off-site URL(s):")
    for u in urls[:30]:
        print(f"      {u[:110]}")

    # An IR page very often embeds its releases rather than rendering them.
    for tag in ("iframe", "embed", "object"):
        for m in re.findall(rf"<{tag}[^>]*>", text, re.I):
            print(f"\n  <{tag}>: {m[:200]}")
    # Every quoted path inside inline script. The endpoint that fills the
    # shell is a string somewhere, even when it is built at runtime.
    inline = " ".join(re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>",
                                 text, re.S))
    paths = sorted({p for p in re.findall(r'["\'](/[A-Za-z0-9_\-./?=&]{4,})["\']',
                                          inline)})
    print(f"\n  {len(paths)} quoted path(s) inside inline script:")
    for p in paths[:40]:
        print(f"      {p[:110]}")
    data_attrs = sorted(set(re.findall(r'(data-[a-z-]+)="[^"]{4,}"', text)))
    print(f"\n  data-* attributes present: {data_attrs[:25]}")

    for marker in ("__NEXT_DATA__", "wp-json", "graphql", "sanity", "strapi",
                   "contentful", "prismic", "webflow", "hubspot", "q4inc",
                   "gcs-web", "globenewswire", "apiUrl", "api_url", "/api/"):
        if marker.lower() in text.lower():
            i = text.lower().find(marker.lower())
            print(f"\n  MARKER {marker!r} at {i}: "
                  f"{text[max(0, i - 90):i + 130]!r}")
    print("=" * 72 + "\n")


def probe_user_agents():
    """Is GlobeNewswire stalling this runner because of WHO it looks like?

    press_monitor's own comment records that IR platforms behind WAFs stall
    non-browser User-Agents rather than erroring, which is exactly the symptom
    here. The UA it sends is Chrome/126, roughly two years old now, and a WAF
    scoring client reputation would treat that as bot-like.

    Two URLs so a result cannot be read as being about the feed endpoint: the
    configured feed, and an ordinary release page that has nothing to do with
    feeds.
    """
    URLS = [
        ("org feed",
         "https://www.globenewswire.com/rssfeed/organization/z9WJvxXYqqA-t7lWEcsvqw=="),
        ("release page",
         "https://www.globenewswire.com/news-release/2026/07/29/3335631/0/en/"
         "Big-Digital-Energy-to-Release-Second-Quarter-2026-Results-August-12th.html"),
    ]
    CHROME_140 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                  " (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
    FIREFOX = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
               "Gecko/20100101 Firefox/131.0")
    CASES = [
        ("CONTROL current IR_HEADERS", dict(pm.IR_HEADERS)),
        ("Chrome/140, same Accept",
         {**pm.IR_HEADERS, "User-Agent": CHROME_140}),
        ("Chrome/140, browser Accept, keep-alive", {
            "User-Agent": CHROME_140,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }),
        ("Firefox/131, browser Accept", {
            "User-Agent": FIREFOX,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }),
        ("feed reader UA", {"User-Agent": "Feedly/1.0 (+http://www.feedly.com/"
                                          "fetcher.html; like FeedFetcher-Google)"}),
        ("no User-Agent at all", {"Accept": "*/*"}),
    ]
    # The first matrix's "no User-Agent" case did not send none: requests
    # supplies python-requests/X.Y.Z unless the header is explicitly removed.
    # So the winning condition is a plain non-browser UA, not the absence of
    # one, and these cases separate the two. A polite identifying UA is
    # preferred over both if it works — this repo already identifies itself to
    # the SEC that way.
    CASES += [
        ("explicit python-requests UA",
         {"User-Agent": "python-requests/2.34.2", "Accept": "*/*"}),
        ("truly no User-Agent header",
         {"User-Agent": None, "Accept": "*/*"}),
        ("curl UA", {"User-Agent": "curl/8.5.0", "Accept": "*/*"}),
        ("polite identifying UA",
         {"User-Agent": "InfraMonitor/1.0 (press release monitor; contact via "
                        "GitHub NTRS-ZIB/RSS-Feed)", "Accept": "*/*"}),
    ]
    print("=" * 72)
    print("GLOBENEWSWIRE USER-AGENT MATRIX")
    print("=" * 72)
    for label, headers in CASES:
        for what, url in URLS:
            started = time.time()
            try:
                r = pm.requests.get(url, headers=headers, timeout=(10, 15))
                took = time.time() - started
                body = r.content or b""
                extra = ""
                if what == "org feed":
                    try:
                        extra = f" entries={len(pm.feedparser.parse(body).entries or [])}"
                    except Exception:
                        extra = " entries=?"
                print(f"  {label:<38} {what:<13} {r.status_code} "
                      f"{took:>5.1f}s {len(body):>8}b{extra}")
            except Exception as e:
                print(f"  {label:<38} {what:<13} {type(e).__name__} "
                      f"after {time.time() - started:.0f}s")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    # Only this probe. The full calibration re-fetches every feed and the
    # hanging ones make the run take minutes for nothing.
    probe_user_agents()
    sys.exit(0)
