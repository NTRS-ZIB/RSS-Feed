#!/usr/bin/env python3
"""
The watchlist. One record per company; every component derives its own view.

WHY THIS EXISTS
Before this file the watchlist was defined eight times in five incompatible
shapes — ticker lists, ticker->name dicts, ticker->(cik, name) dicts, and two
alias maps pointing in OPPOSITE directions. Adding one company meant eight
edits, and getting an alias backwards merges two companies' data under a
plausible number with no error anywhere (see docs/fails-to-deliver.md).

Run this file directly to validate and print the roster:

    python -u watchlist.py

WHAT BELONGS HERE
Facts about a company that more than one component needs: identifiers, names,
feeds. Nothing about how any component behaves — no thresholds, no schedules,
no webhooks. Those stay in the component that owns them.

WHAT DOES NOT BELONG HERE
Anything derivable. daily_recap.py previously carried a ticker -> Stooq symbol
map, but every value was `ticker.lower() + ".us"` — a transformation, not a
fact about the company. It belongs in the component as a function. If one
company ever needs an irregular provider symbol, that is when it earns a field.

IDENTIFIER NOTES
- `cik` is permanent and is what EDGAR is keyed on. Ten digits, zero-padded.
- `cusips[0]` is the CURRENT identifier. Later entries are retired ones, kept
  because historical files still carry them. A CUSIP survives a rename but NOT
  a reverse split, which is why ANY has two.
- `alt_symbols` covers former AND pending tickers. Consumers that query by
  symbol ask for all of them; consumers that filter a bulk file map all of them
  back to `ticker`. Both directions are derived below, so neither can be
  written backwards by hand.
"""

import sys

# ---------------------------------------------------------------- ROSTER ----

WATCHLIST = [
    {
        "ticker": "MARA",
        "name": "MARA Holdings",
        "cik": "0001507605",
        "cusips": ["565788106"],
        "alt_symbols": [],
        "ir_feed": "https://ir.mara.com/news-events/press-releases/rss",
    },
    {
        "ticker": "CLSK",
        "name": "CleanSpark",
        "cik": "0000827876",
        "cusips": ["18452B209"],
        "alt_symbols": [],
        "ir_feed": "https://investors.cleanspark.com/rss/pressrelease.aspx",
    },
    {
        "ticker": "BKKT",
        "name": "Bakkt Holdings",
        "cik": "0001820302",
        # [1] UNCONFIRMED BY DATA. Taken from the 8-K12B of 3 Nov 2025, which
        # states this CUSIP at the point New Bakkt became successor issuer.
        # But a 12-month sweep of the SEC fails files (2025-07 to 2026-07)
        # shows BKKT under 05759B305 throughout and never under this one — so
        # either it predates the sweep window or the filing refers to another
        # security. The issue number `10` suggests original common stock,
        # which would place it before the April 2024 reverse split.
        #
        # Kept because a stale pin is inert while a missing one loses data,
        # but it is not trusted until observed. probe_cusips.py with
        # SWEEP_PERIODS=48 would settle it: if it appears in 2024 files it is
        # the pre-split common and correct; if it never appears, remove it
        # rather than risk matching a different Bakkt security.
        "cusips": ["05759B305", "05759B107"],
        "alt_symbols": [],
        "ir_feed": "https://investors.bakkt.com/rss/news-releases.xml",
    },
    {
        "ticker": "NUAI",
        "name": "New Era Energy & Digital",
        "cik": "0002028336",
        "cusips": ["64428N109"],
        "alt_symbols": ["NEHC"],          # New Era Helium, until 2025-08-13
        "ir_feed": "https://investors.newerainfra.ai/rss/pressrelease.aspx",
    },
    {
        "ticker": "IREN",
        "name": "IREN Limited",
        "cik": "0001878848",
        "cusips": ["Q4982L109"],          # CINS: Q prefix, non-US issuer
        "alt_symbols": [],
        "ir_feed": "https://irisenergy.gcs-web.com/rss/news-releases.xml",
    },
    {
        "ticker": "VIP",
        "name": "Vulcan Infrastructure and Power",
        "cik": "0001844971",
        "cusips": ["39531G308"],
        "alt_symbols": ["GREE"],          # Greenidge Generation, until 2026-07-24
        "ir_feed": "https://ir.vulcanip.com/rss/news-releases.xml",
    },
    {
        "ticker": "ANY",
        "name": "Sphere 3D",
        "cik": "0001591956",
        "cusips": ["84841L506", "84841L407"],   # [1] is pre-reverse-split
        "alt_symbols": ["DRK"],           # pending change to DarkHorse
        "ir_feed": "https://sphere3d.gcs-web.com/rss/news-releases.xml",
    },
    {
        "ticker": "SLNH",
        "name": "Soluna Holdings",
        "cik": "0000064463",
        "cusips": ["583543301"],
        "alt_symbols": [],
        # WordPress. The /news/ archive feed, not the site-root blog feed that
        # autodiscovery finds — see docs/press-monitor.md.
        "ir_feed": "https://www.solunacomputing.com/news/feed/",
    },
    {
        "ticker": "BGDE",
        "name": "Big Digital Energy",
        "cik": "0001218683",
        # [1] retired 2025-11 (seen to 17 Nov, replaced by 24 Nov). Confirmed
        # by sweeping the SEC fails files, and corroborated independently: the
        # dilution tracker found the share count dropping 4.2:1 across the
        # same window.
        "cusips": ["57778N406", "57778N307"],
        "alt_symbols": ["MIGI"],          # Mawson Infrastructure, until 2026-04-30
        "ir_feed": None,                  # renders client-side; EDGAR only
    },
    {
        "ticker": "WYFI",
        "name": "WhiteFiber",
        "cik": "0002042022",
        "cusips": ["G96115103"],          # CINS: G prefix, non-US issuer
        "alt_symbols": [],
        "ir_feed": None,                  # renders client-side; EDGAR only
    },
    {
        "ticker": "DGXX",
        "name": "Digi Power X",
        "cik": "0001854368",
        "cusips": ["25380B102"],
        "alt_symbols": [],
        "ir_feed": None,                  # renders client-side; EDGAR only
    },
]

