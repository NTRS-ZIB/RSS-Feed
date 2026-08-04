#!/usr/bin/env python3
"""Re-derive the 8-K item distribution that justifies ALWAYS_POST_ITEMS.

WHAT THIS ANSWERS
`press_monitor.py` drops any 8-K whose items lack 2.02, 7.01 or 8.01, on the
grounds that no press release accompanied it. `ALWAYS_POST_ITEMS` exempts seven
item codes from that, and 5.02 is deliberately excluded from the exemption.

Those decisions rest on measurements — "1,986 filings said so" — and without
this tool there is no way for anyone to check them. This prints the distribution
they came from: how often each item code appears across every company's full
8-K history, how many of each the exhibit filter drops, what the current
always-post set actually rescues, and the concentration behind the 5.02 call.

WHEN TO RUN IT
- After adding or removing a company, since the distribution is only as good as
  the roster it was measured over.
- When someone disagrees with the seven, or wants an eighth added. The volume
  column is the argument.
- Before widening the exhibit filter in any other way.

HOW TO READ THE OUTPUT
`dropped` is the number of appearances with no 2.02/7.01/8.01 alongside — the
filings the exhibit filter removes. A high drop rate on a rare, material item is
the case for exempting it. A high drop rate on a frequent, routine one is the
case against, because the exemption would post all of it.

The sets are read from press_monitor at runtime rather than copied, so this
stays honest if they change.

Read-only. Reads the same EDGAR submissions endpoint the monitor already uses,
posts nothing, writes nothing. Needs SEC_USER_AGENT and no other secret.
"""

import os
import sys
import time
from collections import Counter, defaultdict

import requests

import press_monitor as pm
import watchlist

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"

# Item codes that are structural rather than newsworthy. 9.01 rides along with
# almost every filing that attaches anything, so it dominates any raw count and
# tells you nothing; it is called out separately rather than ranked.
STRUCTURAL = {"9.01"}


def sec_get(url):
    time.sleep(0.2)
    r = requests.get(url, headers={"User-Agent": SEC_USER_AGENT,
                                   "Accept-Encoding": "gzip, deflate"},
                     timeout=(10, 60))
    return r.json() if r.status_code == 200 else None


def filings():
    """Every 8-K across the roster: (ticker, date, form, {item codes})."""
    out = []
    for ticker, (cik, name) in watchlist.ciks().items():
        data = sec_get(SUBMISSIONS.format(cik=cik))
        if not data:
            print(f"  {ticker}: submissions unavailable")
            continue
        chunks = [data["filings"]["recent"]]
        for extra in data["filings"].get("files", []):
            older = sec_get(OLDER.format(name=extra["name"]))
            if older:
                chunks.append(older)

        n = 0
        for ch in chunks:
            forms = ch.get("form", [])
            dates = ch.get("filingDate", [])
            items = ch.get("items", [""] * len(forms))
            for i, form in enumerate(forms):
                if not form.startswith("8-K"):
                    continue
                raw = items[i] if i < len(items) else ""
                codes = {c.strip() for c in (raw or "").split(",") if c.strip()}
                out.append((ticker, dates[i], form, codes))
                n += 1
        print(f"  {ticker:<6} {n:>5} 8-K filings")
    return out


def main():
    if not SEC_USER_AGENT:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

    print(f"Reading 8-K history for {len(watchlist.tickers())} companies...")
    rows = filings()
    print(f"\n{len(rows)} 8-K filings total")

    no_codes = sum(1 for _, _, _, c in rows if not c)
    print(f"{no_codes} with no item codes listed "
          f"(carries_press_release fails open on these, so they post)")

    total, dropped, newest_dropped = Counter(), Counter(), {}
    for ticker, date, form, codes in rows:
        posts_now = bool(codes & pm.PRESS_RELEASE_ITEMS)
        for code in codes:
            total[code] += 1
            if not posts_now:
                dropped[code] += 1
                if date > newest_dropped.get(code, ""):
                    newest_dropped[code] = date

    print("\n" + "=" * 92)
    print("ITEM DISTRIBUTION — appearances, and appearances the filter drops")
    print("=" * 92)
    print(f"{'item':<7}{'label':<40}{'total':>7}{'dropped':>9}{'drop%':>7}"
          f"   {'newest dropped':<14}{'in set':>7}")
    print("-" * 92)
    for code, n in sorted(total.items(), key=lambda kv: -kv[1]):
        if len(code) < 4:
            continue          # pre-2004 legacy numbering; all dated 2000-2004
        d = dropped.get(code, 0)
        label = pm.ITEM_LABELS.get(code, "?")[:38]
        mark = "yes" if code in pm.ALWAYS_POST_ITEMS else ""
        flag = "  <- structural" if code in STRUCTURAL else ""
        print(f"{code:<7}{label:<40}{n:>7}{d:>9}{100*d/n:>6.0f}%"
              f"   {newest_dropped.get(code, '—'):<14}{mark:>7}{flag}")

    print("\n" + "=" * 92)
    print(f"WHAT THE CURRENT SET RESCUES — {sorted(pm.ALWAYS_POST_ITEMS)}")
    print("=" * 92)
    recent = [r for r in rows if r[1] >= "2025-01-01"]
    resc_all = [r for r in rows
                if (r[3] & pm.ALWAYS_POST_ITEMS) and not (r[3] & pm.PRESS_RELEASE_ITEMS)]
    resc_rec = [r for r in recent
                if (r[3] & pm.ALWAYS_POST_ITEMS) and not (r[3] & pm.PRESS_RELEASE_ITEMS)]
    print(f"  full history : {len(resc_all)} filing(s) now post that previously did not")
    print(f"  since 2025   : {len(resc_rec)} filing(s), "
          f"~{len(resc_rec)/19:.1f}/month")
    print("\n  most recent rescued filings:")
    for ticker, date, form, codes in sorted(resc_rec, key=lambda r: r[1],
                                            reverse=True)[:8]:
        print(f"    {date}  {ticker:<6} items={','.join(sorted(codes))}")

    print("\n" + "=" * 92)
    print("EXCLUDED ITEMS — what adding each would cost, since 2025")
    print("=" * 92)
    candidates = [c for c in total
                  if len(c) >= 4 and c not in pm.ALWAYS_POST_ITEMS
                  and c not in pm.PRESS_RELEASE_ITEMS and c not in STRUCTURAL]
    for code in sorted(candidates, key=lambda c: -dropped.get(c, 0))[:8]:
        n = sum(1 for _, _, _, codes in recent
                if code in codes and not (codes & pm.PRESS_RELEASE_ITEMS))
        if not n:
            continue
        by_co = Counter(t for t, _, _, codes in rows
                        if code in codes and not (codes & pm.PRESS_RELEASE_ITEMS))
        print(f"\n  {code}  {pm.ITEM_LABELS.get(code, '?')}")
        print(f"    +{n} posts since 2025 (~{n/19:.1f}/month), "
              f"{dropped.get(code, 0)} dropped across full history")
        print(f"    concentration: "
              f"{', '.join(f'{t} {c}' for t, c in by_co.most_common(5))}")

    print("\n" + "=" * 92)
    print("STRUCTURAL ITEMS — never exempt these")
    print("=" * 92)
    for code in sorted(STRUCTURAL):
        print(f"  {code}  {pm.ITEM_LABELS.get(code, '?')}: appears on "
              f"{total.get(code, 0)} of {len(rows)} filings. Exempting it would "
              f"post nearly every 8-K\n      and silently undo the exhibit "
              f"filter entirely.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
