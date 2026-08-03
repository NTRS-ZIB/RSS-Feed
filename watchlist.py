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
        # [1] CONFIRMED by a 3-year audit: in use 2023-07-17 to 2024-04-29,
        # replaced by 05759B305 on 2024-05-01. That is the 1-for-25 reverse
        # split effective 29 Apr 2024 — NOT the Nov 2025 reorganisation, which
        # changed no identifier. The 8-K12B filed at that reorganisation quotes
        # this CUSIP, by then eighteen months stale. The data establishes it;
        # the filing did not.
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
        # [1] pre-reverse-split, in use to 2023-10-13. Corroborated
        # independently by the dilution tracker, which found the share count
        # dropping 22.2:1 across the same window from XBRL — a different
        # dataset reaching the same conclusion.
        "cusips": ["583543301", "583543103"],
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
        # [1] the Digihost-era identifier, in use to 2025-03-06. Note the
        # ISSUER prefix changes — 25381D to 25380B — not just the issue number,
        # so this was an issuer-level reassignment rather than a split. Found
        # only after DGHI was added to alt_symbols: the audit needs one of the
        # two to resolve the other. See the two-pass note in docs/watchlist.md.
        "cusips": ["25380B102", "25381D206"],
        # Digihost Technology -> Digi Power X. Name change effective
        # 2025-03-06, Nasdaq ticker DGHI -> DGXX on 2025-03-18. DGHIZZZZ is
        # not a ticker: NSCC uses a ZZZZ suffix as a placeholder while a symbol
        # change processes, and it appears for exactly one settlement day
        # between the two. Listed because it occurs in the data.
        "alt_symbols": ["DGHI", "DGHIZZZZ"],
        "ir_feed": None,                  # renders client-side; EDGAR only
    },
    {
        "ticker": "WULF",
        "name": "TeraWulf",
        # A 1999-era CIK on a company incorporated in Delaware in February
        # 2021. TeraWulf came public by merging into IKONICS Corporation in
        # December 2021 rather than through an IPO, so it continues that
        # registrant. The low number is correct, not the wrong entity.
        "cik": "0001083301",
        # Observed 2021-12-16 to 2026-07-13 by a 120-period sweep, unbroken.
        # It starts AT the IKONICS merger rather than before it — nothing
        # under this company trades earlier — so there is no retired
        # identifier to carry, and this is a measured absence rather than an
        # unexamined one.
        "cusips": ["88080T104"],
        # IKONICS traded as IKNX. The 120-period sweep reaches 2021-07, past
        # the December 2021 merger, and never saw it against this company. It
        # predates every lookback window in any case.
        "alt_symbols": [],
        # Linked as "News RSS" at the foot of the press releases page. Same
        # /news-events/press-releases/rss pattern as MARA.
        "ir_feed": "https://investors.terawulf.com/news-events/press-releases/rss",
    },
    {
        "ticker": "HUT",
        "name": "Hut 8 Corp",
        # NOT 0001731805. That is Hut 8 Mining Corp, a British Columbia
        # company that filed 6-Ks as a foreign private issuer, and it is now
        # dormant. In November 2023 it combined with US Bitcoin Corp under a
        # newly formed Delaware parent, Hut 8 Corp, which files 10-Ks under
        # this CIK. The ticker did not change — both entities traded as HUT —
        # so nothing in alt_symbols catches this, and pinning the old CIK
        # returns no filings and no error. See docs/watchlist.md.
        "cik": "0001964789",
        # [1] the Hut 8 Mining Corp identifier, in use to 2023-12-04 and
        # replaced by [0] the same day. Note the ISSUER prefix changes —
        # 44812T to 44812J — not just the issue number, so this is an
        # issuer-level reassignment rather than a split. That is the
        # combination above, visible in the data: a new registrant, not a
        # renamed one. Found by a 120-period sweep; a 48-period one reached
        # only 2024-07 and saw a single unbroken identifier.
        "cusips": ["44812J104", "44812T102"],
        # HUTZZZZ is not a ticker. NSCC uses a ZZZZ suffix while a symbol
        # change processes; it appears for the single settlement day of the
        # changeover, 2023-12-04. Same placeholder as DGXX's DGHIZZZZ. Listed
        # because it occurs in the data — and it is the only symbol-side trace
        # of the combination, since HUT itself never changed.
        "alt_symbols": ["HUTZZZZ"],
        # No feed anywhere on hut8.com: none linked from the press releases
        # page, and no RSS entry under investor resources — unlike WULF and
        # CIFR, which both publish one. NOT the BGDE/WYFI/DGXX case: those
        # render client-side, whereas Hut 8's releases render server-side and
        # come back complete in a plain HTTP fetch. So this None means "no
        # feed to poll", not "not covered" — press_monitor.py scrapes the page
        # instead, in scrape_hut8(), and the items rejoin the same path the
        # feeds use. HUT is the only company covered that way.
        "ir_feed": None,                  # no feed; scraped, see scrape_hut8()
    },
    {
        "ticker": "CIFR",
        # Cipher Mining -> Cipher Digital Inc. Name change effective
        # 2026-02-24, announced in the Q4 2025 business update alongside the
        # divestment of 49% of the Alborz, Bear and Chief mining sites. The
        # ticker did not change, so nothing goes in alt_symbols; the IR domain
        # moved from ciphermining.com to cipherdigital.com.
        "name": "Cipher Digital",
        "cik": "0001819989",
        # Observed 2021-08-30 to 2026-07-10 by a 120-period sweep, unbroken.
        # It starts days after the August 2021 combination and nothing under
        # this company trades earlier, so there is no SPAC-era identifier to
        # carry. A measured absence, not an unexamined one.
        "cusips": ["17253J106"],
        # Formerly Good Works Acquisition Corp, a SPAC trading as GWAC until
        # the August 2021 business combination. The 120-period sweep reaches
        # 2021-07 and never saw GWAC against this company; it predates every
        # lookback window in any case.
        "alt_symbols": [],
        # Listed on the RSS Feeds page under Investor Resources. Same
        # /rss/news-releases.xml pattern as VIP.
        "ir_feed": "https://investors.cipherdigital.com/rss/news-releases.xml",
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

    # The alt column sizes to its contents. A fixed :8 field silently ran into
    # the feed column once DGXX carried DGHI,DGHIZZZZ at 13 characters, and any
    # fixed width just moves that break to the next company that earns a third
    # alternate. +2 keeps a visible gap; the rule separator follows suit.
    alts = {c["ticker"]: ",".join(c["alt_symbols"]) or "-" for c in rows}
    alt_w = max(len("alt"), max(len(a) for a in alts.values())) + 2
    width = 6 + 12 + 11 + alt_w + 5 + 1 + max(len(c["name"]) for c in rows)

    print(f"{len(rows)} companies\n")
    print(f"{'':6}{'CIK':12}{'CUSIP':11}{'alt':{alt_w}}{'feed':5} name")
    print("-" * width)
    for c in rows:
        # 'pending' rather than cusips[0]: a company added before its first
        # audit sweep has none, and indexing crashed the roster's own display.
        print(f"{c['ticker']:6}{c['cik']:12}"
              f"{(c['cusips'][0] if c['cusips'] else 'pending'):11}"
              f"{alts[c['ticker']]:{alt_w}}"
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
