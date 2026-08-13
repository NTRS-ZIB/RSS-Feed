#!/usr/bin/env python3
"""Census of the date material every IR source offers, and what it costs.

WHAT THIS ANSWERS
`within_age()` drops an item whose `published` is `0`. The value falls to
1970, so it reads as ancient rather than as undated, and the item is dropped
however fresh it really is. That is not a near-miss: `main()` marks items seen
BEFORE the age floor runs, so a dropped item is recorded as seen and can never
return. One undated item is one release the channel never carries.

Five code paths mint that `0`. `entry_time()` returns it for a feed entry
whose timestamp will not parse, and `scrape_hut8()`, `scrape_galaxy()`,
`read_dgxx()` and `read_abtc()` each default to it when their own date parse
fails — brittle format strings like "%b %d, %Y" against a CMS nobody here
controls.

Nobody has ever measured how often it happens. This does.

WHY IT IS A CENSUS AND NOT A COUNT
One sweep sees roughly twenty entries per source at one instant, so if the
`0` is rare the count is zero and a bare count of zero measures nothing: it
cannot tell "this never happens" from "the window was too short", which is a
mistake this repository has made before and written down.

So every item is classified by the date material its source offered, not only
by whether the result was `0`. A run finding no zeros still reports the shape
of the population that produced none, and that is an answer: if every entry
carries a timestamp feedparser parses cleanly, the `0` path needs a source to
BREAK, and its rate is the rate of breakage rather than a property of normal
traffic.

HOW TO READ THE OUTPUT
The census columns are the classification of every item:

  parsed           a usable timestamp; within_age judges it on its merits
  struct-unusable  a *_parsed struct exists but timegm rejected it
  string-unparsed  the source gave a date string feedparser could not read
  no-date-field    the source offered no date at all
  scraped-zero     a scraper or CMS reader produced published == 0

The last four are all dropped, permanently. Any count above zero in those
columns names a release the channel silently did not carry, and each one is
printed in full below the table.

Read-only. Fetches the same sources the monitor already fetches, posts
nothing, writes nothing, needs no secrets.
"""

import sys

import press_monitor as pm

# feedparser exposes both a raw string and a parsed struct_time per date.
# entry_time only ever consults the structs, so a string with no struct beside
# it is a date the source supplied and feedparser declined to read.
STRUCTS = ("published_parsed", "updated_parsed", "created_parsed")
STRINGS = ("published", "updated", "created")

PARSED = "parsed"
STRUCT_BAD = "struct-unusable"
STRING_BAD = "string-unparsed"
NO_FIELD = "no-date-field"
SCRAPED_ZERO = "scraped-zero"

CLASSES = [PARSED, STRUCT_BAD, STRING_BAD, NO_FIELD, SCRAPED_ZERO]


def classify(entry):
    """Which date material this feed entry offered, and what came of it."""
    if pm.entry_time(entry):
        return PARSED
    # entry_time returned 0. The three arms below are the three reasons, and
    # they are worth separating: a struct that timegm rejects is a feedparser
    # bug, an unread string is a format nobody taught it, and no field at all
    # is the source's own choice. Only the last is out of our hands.
    if any(entry.get(k) for k in STRUCTS):
        return STRUCT_BAD
    if any(entry.get(k) for k in STRINGS):
        return STRING_BAD
    return NO_FIELD


def date_material(entry):
    """Every date-ish value on this entry, for printing a loss in full."""
    bits = []
    for key in STRINGS + STRUCTS:
        value = entry.get(key)
        if value:
            bits.append(f"{key}={value!r}")
    return "; ".join(bits) or "no date field of any kind"


