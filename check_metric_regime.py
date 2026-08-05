#!/usr/bin/env python3
"""Did the relationship change, or did one of its inputs change regime?

A maintenance tool, not a component: it posts nothing, saves nothing, and runs
only when started by hand.

WHAT IT ANSWERS
Any metric shaped as a ratio of two quantities that both move can fall for two
completely different reasons, and the number alone cannot tell you which:

  1. the relationship it measures genuinely weakened, or
  2. one of its inputs changed regime and the metric followed mechanically.

Correlation is the case this was written for, and it is worth stating in full
because the trap is not obvious. Correlation is SCALE-INVARIANT, so a reference
series simply moving less cannot reduce it directly — multiply every reference
return by 0.5 and every correlation is unchanged. The mechanism can only reach
correlation through the identity

    r  =  beta  x  sigma_reference / sigma_subject

which makes BETA the discriminating quantity, not volatility. Beta is how far
the subject moves per 1% of the reference: it is what "is this still tracking
that" actually means, and it is exactly what a bare correlation hides.

That identity also yields a falsifiable signature. A pure rescaling of the
reference leaves r unchanged and raises beta by 1/ratio. So:

  - beta moved            -> the relationship changed. The finding is real.
  - beta flat, sigma fell -> the reference went quiet. The finding is an
                             artefact and reporting it would be reporting a
                             measurement as an event.

GENERALISES BEYOND CORRELATION
The same shape recurs wherever a metric divides one moving thing by another —
a ratio against a trailing baseline, a share-of-total, a rate per unit of
something that is itself varying. Decompose before believing a change: hold
each input's regime up against the numerator and see which one actually moved.

WHEN TO REACH FOR IT
- Before building any component whose output is a ratio, when a probe has
  produced a finding that looks like a change in behaviour.
- When an existing metric moves across the whole roster at once. A roster-wide
  move is much more often an input changing regime than fourteen companies
  changing together.
- When a finding is about to be reported as a market event rather than as a
  measurement.

HOW TO READ THE OUTPUT
Section 1 is the setup: if either reference's volatility ratio is far from 1.0
while the subjects' median ratio is near it, the conditions for a mechanical
result are present and sections 2 and 3 decide it.

Section 2 is the test. Compare the beta column against the sigma-ratio column.
Betas moving in one direction across most of the roster is a real change;
betas flat with the sigma ratio falling everywhere is not.

Section 3 asks whether any of it clears sampling noise at all. Two independent
90-day samples give a critical |dz| of about 0.30, which is a wide bar — a
change of 0.20 in a correlation near 0.5 does not clear it.

Section 4 checks derived quantities. Anything computed FROM the metric inherits
its artefact rather than correcting it, which is easy to forget when the
derived number is the sharpest-looking result you have.

WHAT IT FOUND THE FIRST TIME
Run 2026-08-04 against a proposed BTC-decoupling table. Bitcoin's realised
volatility fell 54% to 34% while the Nasdaq's rose 16% to 25% and the roster's
own median barely moved at 1.05. Median correlation change was -0.20; median
RELATIVE change in beta was +4%, and betas fell for seven of fourteen, a coin
flip. The sigma-ratio term fell for all fourteen. A pure rescaling would have
raised beta 59%. The measure was rejected — see docs/rejected.md.

Read-only. Fetches price history, prints tables, exits. No webhook, no state,
no commit, no schedule, no write permissions.
"""

import math
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from watchlist import WATCHLIST

# The subject roster. Any list of symbols works; the watchlist is the default
# because that is what the repo measures.
SUBJECTS = [c["ticker"] for c in WATCHLIST]

# References to decompose against. A crypto symbol is fetched keyless from the
# crypto endpoint; anything else goes to the equity endpoint with the key.
# Two references rather than one: a single series cannot distinguish "the
# subject moved away from A" from "A went quiet", and a second one that moved
# the other way is what exposed the artefact the first time.
CRYPTO_REFERENCES = ["BTC/USD"]
EQUITY_REFERENCES = ["QQQ"]

