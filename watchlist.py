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
        # [1] is pre-reverse-split, in use 2021-09-15 to 2023-05-12 and found
        # only by a 120-period sweep. Same issuer prefix 39531G, and the
        # description reads "GREENIDGE GENERATION HLDGS INC" — the pre-rename
        # name against an identifier this company still owns.
        "cusips": ["39531G308", "39531G100"],
        "alt_symbols": ["GREE"],          # Greenidge Generation, until 2026-07-24
        "ir_feed": "https://ir.vulcanip.com/rss/news-releases.xml",
    },
    {
        "ticker": "ANY",
        "name": "Sphere 3D",
        "cik": "0001591956",
        # [1] and [2] are both pre-reverse-split, and [2] was found only by a
        # 120-period sweep — a 72-period one reached 2023-08 and saw an
        # unbroken pair. All three share the issuer prefix 84841L, so this is
        # one company across two corporate actions rather than two issuers.
        # Confirmed by description: 84841L308 reads "SPHERE 3D CORP NEW COM
        # SHS (CD", in use 2021-07-15 to 2023-06-29.
        "cusips": ["84841L506", "84841L407", "84841L308"],
        # ANYZZZZ is not a ticker — the NSCC placeholder for a symbol change in
        # progress, occupying the single settlement day of the 84841L308 ->
        # 84841L407 changeover, 2023-06-29. Same placeholder as DGXX's
        # DGHIZZZZ. Listed because it occurs in the data.
        "alt_symbols": ["DRK", "ANYZZZZ"],   # DRK pending, ANYZZZZ historical
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
        # Mechanical Technology Inc, until 2021-11-04. Found by a 120-period
        # sweep via the pinned pre-split CUSIP 583543103, whose description
        # reads "MECHANICAL TECHNOLOGY INC COM" over 2021-07-19 to 2021-11-04
        # and "SOLUNA" after — a rename against an unchanged identifier, which
        # is the textbook case. This is the OLDEST rename on the roster and
        # sits outside every component's lookback window; it matters only to
        # an unbounded FTD_REPLAY.
        "alt_symbols": ["MKTY"],
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
        # [2] and [3] were found only by a 120-period sweep. All four share the
        # issuer prefix 57778N — one company across three corporate actions,
        # not four issuers — and both new entries read "MAWSON INFRASTRUCTURE
        # GROUP" in the SEC's description field: 57778N109 in use 2021-07-16
        # to 2021-07-28, 57778N208 to 2023-02-06.
        "cusips": ["57778N406", "57778N307", "57778N208", "57778N109"],
        # Three settlement-line markers, none of them a ticker, all reading
        # "MAWSON INFRASTRUCTURE GROUP" in the description:
        #   MIGIZZZZ  2023-02-09, on the NEW CUSIP 57778N307 — the changeover
        #   MIGIXXXX  2023-02-10, on the OLD CUSIP 57778N208 — the tail
        #   MIGID     2021-08-17 to 2021-09-13, on 57778N208, alongside MIGI
        # MIGID and MIGIXXXX surfaced only after 57778N109 and 57778N208 were
        # pinned — the two-pass bootstrap firing a second time on a company
        # that had been on the roster for months.
        "alt_symbols": ["MIGI", "MIGIZZZZ", "MIGIXXXX", "MIGID"],
        # THE NEWSWIRE'S feed, not the company's newsroom — the first of its
        # kind in this roster. BGDE's own newsroom renders client-side and
        # cannot be read, but it distributes through GlobeNewswire, which
        # publishes a per-organization feed. The wire also publishes first and
        # the newsroom mirrors it, so this is the earlier source, not a
        # substitute for a missing one.
        #
        # The token is opaque and cannot be derived from the company name. It
        # has to be read off an individual release page, where GlobeNewswire
        # embeds a "Subscribe via RSS" control — organization pages carry no
        # feed link and no autodiscovery at all.
        #
        # One token spans both eras: the same organization holds the Mawson
        # Infrastructure releases and the Big Digital Energy ones, so the
        # rename did not split the history.
        #
        # Verified first-party: all 20 items are BGDE's own releases, with no
        # third-party or paid content mixed in, so nothing needs filtering.
        "ir_feed": "https://www.globenewswire.com/rssfeed/organization/z9WJvxXYqqA-t7lWEcsvqw==",
    },
    {
        "ticker": "WYFI",
        "name": "WhiteFiber",
        "cik": "0002042022",
        "cusips": ["G96115103"],          # CINS: G prefix, non-US issuer
        "alt_symbols": [],
        # NOT on whitefiber.com. That newsroom is a Webflow shell that renders
        # client-side and carries no headlines in its HTML, so anyone checking
        # the company's own domain concludes no feed exists — which is what was
        # concluded here twice. The feed lives on a SEPARATE IR PLATFORM HOST,
        # whitefiber.investorroom.com, reachable only by following the
        # autodiscovery <link> out of that shell.
        #
        # Shallow at five items, against ten or twenty elsewhere. That is the
        # platform's window, not a fault, and it is ample against a 15-minute
        # schedule and a 7-day age floor.
        #
        # Verified QUIET, not stale: newest item was 25 days old when added, and
        # every WYFI filing since 2026-07-01 is a Form 4 or an 8-K with no EX-99
        # exhibit, so no release has been missed. Check that before concluding a
        # feed has died — see the DGXX case in docs/press-monitor.md.
        "ir_feed": "https://whitefiber.investorroom.com/index.php?s=43&pagetemplate=rss",
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
        # HSSHD carries the already-pinned CUSIP 25381D206 and the description
        # "DIGIHOST TECHNOLOGY INC", so it is certainly this company. It runs
        # 2021-10-28 to 2021-11-12, eleven rows, immediately before DGHI first
        # appears on 2021-11-16.
        #
        # WHAT THE `D` SUFFIX MEANS IS NOT ESTABLISHED. The obvious reading —
        # a pre-Nasdaq line replaced by DGHI — does not survive the parallel
        # case: BGDE carries MIGID over 2021-08-17 to 2021-09-13 *while MIGI
        # is trading*, so the suffix is not a predecessor symbol there. It is
        # a settlement-line marker of some kind, lasting weeks rather than the
        # single day a ZZZZ placeholder occupies. Recorded because it occurs
        # in the data; not explained, because nothing here has explained it.
        "alt_symbols": ["DGHI", "DGHIZZZZ", "HSSHD"],
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
        # HUTXXXX is the other half of the same changeover and was missed until
        # a 120-period sweep. HUTZZZZ marks the switch on 2023-12-04; HUTXXXX
        # then runs 2023-12-05 to 2023-12-14 against the OLD CUSIP 44812T102,
        # whose description still reads "HUT 8 MNG CORP (CANADA)" — the
        # predecessor's rows draining after the successor had taken over. So
        # the two markers are not interchangeable: ZZZZ is the transition,
        # XXXX is the tail on the retired line.
        "alt_symbols": ["HUTZZZZ", "HUTXXXX"],
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
    {
        "ticker": "GLXY",
        "name": "Galaxy Digital",
        # NOT 0001405064. That is Galaxy Digital Holdings Ltd., the Cayman
        # entity that listed in Toronto, and it is this redomiciliation's
        # HUT-shaped trap: it is named "Galaxy Digital", it appears first in an
        # EDGAR name search, and it has NEVER filed a periodic report — only
        # 425s, the last on 2025-05-06. Pinning it returns an empty filing list
        # and no error.
        #
        # This CIK is the one that files. Registered 2021-05-05 as Galaxy
        # Digital Pubco Inc. and renamed 2021-09-14, it became the reporting
        # parent at the US listing: 8-A12B and CERT both 2025-05-15, first 10-Q
        # 2025-05-13, first 10-K 2026-02-26, most recent 8-K 2026-08-05.
        # Confirmed against a 10-Q accession (0001859392-26-000054), not
        # against the ticker.
        #
        # Thirty-four registrants match "galaxy digital" in EDGAR. All but
        # these two are funds, LPs and 13F filers; none files a periodic
        # report, so "which one files today" separates them cleanly.
        "cik": "0001859392",
        # Observed 2025-05-19 to 2026-07-13 by a 120-period sweep, unbroken,
        # and named "GALAXY DIGITAL INC CL A (DE)" in the SEC's own files —
        # the (DE) is the redomiciliation, visible in the identifier.
        #
        # It starts three trading days after the Nasdaq listing and nothing
        # trades under this company earlier, because the Cayman predecessor
        # traded in TORONTO and never appears in US fails data at any depth.
        # So there is no retired identifier to carry, and that is a measured
        # absence rather than an unswept one.
        "cusips": ["36317J209"],
        "alt_symbols": [],
        # ON THE IR HOST, NOT www.galaxy.com — and the company newsroom is
        # ALSO read, by scrape_galaxy(). GLXY is the only company on this
        # roster covered two ways at once, because the two carry different
        # populations: this feed has the financial and material releases (Q2
        # results, the $3.507bn notes pricing, the ERCOT 830 MW Helios
        # approval), and the newsroom has the on-domain corporate
        # announcements. Neither is a superset.
        #
        # The overlap is deduped per run by suppress_cross_host(); six of ten
        # feed items had a newsroom twin when this was measured.
        #
        # Found on 2026-08-08 in an href on the newsroom page that had already
        # been parsed many times. Autodiscovery finds NOTHING on this host.
        "ir_feed": "https://investor.galaxy.com/rss/news-releases.xml",
    },
    {
        "ticker": "APLD",
        "name": "Applied Digital",
        # A 2001-era CIK on a company that took this name in 2023: Reel Staff
        # -> Flight Safety Technologies -> Applied Science Products -> Applied
        # Blockchain (2021-04) -> Applied Digital (2023-02). One registrant
        # throughout, so the low number is correct rather than a wrong entity —
        # the same shape as WULF's 1999-era CIK.
        #
        # formerNames carries a FIFTH row that reads like a rename and is not
        # one: "Applied Digital Corp." — the current name — from 2023-02-09 to
        # 2026-08-04, an end date of yesterday. The 10-K filed 2026-07-29
        # (0001144879-26-000048) carries the conformed name "Applied Digital
        # Corp.", and the ticker and exchange are unchanged. An end date on a
        # formerNames row is an EDGAR record refresh, not evidence of a rename.
        "cik": "0001144879",
        # [1] retired 2022-04-13, replaced by [0] on 2022-04-18 at the Nasdaq
        # uplisting — the same week as the 424B4. The ISSUER prefix does not
        # move (038169 both sides), only the issue number, so this is a
        # corporate action on one issuer rather than a reassignment. Contrast
        # HUT and DGXX, where the prefix itself changed.
        #
        # The 2023 rename is visible in the description against an UNCHANGED
        # identifier: 038169207 reads "APPLIED BLOCKCHAIN INC COM NEW" in
        # 2022-05 and "APPLIED DIGITAL CORP COM NEW" from 2024-02. That is the
        # rule in this file's header demonstrated in data — a CUSIP survives a
        # rename but not a corporate action.
        "cusips": ["038169207", "038169108"],
        # None. The symbol was APLD across both eras — a 120-period sweep sees
        # it from 2021-07-29, in the Applied Blockchain era, unbroken to today.
        # So the four earlier NAMES on this CIK never traded under a symbol
        # this window reaches, and none is recorded from the filing that lists
        # them.
        "alt_symbols": [],
        # Autodiscovered from a <link rel="alternate"> on the newsroom page.
        # RECORDED AS AUTODISCOVERED RATHER THAN CONSTRUCTED, deliberately:
        # this platform returns BYTE-IDENTICAL responses for /rss,
        # /rss/news-releases.xml and /rss/pressrelease.aspx — 7,741 bytes each
        # — so it serves the feed for anything under /rss. A constructed URL
        # that works today is not evidence the platform means it, and path
        # guessing here cannot tell a real endpoint from a soft match.
        "ir_feed": "https://ir.applieddigital.com/news-events/press-releases/rss",
    },
    {
        "ticker": "BTDR",
        "name": "Bitdeer Technologies",
        "cik": "0001899123",
        # CINS: G prefix, non-US issuer, same as WYFI's G96115103. Observed
        # 2023-04-14 to 2026-07-13 by a 120-period sweep, unbroken from the
        # listing date onward — its whole life as a US-traded security, so
        # there is nothing earlier to miss.
        "cusips": ["G11448100"],
        "alt_symbols": [],
        # FOREIGN PRIVATE ISSUER — confirmed from the filing record, not from
        # the address: 99 6-Ks and 5 20-Fs in the recent block, no 10-K and no
        # 8-K at any point, first 20-F 2023-04-19. State of incorporation E9
        # (Cayman Islands), operations in Singapore. So it behaves like IREN
        # and DGXX, and the earnings calendar reaches it through its 20-F/6-K
        # fallback rather than through 10-K/8-K.
        #
        # AT THE HOST ROOT, NOT UNDER THE NEWSROOM PATH. The newsroom is
        # /news-events/news-releases, which looks like the Equisolve shape
        # MARA and WULF use, and /news-events/news-releases/rss returns
        # NOTHING. The feed is the gcs-web shape at the root, same as ANY,
        # BKKT, CIFR, IREN and VIP. There is no <link rel="alternate"> on the
        # page at all; a footer anchor to /rss-feeds is the only pointer.
        #
        # BTDR distributes through GlobeNewswire — a recent dateline names it
        # — and still serves its own feed from its own host. That is the good
        # case and worth distinguishing from BGDE, where only the WIRE's
        # organisation feed existed, with an opaque token readable solely from
        # an individual release page.
        "ir_feed": "https://ir.bitdeer.com/rss/news-releases.xml",
    },
    {
        "ticker": "SPCX",
        "name": "Space Exploration Technologies",
        # The CIK dates to 2002 and the public company does not. It is a
        # long-dormant private-placement filer — REGDEX and Form D from
        # 2002-08-19 onward — that became a reporting company at the IPO. No
        # formerNames, so the registrant is continuous and this is the same
        # entity throughout.
        "cik": "0001181412",
        # ONE identifier, not the two the sweep proposed. 84615Q103 is
        # "SPACE EXPL TECHNOLOGIES CORP C" and runs 2026-06-15 to 2026-07-14,
        # from three days after the IPO.
        #
        # CRITICAL: the sweep also reported 19423L672 under this ticker,
        # 2021-07-16 to 2026-04-07, and it is NOT this company. The SEC's own
        # description names it "COLLABORATIVE INVT SER TR SPAC" — a SPAC ETF
        # that held the ticker SPCX until April 2026, two months before this
        # company existed as a security. THE TICKER WAS RECYCLED, and a
        # recycled ticker is indistinguishable from a rename in the three
        # columns audit_identifiers.py reads.
        #
        # Nothing flagged it. The COLLISIONS check needs a row whose symbol and
        # CUSIP name different companies, and with "cusips": [] there was no
        # pin to collide with — so a brand-new company is exactly the case that
        # check cannot cover. It was caught by reading the DESCRIPTION column
        # of the same files, which the audit does not parse. Do that before
        # accepting any identifier that predates a company's own listing.
        "cusips": ["84615Q103"],
        # Deliberately empty, and it must stay that way. The pre-IPO SPCX rows
        # belong to that ETF, so SPCX is a symbol this company shares with a
        # dead security rather than one it inherited.
        "alt_symbols": [],
        # UNDER TWO MONTHS PUBLIC, and that is a property of the roster rather
        # than a temporary inconvenience. 8-A12B and CERT 2026-06-10, 424B4
        # 2026-06-12, first 8-K 2026-06-15. Its FIRST AND ONLY 10-Q was filed
        # 2026-08-04 for the period ended 2026-06-30; there is no 10-K.
        #
        # What that costs, per component:
        #   - crossings.py SKIPS IT ENTIRELY. MIN_BARS is 60 and the IPO is
        #     ~37 sessions back, so it lands in `missing` and is printed as
        #     "N bar(s) — too few, skipped". In the embed it joins "No data
        #     this run", alongside genuine feed failures — the one place this
        #     reads as a fault rather than as a young listing. It starts
        #     reporting about 2026-09-08 and carries the `~` shorter-window
        #     mark until roughly 2027-06.
        #   - dilution.py reports it as `-` with a `~`, and says why in the
        #     footer: "under a year of reported history". `year_reason` is
        #     "thin", which the component distinguishes from "split" precisely
        #     so a young company does not read as a corporate action. Nothing
        #     is wrong here; the trailing-year figure simply begins mid-2027.
        #   - the staleness check needs STALE_MIN_DAYS (4) distinct publication
        #     days before it will judge a source. That does not bite yet
        #     because there is no feed to judge — it becomes the first thing to
        #     check if one is added.
        # The same Q4 endpoint CLSK and NUAI already use. `default.aspx` on
        # the newsroom URL is that platform's page naming, not a different
        # platform — it looks like a third shape and is not.
        #
        # WEAKER EVIDENCE THAN THE OTHER TWO, AND THE DIFFERENCE IS RECORDED
        # RATHER THAN ROUNDED OFF. Every feed added here is checked against
        # the newsroom page it claims to mirror, because a dead feed matches
        # today's date for ninety days. SPCX's newsroom ships ZERO dates in
        # its delivered HTML, so that check could not run: the feed is fresh
        # by absolute date and UNCONFIRMED AGAINST ITS SOURCE. Seven items is
        # consistent with a 2026-06 listing, which is corroboration and not
        # verification. This is the one that most wants check_staleness()
        # watching it.
        "ir_feed": "https://ir.spacex.com/rss/pressrelease.aspx",
    },
    {
        "ticker": "ABTC",
        "name": "American Bitcoin",
        # NOT 0002068580, which EDGAR ALSO names "American Bitcoin Corp." That
        # is the private company that came through the reverse merger; its only
        # filing is a Form D on 2025-07-09 and it files no periodic reports.
        # Two live registrants under one name is HUT's silent failure reached
        # by a different route — a name search alone cannot separate them.
        #
        # The reporting registrant is a 2018 SPAC renamed three times: MTech
        # Acquisition Holdings (2018-11) -> Akerna (2018-12) -> Gryphon Digital
        # Mining (2024-02) -> American Bitcoin (2025-09-03). The registrant
        # continues across all of them — a succession, not a new one — so a CIK
        # seven years older than the company is correct. Confirmed against a
        # 10-Q accession, 0001193125-26-329472, filed 2026-08-03 for the period
        # ended 2026-06-30.
        "cik": "0001755953",
        # FIVE identifiers across four issuer prefixes, and every one of them
        # is this registrant. The longest chain on the roster, and the reason
        # the two-pass note in docs/watchlist.md is a floor rather than a rule:
        # a pinned CUSIP bridges ONE rename per pass, and this took four.
        #
        #   00973W102  AKERNA CORP COM          2021-07-15 to 2022-11-04
        #   00973W300  AKERNA CORP COM NEW      2022-11-10 to 2024-02-08
        #   400510103  GRYPHON DIGITAL MNG INC  2024-02-13 to 2025-09-02
        #   02462A104  AMERICAN BITCOIN CORP    2025-09-04 to 2026-07-06
        #   02462A203  AMERICAN BITCOIN CL A NEW  2026-07-06 onward
        #
        # The ranges abut with no overlap and no unexplained gap, each
        # description names the company EDGAR's formerNames says held the CIK
        # at that date, and the two 00973W and two 02462A pairs are ordinary
        # corporate actions within one issuer. Note the prefix changes at both
        # renames — 00973W -> 400510 -> 02462A — so nothing here could have
        # been inferred from the identifiers alone.
        #
        # 2021-07-15 is where the 120-period window opens, not where Akerna
        # begins. An earlier identifier may exist and has not been swept.
        "cusips": ["02462A203", "02462A104", "400510103",
                   "00973W300", "00973W102"],
        # ABTCZZZZ is not a ticker. NSCC uses a ZZZZ suffix while a symbol
        # change processes, and here it occupies the single settlement day of
        # the CUSIP changeover, 2026-07-06 — the same placeholder as DGXX's
        # DGHIZZZZ and HUT's HUTZZZZ. Listed because it occurs in the data.
        #
        # GRYP and KERN are this registrant's earlier symbols, and the dates
        # abut with no overlap and no gap that matters:
        #
        #   KERN  AKERNA CORP COM            .. 2024-02-08
        #   GRYP  GRYPHON DIGITAL MNG INC    2024-02-13 .. 2025-09-02
        #   ABTC  AMERICAN BITCOIN CORP      2025-09-04 ..
        #
        # against EDGAR's formerNames on this CIK — Akerna to 2024-02-13,
        # Gryphon to 2025-09-03. Two independent records agreeing, which is
        # the standard HUT was established to.
        #
        # Checked in the other direction too, because that is the SPCX lesson
        # reversed: neither symbol appears in 2026-06 or 2026-07, so neither
        # has been recycled by another company since being released.
        #
        # MTEC, the 2018-19 SPAC symbol, sits outside a 120-period window
        # altogether and cannot be established from these files at any depth
        # they reach. That absence is unswept, not measured.
        "alt_symbols": ["ABTCZZZZ", "GRYP", "KERN"],
        "ir_feed": None,                  # no feed; Sanity CMS, read_abtc()
    },
    # EVERY None ABOVE IS A MEASURED ABSENCE OF A FEED ON THE COMPANY'S OWN
    # NEWSROOM, and every one of those companies is still covered by something
    # faster than EDGAR. "Not looked for" no longer exists on this roster.
    #
    #   DGXX  renders client-side; public Strapi CMS, read_dgxx()
    #   HUT   no feed; server-rendered, scrape_hut8()
    #   GLXY  no feed on www.galaxy.com; server-rendered, scrape_galaxy() —
    #         but SEE ITS ir_feed ABOVE: the IR host has one, and both are
    #         read
    #   ABTC  client-rendered scroll; public Sanity CMS, read_abtc()
    #
    # GLXY is covered BOTH ways and is the only company that is — its
    # ir_feed is set and scrape_galaxy() also runs. See the note on its entry.
]