def sweep_feeds():
    """(rows, losses) over every configured IR feed."""
    rows, losses = [], []
    for label, url in pm.IR_FEEDS.items():
        entries = pm.parse_feed(url)
        if not entries:
            # A dead feed is a different measurement and report_feed_health
            # already owns it. Recorded here so the table's totals are honest
            # about what was not sampled.
            rows.append((label, "feed", 0, {}))
            print(f"  {label}: no entries — not sampled")
            continue
        counts = {}
        for entry in entries:
            verdict = classify(entry)
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict != PARSED:
                losses.append((label, verdict,
                               entry.get("title", "Untitled"),
                               entry.get("link", ""),
                               date_material(entry)))
        rows.append((label, "feed", len(entries), counts))
        print(f"  {label}: {len(entries)} entries")
    return rows, losses


def sweep_scraped():
    """(rows, losses) over the four sources that build items themselves.

    These cannot be censused the way a feed can: each reader parses its own
    date inline and returns the item, so the material it rejected is gone by
    the time we see the result. What is observable is the outcome, and for a
    zero the title and link are enough to go and look.
    """
    rows, losses = [], []
    readers = [("HUT", pm.scrape_hut8), ("GLXY", pm.scrape_galaxy),
               ("DGXX", pm.read_dgxx), ("ABTC", pm.read_abtc)]
    for label, reader in readers:
        try:
            items = reader()
        except Exception as exc:                       # noqa: BLE001
            # The readers promise never to raise. If one does, that is worth
            # the run reporting rather than the run dying.
            print(f"  {label}: READER RAISED {type(exc).__name__}: {exc}")
            rows.append((label, "scraped", 0, {}))
            continue
        zeros = [i for i in items if not i.get("published")]
        counts = {PARSED: len(items) - len(zeros)}
        if zeros:
            counts[SCRAPED_ZERO] = len(zeros)
        for item in zeros:
            losses.append((label, SCRAPED_ZERO, item.get("title", "Untitled"),
                           item.get("link", ""),
                           "reader produced published=0"))
        rows.append((label, "scraped", len(items), counts))
    return rows, losses


def main():
    print("Sweeping IR feeds...")
    feed_rows, feed_losses = sweep_feeds()
    print("\nSweeping scraped and CMS sources...")
    scraped_rows, scraped_losses = sweep_scraped()

    rows = feed_rows + scraped_rows
    losses = feed_losses + scraped_losses

    print("\nCENSUS")
    header = f"{'source':<8}{'kind':<9}{'items':>6}  " + "".join(
        f"{c:>17}" for c in CLASSES)
    print(header)
    print("-" * len(header))
    totals = {c: 0 for c in CLASSES}
    total_items = 0
    for label, kind, n, counts in rows:
        total_items += n
        cells = ""
        for c in CLASSES:
            v = counts.get(c, 0)
            totals[c] += v
            cells += f"{v if v else '.':>17}"
        print(f"{label:<8}{kind:<9}{n:>6}  {cells}")
    print("-" * len(header))
    cells = "".join(f"{totals[c]:>17}" for c in CLASSES)
    print(f"{'TOTAL':<8}{'':<9}{total_items:>6}  {cells}")

    dropped = sum(totals[c] for c in CLASSES if c != PARSED)
    print(f"\n{dropped} of {total_items} items would be DROPPED by within_age "
          f"and recorded as seen, so never posted and never retried.")

    if losses:
        print("\nEVERY DROPPED ITEM, IN FULL")
        for label, verdict, title, link, material in losses:
            print(f"\n  {label} [{verdict}] {title[:70]}")
            print(f"    {link}")
            print(f"    {material}")
    else:
        # State plainly what a null result does and does not establish, or
        # the next reader will take it for "this cannot happen".
        print("\nNo item in this sweep was undated. That is a measurement of "
              "the population above,\nnot a proof that the 0 path is dead: "
              f"every one of the {total_items} items carried a date its\n"
              "source could produce and its reader could read. The drop "
              "therefore costs nothing\nwhile the sources behave, and bites "
              "only when one breaks — which is exactly when\nit is least "
              "affordable, since a broken source is the case the drop makes "
              "silent.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
