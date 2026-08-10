# The five changes — built, dry-run, held on branch

2026-08-09. Branch `digest-large-move`, one commit `595672a`. **`main` is
untouched at `4c5f304`.**

---

## The re-derived constant: it holds, and W32 changes

**18% and 2.0× survive the redefinition unchanged.** The two definitions are
further apart than the W32 spot-check suggested:

```
959 ticker-weeks measured both ways
|difference|  p50 2.3pts   p90 6.1   p99 17.3   max 85.0
```

Aggregate behaviour barely moves, and moves slightly in favour:

| | mean/wk | median | max | weeks ≥1 | weeks ≥5 |
|---|---|---|---|---|---|
| probe definition (open→close) | 1.8 | 2.0 | 6 | 42/53 | 3 |
| **digest definition (prior close→close)** | **2.0** | **2.0** | **6** | **48/53** | **2** |

Better coverage (48 weeks against 42) and fewer crowded weeks (2 against 3).
Nothing in the grid argued for a different constant — 15% & 2.0× gives 2.2/wk
with 3 crowded weeks, 20% & 2.0× gives 1.8/wk with 1.

**And the absolute-only finding survives the redefinition**, which it had to:

```
>=10%  mean 8.2/wk  max 17  weeks naming >=5: 40/53
>=18%  mean 3.6/wk  max 14  weeks naming >=5: 15/53
>=25%  mean 1.7/wk  max  9  weeks naming >=5:  5/53
```

### What changed is W32's output — four names became two

```
        digest      x  fires      probe      x
CIFR     -23.0   3.45  FIRES      -21.2   2.59
SPCX     +22.8   3.42  FIRES      +25.1   3.07
HUT      -17.7   2.65             -14.7   1.80
ABTC     +17.2   2.58             +21.8   2.67
NUAI     +13.3   1.99             +19.7   2.41
```

ABTC and NUAI fall below the 18% absolute on the digest's definition; on mine
they cleared it. **The two that survive are exactly the two you named as the
week** — CIFR and SPCX.

**One cost worth stating: HUT misses by 0.3 points** at −17.7% and 2.65×. I am
not moving the constant for it. Dropping to 17% or 15% to catch one name is
fitting to the sample, which is the thing this whole derivation was built to
avoid — and 15% & 2.0× would add a third crowded week to buy it.

---

## What the post looks like now

```
__**Large moves**__ · >=18.0% and >=2.0x the roster median of 6.7%

**CIFR** -23.0% to $17.18 — 3.4x the roster, 2.6x peak volume
**SPCX** +22.8% to $133.11 — 3.4x the roster, 3.5x peak volume

__**Convergence**__ · a company in 3+ independent source families in one week

Nothing converged this week.
...
[Full derivation → 2026-W32.md](https://github.com/.../digest/2026-W32.md)
```

**Your crowding-out worry, measured:**

```
description 1065/4096   embed total 1746/6000   widest monospace line 26/28
LIMITS OK
```

Both persistence findings survive untouched. Two large-move entries rather
than four turns out to help — the post is at a quarter of the description
budget, so the limit was never near. Worth having checked rather than assumed,
but there is a lot of headroom.

---

## The ~ inversion, and the second instance

Fixed in **both** renderings — the post's monospace block had its own copy and
I missed it on the first pass; the second dry run caught it.

```
| **SPCX** | +22.8% | $133.11 | 3.5x | ~ not testable  |
| **WYFI** |  +3.9% |  $24.63 | 0.6x | ~ short window  |
```

Both marked now, and the file distinguishes the two states while the 28-char
block cannot and marks both with `~`.

**You were right that it was a shape.** `silent()` had it too: it read
`filings.detail.filings_in_week`, and a NOT_TESTABLE filings verdict carries an
empty detail — so a company nothing had measured would have been reported as
having **filed nothing**. That is the one claim in the digest that turns a gap
into a lie, and its own docstring says so. Both now read the level first.

The rule is stated once, in `bar_figure`:

> **Reading a detail field to infer a state, when a not-testable verdict
> populates no detail at all, silently returns the falsy answer.** Check the
> level; the detail is for figures.

---

## Absolutes, and the close column

`close` and `prior_close` in the price detail, `peak_volume` and `week_volume`
in the volume detail. The week table now carries a real close:

```
| | week % | close | peak volume | 52w |
| **MARA** | -10.9% | $10.09 | 1.2x | · |
| **IREN** | +12.0% | $41.23 | 1.1x | · |
```

Column reordered so close sits next to the return it explains.

---

## The link

**Width was not the problem.** Discord does not linkify footer text at all, so
the bare `digest/<week>.md` was unreachable regardless of length. It is a
markdown link in the description now, appended after the budget checks so it
cannot be truncated away, with a warning if it ever will not fit. The
redundant path is out of the footer.

---

## The roster median, recorded

`large_moves.roster_median_abs_return`, alongside `threshold_pct`,
`roster_multiple`, `measured` and `basis`. The file states it in prose too —
*"the roster's median absolute return, which was **6.7%** across 19
companies"* — so a reader or an article can reproduce why a name fired.

---

## Not a contributor

`record["large_moves"]` is computed after the verdicts and before convergence,
from the `price` and `volume` details that already exist. No key, no
`SOURCE_FAMILY` entry, no change to the convergence arithmetic. W32's
convergence output is byte-identical to before: IREN at 2, nothing converged,
SPCX still `count=1, families=['market']`.

---

## The divergence, recorded

New section in `docs/weekly-digest.md` — *A company added mid-week is reported
for the whole week* — with the table contrasting an event feed against a weekly
summary, the verification that all nineteen companies had five sessions and
identical baselines in W32, and what each wrong "fix" would cost.

---

## Status

| | |
|---|---|
| Branch | `digest-large-move`, one commit, pushed |
| `main` | untouched at `4c5f304` |
| Dry runs | two, both success; second confirmed the mono-table fix |
| Limits | 1065/4096, 1746/6000, 26/28 — **OK** |
| Probe deleted | `probe_largemove.py` and its workflow; findings are in the constant's comment |
| `python watchlist.py` | OK |

Ready to merge on your word.
