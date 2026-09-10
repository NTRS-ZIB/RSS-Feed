#!/usr/bin/env python3
"""Does any IR host require a browser User-Agent, and does the default stall?

Maintenance tool, not a component. Read-only: fetches each IR source twice,
once with the headers press_monitor actually ships and once with a browser
User-Agent, and prints which answer and which stall. No webhook, no state, no
commit, no schedule.

WHY IT EXISTS. On 2026-09-09 eight of nineteen feeds stalled the browser
User-Agent the repo had shipped since August, with no change in this
repository: Chrome/126 was current when it was written and had aged into a
signature a WAF treats as a bot. The default became an identifying string on
the strength of a measurement, and a number that justifies live behaviour has
to stay re-derivable, so this is that measurement as a tool.

IT IMPORTS press_monitor.IR_HEADERS RATHER THAN COPYING IT. A probe holding
its own copy of the thing it validates stops testing the shipped value the
first time someone edits one and not the other.

RUN IT ON THE RUNNER, not locally:

    gh workflow run "Probe IR headers"

That matters more here than for most probes. The 2026-08-11 finding was that a
browser UA scores worse FROM A DATACENTER IP, so a result from a home
connection can disagree with production and be right about the wrong network.

A stall is the finding, not an error. Every arm is bounded by TIMEOUT and a
timeout is reported rather than raised, because the whole point is that these
hosts fail by hanging instead of refusing.
"""

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import press_monitor as pm
import watchlist

# Long enough to distinguish a stall from ordinary slowness, short enough that
# a fully broken roster still finishes inside the workflow's timeout. The
# stalls measured on 2026-09-09 ran to 15s and beyond; every healthy answer
# came back in under half a second.
TIMEOUT = 15

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# The URLs that share IR_HEADERS but are not ir_feed entries. Measuring only
# the feeds and then changing the shared default would be a number taken over
# an adjacent population, which this repo has been caught by before. The two
# JSON endpoints override Accept in press_monitor, so only the UA varies.
NON_FEED = [
    ("HUT page", pm.HUT_PAGE, None),
    ("GLXY page", pm.GLXY_PAGE, None),
    ("DGXX page", pm.DGXX_PAGE, None),
    ("ABTC page", pm.ABTC_PAGE, None),
    ("DGXX API", pm.DGXX_API, "application/json"),
    ("ABTC API", pm.ABTC_API, "application/json"),
]


def fetch(url, headers):
    """(result, seconds). Never raises: a stall is the measurement."""
    req = urllib.request.Request(url, headers=headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
        entries = body.count(b"<item") + body.count(b"<entry")
        detail = f"{entries:>3} entries" if entries else f"{len(body):>8,}b"
        return f"{r.status} {detail}", time.monotonic() - start
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", time.monotonic() - start
    except Exception as e:
        return type(e).__name__, time.monotonic() - start


def arms(accept):
    """The shipped headers, and the same set with a browser UA."""
    shipped = dict(pm.IR_HEADERS)
    if accept:
        shipped["Accept"] = accept
    return shipped, dict(shipped, **{"User-Agent": BROWSER_UA})


def main():
    print(f"shipped User-Agent: {pm.IR_HEADERS['User-Agent']}")
    print(f"HOST_HEADERS overrides: {len(pm.HOST_HEADERS)}")
    for host, headers in pm.HOST_HEADERS.items():
        print(f"  {host}: {headers.get('User-Agent', '')[:60]}")
    print()

    targets = [(t, u, None) for t, u in sorted(watchlist.ir_feeds().items())]
    targets += NON_FEED

    print(f"{'target':<12}{'host':<32}{'shipped':<22}{'':>6}  "
          f"{'browser UA':<22}{'':>6}")
    print("-" * 104)

    shipped_ok = browser_only = stalls = 0
    for label, url, accept in targets:
        # Honour a per-host override if one is ever added back, so the probe
        # reports what the component would actually send.
        base = pm.headers_for(url)
        shipped, browser = arms(accept)
        if base is not pm.IR_HEADERS:
            shipped = dict(base, **({"Accept": accept} if accept else {}))

        a, at = fetch(url, shipped)
        b, bt = fetch(url, browser)

        flag = ""
        if a.startswith("200"):
            shipped_ok += 1
        if "Timeout" in a:
            stalls += 1
            flag = "  <- THE SHIPPED DEFAULT STALLS HERE"
        if not a.startswith("200") and b.startswith("200"):
            browser_only += 1
            flag = "  <- WANTS A BROWSER UA: needs a HOST_HEADERS entry"

        print(f"{label:<12}{urlparse(url).netloc:<32}{a:<22}{at:>5.1f}s  "
              f"{b:<22}{bt:>5.1f}s{flag}")

    print()
    print(f"targets                            : {len(targets)}")
    print(f"answering 200 on the shipped default: {shipped_ok}")
    print(f"stalling the shipped default        : {stalls}")
    print(f"answering ONLY the browser UA       : {browser_only}")
    print()
    if browser_only:
        print("A host answering only the browser UA needs its own HOST_HEADERS")
        print("entry carrying this measurement. Do NOT change the shared")
        print("default back: a pinned browser version decays, which is what")
        print("produced the 2026-09-09 outage in the first place.")
    else:
        print("No host on the roster requires a browser User-Agent, which is")
        print("the finding the current default rests on.")


if __name__ == "__main__":
    main()