CRYPTO_BARS = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
STOCK_BARS = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
# Consolidated feed, matching daily_recap.py. IEX alone gives a wrong close.
FEED = "sip"
DELAY_MINUTES = 20
LOOKBACK_DAYS = 430
HALF = 90                    # trading days per half
ANN = math.sqrt(252)


def _get(url, params, headers=None):
    r = requests.get(url, params=params, timeout=(10, 30), headers=headers or {})
    if r.status_code != 200:
        print("  HTTP %s %s" % (r.status_code, r.text[:200]))
        return None
    return r.json()


def _paged(url, params, headers=None):
    """Alpaca pages by token; collect every bar across pages."""
    rows, token, pages = {}, None, 0
    while pages < 8:
        p = dict(params)
        if token:
            p["page_token"] = token
        d = _get(url, p, headers)
        if d is None:
            return None
        for sym, bars in (d.get("bars") or {}).items():
            for b in bars:
                day = datetime.fromisoformat(
                    b["t"].replace("Z", "+00:00")).date()
                rows.setdefault(sym, {})[day] = float(b["c"])
        token = d.get("next_page_token")
        pages += 1
        if not token:
            break
    return rows


def fetch_crypto(symbols):
    """Keyless. Crypto trades every calendar day; the join drops the extras."""
    start = (datetime.now(timezone.utc)
             - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    return _paged(CRYPTO_BARS, {"symbols": ",".join(symbols),
                                "timeframe": "1Day", "start": start,
                                "limit": 10000})


def fetch_equities(symbols):
    now = datetime.now(timezone.utc)
    return _paged(STOCK_BARS, {
        "symbols": ",".join(symbols), "timeframe": "1Day",
        "start": (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat(),
        "end": (now - timedelta(minutes=DELAY_MINUTES)).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "limit": 10000, "feed": FEED, "adjustment": "all",
    }, {"APCA-API-KEY-ID": ALPACA_KEY_ID,
        "APCA-API-SECRET-KEY": ALPACA_SECRET})


def returns_on(dates, closes):
    """Simple returns between CONSECUTIVE ENTRIES of `dates`.

    `dates` must already be the inner join of the two series. A Friday-to-
    Monday step is then one observation with the weekend folded into it on both
    sides; taking a 24x7 reference's own calendar returns instead would compare
    a one-day equity move against a three-day crypto move every week.
    """
    out = []
    for prev, cur in zip(dates, dates[1:]):
        p0, p1 = closes.get(prev), closes.get(cur)
        out.append(p1 / p0 - 1.0 if p0 and p1 and p0 > 0 else None)
    return out


def pearson(xs, ys):
    pairs = [(a, b) for a, b in zip(xs, ys) if a is not None and b is not None]
    n = len(pairs)
    if n < 5:
        return None, n
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    sxy = sum((a - mx) * (b - my) for a, b in pairs)
    sxx = sum((a - mx) ** 2 for a, _ in pairs)
    syy = sum((b - my) ** 2 for _, b in pairs)
    if sxx <= 0 or syy <= 0:
        return None, n
    return sxy / math.sqrt(sxx * syy), n


def beta(subject, reference):
    """Slope of subject on reference: how far it moves per 1% of the reference."""
    pairs = [(a, b) for a, b in zip(subject, reference)
             if a is not None and b is not None]
    if len(pairs) < 5:
        return None
    mr = sum(b for _, b in pairs) / len(pairs)
    ms = sum(a for a, _ in pairs) / len(pairs)
    var = sum((b - mr) ** 2 for _, b in pairs)
    cov = sum((a - ms) * (b - mr) for a, b in pairs)
    return cov / var if var > 0 else None


def stdev(vals):
    v = [x for x in vals if x is not None]
    if len(v) < 3:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def halves(a, b):
    """(prior, recent) aligned return vectors for two series."""
    common = sorted(set(a) & set(b))
    if len(common) < 2 * HALF + 5:
        return None
    rec, pri = common[-(HALF + 1):], common[-(2 * HALF + 2):-HALF]
    return ((returns_on(pri, a), returns_on(pri, b)),
            (returns_on(rec, a), returns_on(rec, b)))


def fisher_z(r):
    return 0.5 * math.log((1 + r) / (1 - r)) if r is not None and abs(r) < 1 \
        else None


def main():
    if not ALPACA_KEY_ID or not ALPACA_SECRET:
        sys.exit("ALPACA_KEY_ID / ALPACA_SECRET_KEY not set.")

    refs = {}
    if CRYPTO_REFERENCES:
        got = fetch_crypto(CRYPTO_REFERENCES) or {}
        for k, v in got.items():
            refs[k.split("/")[0]] = v
    eq = fetch_equities(SUBJECTS + EQUITY_REFERENCES) or {}
    for r in EQUITY_REFERENCES:
        if r in eq:
            refs[r] = eq.pop(r)
    if not refs or not eq:
        sys.exit("No data.")

    subjects = [s for s in SUBJECTS if s in eq]
    print("%d subjects against %s, %d trading days per half.\n"
          % (len(subjects), " and ".join(refs), HALF))

    # ------------------------------------------------------------------
    print("=" * 78)
    print("1. REALISED VOLATILITY, BOTH HALVES")
    print("=" * 78)
    print("  Annualised stdev of daily returns. A reference whose ratio is far")
    print("  from 1.00 while the subjects sit near it is the setup for a")
    print("  mechanical result.\n")
    print("    %-6s %10s %10s %8s" % ("", "prior", "recent", "ratio"))
    grid = sorted(set.intersection(*[set(v) for v in refs.values()]))
    ratios = {}
    for label, ser in list(refs.items()) + [(s, eq[s]) for s in subjects]:
        common = sorted(set(ser) & set(grid))
        if len(common) < 2 * HALF + 5:
            continue
        sp = stdev(returns_on(common[-(2 * HALF + 2):-HALF], ser))
        sr = stdev(returns_on(common[-(HALF + 1):], ser))
        if not sp or not sr:
            continue
        ratios[label] = sr / sp
        print("    %-6s %9.0f%% %9.0f%% %8.2f%s"
              % (label, sp * ANN * 100, sr * ANN * 100, sr / sp,
                 "   <-- reference" if label in refs else ""))
    subj = sorted(v for k, v in ratios.items() if k not in refs)
    if subj:
        print("\n    subject median ratio: %.2f" % subj[len(subj) // 2])
    for k in refs:
        if k in ratios:
            print("    %-6s reference ratio: %.2f" % (k, ratios[k]))

    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("2. BETA vs CORRELATION — WHICH ONE MOVED?")
    print("=" * 78)
    print("  r = beta x sigma_ref / sigma_subject. Betas moving together is a")
    print("  real change. Betas flat while the sigma ratio falls everywhere is")
    print("  the reference changing regime. A PURE RESCALING of the reference")
    print("  would leave r unchanged and raise beta by 1/ratio.\n")
    for rname, rser in refs.items():
        exp = (1.0 / ratios[rname] - 1.0) * 100 if ratios.get(rname) else None
        print("  vs %s%s" % (rname,
                             "   (a pure rescaling would move beta %+.0f%%)"
                             % exp if exp is not None else ""))
        print("    %-6s %16s %16s %16s"
              % ("", "corr pri->rec", "beta pri->rec", "sig_ref/sig_sub"))
        bchg, cchg, bfell = [], [], 0
        for s in subjects:
            h = halves(eq[s], rser)
            if not h:
                continue
            (sp_, rp_), (sr_, rr_) = h
            c0, _ = pearson(sp_, rp_)
            c1, _ = pearson(sr_, rr_)
            b0, b1 = beta(sp_, rp_), beta(sr_, rr_)
            if None in (c0, c1, b0, b1):
                continue
            k0 = stdev(rp_) / stdev(sp_) if stdev(sp_) else float("nan")
            k1 = stdev(rr_) / stdev(sr_) if stdev(sr_) else float("nan")
            cchg.append(c1 - c0)
            if abs(b0) > 0.05:
                bchg.append((b1 - b0) / b0)
            if b1 < b0:
                bfell += 1
            print("    %-6s %16s %16s %16s"
                  % (s, "%+.2f -> %+.2f" % (c0, c1),
                     "%+.2f -> %+.2f" % (b0, b1), "%.2f -> %.2f" % (k0, k1)))
        if cchg:
            cchg.sort()
            bchg.sort()
            print("\n      betas that fell:                %d of %d"
                  % (bfell, len(cchg)))
            if bchg:
                print("      median RELATIVE change in beta: %+.0f%%"
                      % (100 * bchg[len(bchg) // 2]))
            print("      median change in correlation:   %+.2f\n"
                  % cchg[len(cchg) // 2])

    # ------------------------------------------------------------------
    print("=" * 78)
    print("3. DOES ANY OF IT CLEAR SAMPLING NOISE?")
    print("=" * 78)
    crit = 1.96 * math.sqrt(2.0 / (HALF - 3))
    print("  Fisher z across two independent %d-day samples; |dz| > %.2f to be"
          % (HALF, crit))
    print("  called real. That is a wide bar: near r=0.5 it needs about 0.22.\n")
    names = list(refs)
    print("    %-6s" % "" + "".join("%24s" % n for n in names))
    tally = {n: 0 for n in names}
    for s in subjects:
        line = "    %-6s" % s
        for rname in names:
            h = halves(eq[s], refs[rname])
            if not h:
                line += "%24s" % "-"
                continue
            (sp_, rp_), (sr_, rr_) = h
            c0, _ = pearson(sp_, rp_)
            c1, _ = pearson(sr_, rr_)
            z0, z1 = fisher_z(c0), fisher_z(c1)
            if None in (z0, z1):
                line += "%24s" % "-"
                continue
            dz = z1 - z0
            real = abs(dz) > crit
            tally[rname] += 1 if real else 0
            line += "%24s" % ("%+.2f  dz %+.2f  %s"
                              % (c1 - c0, dz, "REAL" if real else "noise"))
        print(line)
    print("\n    clearing noise: " + "   ".join(
        "%s %d of %d" % (n, tally[n], len(subjects)) for n in names))

    # ------------------------------------------------------------------
    if len(names) >= 2:
        print("\n" + "=" * 78)
        print("4. DERIVED QUANTITIES INHERIT IT")
        print("=" * 78)
        print("  Partial correlation is built FROM these correlations, so it")
        print("  carries the same artefact rather than correcting it. This is")
        print("  the check that is easiest to skip, because the derived number")
        print("  is usually the sharpest-looking result you have.\n")
        a, b = names[0], names[1]
        print("    %-6s %22s %22s"
              % ("", "%s|%s pri->rec" % (a, b), "%s|%s pri->rec" % (b, a)))
        for s in subjects:
            common = sorted(set(eq[s]) & set(refs[a]) & set(refs[b]))
            if len(common) < 2 * HALF + 5:
                continue
            out = []
            for span in (common[-(2 * HALF + 2):-HALF], common[-(HALF + 1):]):
                rs = returns_on(span, eq[s])
                ra = returns_on(span, refs[a])
                rb = returns_on(span, refs[b])
                r_sa, _ = pearson(rs, ra)
                r_sb, _ = pearson(rs, rb)
                r_ab, _ = pearson(ra, rb)
                if None in (r_sa, r_sb, r_ab):
                    out.append(None)
                    continue
                d1 = math.sqrt((1 - r_sb ** 2) * (1 - r_ab ** 2))
                d2 = math.sqrt((1 - r_sa ** 2) * (1 - r_ab ** 2))
                out.append(((r_sa - r_sb * r_ab) / d1 if d1 else None,
                            (r_sb - r_sa * r_ab) / d2 if d2 else None))
            if None in out or out[0] is None or out[1] is None:
                continue
            print("    %-6s %22s %22s"
                  % (s, "%+.2f -> %+.2f" % (out[0][0], out[1][0]),
                     "%+.2f -> %+.2f" % (out[0][1], out[1][1])))


if __name__ == "__main__":
    main()