# --------------------------------------------------------------- REFUSALS ---

# Identifiers that LOOK like they belong to a company on this roster and do
# not. Every entry has been proposed by audit_identifiers.py and rejected
# against the SEC's own description field.
#
# THIS LIST EXISTS BECAUSE THE PROPOSAL RECURS. The audit reads
# date|cusip|symbol and nothing else, so it cannot see that a ticker changed
# hands; it will re-propose every one of these on every future run, for as long
# as the sweep window reaches them. A note in a comment would leave the roster
# defended by whoever reads the verdict most carefully that day. This is the
# decision recorded once: audit_identifiers.py prints these as `ref` rather
# than `NEW`, and ftd_monitor.py refuses to learn them into ftd_state.json.
#
# `handover` is the LAST date the other security traded under `symbol`. It is
# what lets a replay reaching further back find nothing rather than find
# somebody else's rows — see symbol_handover().

REFUSED = [
    {
        "cusip": "19423L672",
        "symbol": "SPCX",
        "belongs_to": "Collaborative Investment Series Trust",
        "seen": ("2021-07-16", "2026-04-07"),
        "handover": "2026-04-07",
        "why": (
            "A SPAC ETF held the ticker SPCX until 2026-04-07. Space "
            "Exploration Technologies had no security of any kind before its "
            "8-A12B on 2026-06-10 and IPO'd on 2026-06-12, so an identifier "
            "trading from 2021 cannot be its. The SEC's own description "
            "settles it without inference: this one reads COLLABORATIVE INVT "
            "SER TR SPAC, while SPCX's real identifier 84615Q103 reads SPACE "
            "EXPL TECHNOLOGIES CORP C. The ticker was RECYCLED, which looks "
            "exactly like a rename in the three columns the audit reads."
        ),
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


def refused_cusips():
    """{'19423L672': record} — identifiers rejected against SEC descriptions.

    Consumers use this to tell "not seen before" from "seen, checked and
    refused". The two are indistinguishable without it, which is how a
    recycled ticker gets adopted on the third or fourth reading of a verdict.
    """
    return {r["cusip"]: r for r in REFUSED}


def symbol_handover():
    """{'SPCX': '20260407'} — the last date a symbol meant SOMEBODY ELSE.

    A consumer filtering a bulk file by symbol must ignore rows dated at or
    before this, or it attributes the previous holder's rows to the current
    one. Compact YYYYMMDD, matching the SEC fails files' own date format, so a
    plain string comparison orders correctly and no date parsing is needed —
    this file imports `sys` and nothing else, deliberately.

    A symbol absent from this map has no known handover, and `.get(sym, "")`
    then compares less than every real date, so nothing is skipped.
    """
    out = {}
    for r in REFUSED:
        if not r.get("handover"):
            continue
        stamp = r["handover"].replace("-", "")
        # If one symbol has changed hands more than once, the latest wins.
        if stamp > out.get(r["symbol"], ""):
            out[r["symbol"]] = stamp
    return out


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

    # A refusal that contradicts the roster is worse than no refusal at all:
    # one of the two says a CUSIP belongs to a company and the other says it
    # belongs to somebody else, and nothing downstream can decide which.
    for r in REFUSED:
        for field in ("cusip", "symbol", "belongs_to", "handover", "why"):
            if not r.get(field):
                problems.append(f"REFUSED {r.get('cusip', '?')}: missing {field!r}")
        cu = r.get("cusip", "")
        if len(cu) != 9 or cusip_check_digit(cu) != cu[8]:
            problems.append(f"REFUSED {cu!r} fails its check digit")
        if cu in seen_cusips:
            problems.append(
                f"REFUSED {cu!r} is ALSO claimed by {seen_cusips[cu]} — a "
                f"refused identifier cannot be a company's own")

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

    # Printed rather than hidden: the whole point of the list is that the next
    # reader sees a decision already taken instead of re-deriving it from an
    # audit verdict.
    if REFUSED:
        print(f"\nrefused identifiers ({len(REFUSED)}) — proposed by the audit "
              f"and rejected:")
        for r in REFUSED:
            print(f"  {r['cusip']}  traded as {r['symbol']} to "
                  f"{r['handover']} — {r['belongs_to']}")

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  {p}")
        return 1
    print("\nvalidation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