# ------------------------------------------------------------------ VIEWS ---


def tickers():
    """['MARA', 'CLSK', ...] — for components that need symbols only."""
    return [c["ticker"] for c in WATCHLIST]


def names():
    """{'MARA': 'MARA Holdings', ...}"""
    return {c["ticker"]: c["name"] for c in WATCHLIST}


def ciks():
    """{'MARA': ('0001507605', 'MARA Holdings'), ...} — EDGAR consumers."""
    return {c["ticker"]: (c["cik"], c["name"]) for c in WATCHLIST}


def alt_by_ticker():
    """{'VIP': ['GREE'], ...} — for APIs queried by symbol.

    Only companies with alternates appear.
    """
    return {c["ticker"]: list(c["alt_symbols"])
            for c in WATCHLIST if c["alt_symbols"]}


def symbol_to_ticker():
    """{'MARA': 'MARA', 'GREE': 'VIP', ...} — for filtering a bulk file.

    Includes the identity mapping, so a lookup resolves any symbol seen in the
    data. This is the exact inverse of alt_by_ticker() and is derived from the
    same source, so the two cannot disagree.
    """
    out = {c["ticker"]: c["ticker"] for c in WATCHLIST}
    for c in WATCHLIST:
        for alt in c["alt_symbols"]:
            out[alt] = c["ticker"]
    return out


def cusip_pins():
    """{'565788106': 'MARA', ...} — every CUSIP, current and retired."""
    return {cusip: c["ticker"] for c in WATCHLIST for cusip in c["cusips"]}


def ir_feeds():
    """{'MARA': url, ...} — only companies that publish one.

    Keyed by TICKER. The previous map was keyed by display label, a mix of
    tickers and company names, so nothing joined a feed to its company.
    """
    return {c["ticker"]: c["ir_feed"] for c in WATCHLIST if c["ir_feed"]}


# ------------------------------------------------------------- VALIDATION ---


def cusip_check_digit(cusip):
    """Modulus-10 double-add-double over the first 8 characters.

    Applies to CINS too, where a leading letter is valued A=10.
    """
    total = 0
    for i, ch in enumerate(cusip[:8]):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch.upper()) - ord("A") + 10
        else:
            v = {"*": 36, "@": 37, "#": 38}.get(ch, 0)
        if i % 2:
            v *= 2
        total += v // 10 + v % 10
    return str((10 - total % 10) % 10)


def validate():
    """Return a list of problems. Empty means the roster is internally sound.

    These checks are only possible because the data is in one place. Spread
    across eight files, a symbol claimed by two companies — the GREE->SLNH
    bug — is undetectable by construction.
    """
    problems = []
    seen_tickers, seen_cusips, claimed_alts = {}, {}, {}

    for c in WATCHLIST:
        t = c["ticker"]

        for field in ("ticker", "name", "cik", "cusips", "alt_symbols", "ir_feed"):
            if field not in c:
                problems.append(f"{t}: missing field {field!r}")

        if t in seen_tickers:
            problems.append(f"{t}: duplicate ticker")
        seen_tickers[t] = c

        cik = c.get("cik", "")
        if not (len(cik) == 10 and cik.isdigit()):
            problems.append(f"{t}: CIK {cik!r} is not 10 digits, zero-padded")

        if not c.get("cusips"):
            problems.append(f"{t}: no CUSIP")
        for cu in c.get("cusips", []):
            if len(cu) != 9 or cusip_check_digit(cu) != cu[8]:
                problems.append(f"{t}: CUSIP {cu!r} fails its check digit")
            if cu in seen_cusips and seen_cusips[cu] != t:
                problems.append(f"{t}: CUSIP {cu!r} also claimed by {seen_cusips[cu]}")
            seen_cusips[cu] = t

        for alt in c.get("alt_symbols", []):
            if alt in claimed_alts and claimed_alts[alt] != t:
                problems.append(
                    f"{alt!r} claimed as an alternate by both "
                    f"{claimed_alts[alt]} and {t} — these are different companies")
            claimed_alts[alt] = t

    for alt, owner in claimed_alts.items():
        if alt in seen_tickers and seen_tickers[alt]["ticker"] != owner:
            problems.append(
                f"{alt!r} is a live ticker AND an alternate of {owner} — "
                f"one of the two is wrong")

    return problems


def main():
    problems = validate()
    rows = sorted(WATCHLIST, key=lambda c: c["ticker"])
    print(f"{len(rows)} companies\n")
    print(f"{'':6}{'CIK':12}{'CUSIP':11}{'alt':8}{'feed':5} name")
    print("-" * 70)
    for c in rows:
        print(f"{c['ticker']:6}{c['cik']:12}{c['cusips'][0]:11}"
              f"{','.join(c['alt_symbols']) or '-':8}"
              f"{'yes' if c['ir_feed'] else '-':5} {c['name']}")

    print(f"\nderived: {len(cusip_pins())} CUSIP pins, "
          f"{len(alt_by_ticker())} companies with alternates, "
          f"{len(ir_feeds())} IR feeds")

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  {p}")
        return 1
    print("\nvalidation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
