#!/usr/bin/env python3
"""
Nasdaq Reg SHO threshold list -> Discord.

A security joins the threshold list after five consecutive settlement days of
fails-to-deliver above 10,000 shares and at least 0.5% of shares outstanding.
Appearing triggers mandatory close-out obligations for broker-dealers.

WHY NASDAQ AND NOT FINRA
Each SRO publishes its own list, covering the securities for which it is the
primary market. FINRA's `thresholdList` dataset is the OTC list — FINRA Rule
4320 defines threshold securities as those of issuers that are NOT SEC
reporting securities. Every company on this watchlist is a Nasdaq-listed
reporting issuer, so a FINRA-based version would run indefinitely and never
fire. Cboe and NYSE publish their own lists for their own listings.

Source: https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{yyyymmdd}.txt
Pipe-delimited, no authentication, one file per SETTLEMENT day, published
before midnight Eastern.

This is an EXCEPTION REPORT. It posts only when a watchlist company is added
to or removed from the list, and is silent otherwise — which will be almost
every day. Silence means the check ran and found nothing.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import watchlist
from first_run import baseline, summary
# ------------------------------------------------------------------ CONFIG

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one. These two names are DERIVED, not restated: these three components need
# canonical -> [former symbols], while ftd_monitor.py needs the exact inverse.
# Hand-maintaining both directions is how GREE was once mapped to Soluna,
# merging two companies' data under a plausible number with no error anywhere.
TICKERS = watchlist.names()            # {ticker: display name}
ALIASES = watchlist.alt_by_ticker()    # {ticker: [former or pending symbols]}

# Settlement days have files; weekends and holidays do not. Walk back until a
# file is found. Six covers a long weekend plus a couple of holidays.
MAX_DAYS_BACK = 6

# How many prior files to read when counting how long a security has been
# listed. Costs one request each, so kept modest and only done on a change.
RUN_LOOKBACK_FILES = 15

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = (os.environ.get("WEBHOOK_URL_ALERTS", "").strip()
               or os.environ.get("WEBHOOK_URL_MARKET", "").strip())
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
STATE_FILE = Path(os.environ.get("THRESHOLD_STATE", "threshold_state.json"))

FILE_URL = ("https://www.nasdaqtrader.com/dynamic/symdir/regsho/"
            "nasdaqth{stamp}.txt")
# nasdaqtrader.com is a plain web host, not an API; send browser-like headers.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/plain,*/*;q=0.8",
}

MARKET_CATEGORIES = {
    "Q": "Nasdaq Global Select",
    "G": "Nasdaq Global",
    "S": "Nasdaq Capital Market",
}

RED, GREEN, AMBER = 0xF85149, 0x3FB950, 0xD29922


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"on_list": [], "last_date": ""}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1))


def fold_newly_watched(previous, current, newly_watched):
    """Companies added since the last run, treated as already known.

    A COMPANY ALREADY ON THE LIST WHEN IT JOINS THE ROSTER IS NOT AN
    ADDITION. It was listed before anyone here was looking, so reporting it
    as "added" dates an event to the day we started watching. Folding it into
    `previous` also means its eventual REMOVAL posts correctly, which
    dropping it from `current` would not.

    Returns the widened `previous` and the set that was folded in.
    """
    joining = current & {s.upper() for s in newly_watched}
    return previous | joining, joining


def canonical(symbol):
    symbol = (symbol or "").upper().strip()
    if symbol in TICKERS:
        return symbol
    for ticker, alts in ALIASES.items():
        if symbol in (a.upper() for a in alts):
            return ticker
    return None


def fetch_file(day):
    """Raw text for a settlement day, or None if there is no file."""
    url = FILE_URL.format(stamp=day.strftime("%Y%m%d"))
    try:
        r = requests.get(url, headers=HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"  {day}: {type(e).__name__}")
        return None
    if r.status_code == 404:
        return None                      # non-settlement day, expected
    if r.status_code != 200:
        print(f"  {day}: HTTP {r.status_code}")
        return None
    text = r.text
    # A valid file starts with the pipe-delimited header row. Nasdaq serves a
    # placeholder page rather than a 404 for a date that has not published
    # yet, so the status code alone cannot be trusted — same shape as Stooq's
    # HTTP 200 error body.
    if "Symbol" not in text.split("\n", 1)[0]:
        if day >= date.today():
            print(f"  {day}: not published yet, falling back")
        else:
            print(f"  {day}: unexpected content, not a threshold file")
        return None
    return text


def parse_file(text):
    """({canonical ticker: (name, category)} for our watchlist, all flagged).

    Format: Symbol|Security Name|Market Category|Threshold Flag|Rule 3210|Filler
    The trailing Filler field means rows end with a pipe.

    The second return value is every flagged symbol in the file, watchlist or
    not. It exists because this component's normal output is silence, and
    "nobody on our list" is otherwise indistinguishable from "the parse broke
    and nobody will ever be on our list" — a layout change here fails silently
    and forever. A plausible total is proof the file was actually read.
    """
    found, all_flagged = {}, []
    for line in text.split("\n")[1:]:
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        sym = canonical(parts[0])
        if parts[3].strip().upper() != "Y":     # Reg SHO Threshold Flag
            continue
        all_flagged.append(parts[0].strip().upper())
        if sym:
            found[sym] = (parts[1].strip(), parts[2].strip())
    return found, sorted(all_flagged)


def latest_file():
    """Most recent available file: (date, watchlist hits, all flagged symbols)."""
    for back in range(MAX_DAYS_BACK + 1):
        day = date.today() - timedelta(days=back)
        text = fetch_file(day)
        if text is not None:
            found, all_flagged = parse_file(text)
            return day, found, all_flagged
    return None, None, None


def count_run(symbol, latest_day):
    """Consecutive published files, ending at latest_day, listing this security.

    A missing file is a weekend or holiday, not a break in the run.
    """
    run, checked, back = 1, 0, 1
    while checked < RUN_LOOKBACK_FILES and back < RUN_LOOKBACK_FILES * 2:
        day = latest_day - timedelta(days=back)
        back += 1
        text = fetch_file(day)
        if text is None:
            continue
        checked += 1
        if symbol in parse_file(text)[0]:
            run += 1
        else:
            break
    return run


def build_embed(day, added, removed, current, details, runs):
    if added:
        colour, title = RED, "Added to Reg SHO threshold list"
    elif removed:
        colour, title = GREEN, "Removed from Reg SHO threshold list"
    else:
        colour, title = AMBER, "Reg SHO threshold list"

    # The block carries status and ticker ONLY. Company names and market tier
    # go in the description, where prose wraps harmlessly. An earlier version
    # appended the market category here and reached 36 characters against the
    # repo's 28-character limit — and this component is an exception report, so
    # the wrapped line would have been the only output it ever produced.
    lines = []
    for sym in sorted(added):
        lines.append(f"ADDED    {sym}")
    for sym in sorted(removed):
        lines.append(f"REMOVED  {sym}")
    for sym in sorted(set(current) - set(added)):
        lines.append(f"on list  {sym:<6}day {runs.get(sym, '?')}")

    desc = (f"Nasdaq settlement date {day:%Y-%m-%d}. A security joins after "
            f"five consecutive settlement days of fails-to-deliver above "
            f"10,000 shares and 0.5% of shares outstanding, which triggers "
            f"mandatory close-out obligations.\n\n"
            f"Rare and worth attention — but a listing reflects settlement "
            f"failures, which are not the same thing as short-seller pressure.")

    named = []
    for sym in sorted(added):
        cat = MARKET_CATEGORIES.get((details.get(sym) or ("", ""))[1], "")
        name = (details.get(sym) or (TICKERS.get(sym, ""), ""))[0]
        named.append(f"**{sym}** {name}" + (f" · {cat}" if cat else ""))
    for sym in sorted(removed):
        named.append(f"**{sym}** {TICKERS.get(sym, '')} — no longer listed")
    if named:
        desc += "\n\n" + "\n".join(named)

    return {
        "title": title,
        "description": desc,
        "color": colour,
        "fields": [{"name": "\u200b",
                    "value": "```\n" + "\n".join(lines) + "\n```"}],
        "footer": {"text": "Nasdaq Reg SHO threshold list"},
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


def main():
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.\n")
    elif not WEBHOOK_URL:
        sys.exit("No webhook set (WEBHOOK_URL_ALERTS or WEBHOOK_URL_MARKET).")

    print("Fetching Nasdaq threshold list...")
    day, found, all_flagged = latest_file()
    if day is None:
        sys.exit(f"No threshold file found in the last {MAX_DAYS_BACK} days. "
                 f"Check the URL pattern is still current.")

    # Always state the file-wide total. Zero here means the parse or the file
    # layout is broken, which otherwise looks exactly like a quiet day.
    sample = ", ".join(all_flagged[:4])
    print(f"Settlement date {day:%Y-%m-%d} — {len(all_flagged)} securities "
          f"flagged in the file" + (f" (e.g. {sample})" if sample else ""))
    if not all_flagged:
        sys.exit("Zero flagged securities in a valid file — the layout has "
                 "probably changed. Not treating this as a quiet day.")

    current = set(found)
    if current:
        for sym in sorted(current):
            name, cat = found[sym]
            print(f"  ON LIST: {sym} — {name} "
                  f"({MARKET_CATEGORIES.get(cat, cat)})")
    else:
        print("  no watchlist company on the list")

    # Distinguish "state loaded, nobody listed" from "no state file at all".
    # Both render as an empty set, and the difference matters: if the state
    # file never persists, previous is empty on every run, so the first time a
    # watchlist company appears it would post an addition every single day.
    had_state = STATE_FILE.exists()
    state = load_state()
    previous = set(state.get("on_list") or [])
    # A COMPANY ALREADY ON THE LIST WHEN IT JOINS THE ROSTER IS NOT AN
    # ADDITION. It was listed before anyone here was looking, so reporting it
    # as "added" dates an event to the day we started watching. Treated as
    # already-known, which also means its eventual REMOVAL posts correctly.
    newly_watched = set(baseline(state, watchlist.tickers()))
    if newly_watched:
        previous, joining = fold_newly_watched(previous, current,
                                               newly_watched)
        print()
        print(summary("threshold_list", sorted(newly_watched),
                      {t: 1 for t in sorted(joining)}))
    added = current - previous
    removed = previous - current
    print(f"previously: {sorted(previous) or 'none'}"
          + ("" if had_state else f"  (no {STATE_FILE.name} — first run)"))

    if not (added or removed):
        print("No change. Nothing to post.")
        # A dry run saves nothing, so show what a post would look like. This
        # component is silent by design — without this its only output is
        # unpreviewable until the day it actually fires.
        if DRY_RUN:
            if current:
                runs = {sym: 0 for sym in current}
                print("\nDry run: nothing changed, but this is the shape of a "
                      "post.\n")
                print(build_embed(day, set(), set(), current, found, runs)
                      ["fields"][0]["value"])
            else:
                print("\nDry run: no watchlist company is listed, so a post "
                      "would have nothing to show. The embed is only "
                      "previewable when at least one is on the list.")
        if not DRY_RUN and state.get("last_date") != day.isoformat():
            state["last_date"] = day.isoformat()
            save_state(state)
            print(f"State written: {STATE_FILE.name} "
                  f"(on_list empty, last_date {day:%Y-%m-%d})")
        return

    # Runs cost one request per prior file, so only count them on a change.
    runs = {sym: count_run(sym, day) for sym in current - added}

    embed = build_embed(day, added, removed, current, found, runs)
    print()
    print(embed["fields"][0]["value"])

    if DRY_RUN:
        print(f"\nDry run: would post — added {sorted(added) or 'none'}, "
              f"removed {sorted(removed) or 'none'}. State not saved.")
        return

    if post(embed):
        state["on_list"] = sorted(current)
        state["last_date"] = day.isoformat()
        save_state(state)
        print(f"State written: {STATE_FILE.name} "
              f"(on_list {sorted(current) or 'empty'})")
        print(f"Posted. Added {sorted(added) or 'none'}, "
              f"removed {sorted(removed) or 'none'}.")
    else:
        sys.exit("Post failed; state not saved so it retries next run.")


if __name__ == "__main__":
    main()
