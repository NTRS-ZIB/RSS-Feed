# The large-move threshold — distribution, and a design change it forces

2026-08-09. Runs 31291379639 and its follow-up. **Nothing built.**

**An absolute threshold cannot work, at any value. The measurement says so
plainly and it is the main finding.**

---

## 1. What the distribution says

Weekly returns across 53 complete weeks, 960 ticker-weeks. Two populations
kept apart, because the ten-week convergence basis is 190 draws for a tail
statistic:

```
comparable (W22-W31, 187 ticker-weeks)
  |return|  p50  8.1   p75 15.6   p90 22.0   p95 23.9   p98 32.8   max  47.5
long       (53 weeks, 960 ticker-weeks)
  |return|  p50  8.4   p75 15.3   p90 24.6   p95 33.2   p98 47.5   max 180.1
```

This roster's median week is an 8% move. That is the context every threshold
has to sit in.

### The candidates, and the number that kills them

| ≥ | mean/wk | median | **max** | weeks naming ≥5 |
|---|---|---|---|---|
| 10% | 7.6 | 6.0 | **17** | 37/53 |
| 12% | 6.4 | 5.0 | **17** | 28/53 |
| 15% | 4.7 | 4.0 | **17** | 18/53 |
| 18% | 3.5 | 2.0 | **17** | 13/53 |
| 20% | 3.0 | 2.0 | **16** | 12/53 |
| 25% | 1.8 | 1.0 | **14** | 5/53 |

**The means are all acceptable and every single max is the firehose.** At 25%
— more than three times the median week — one week still named 14 of 19.

### Those maxima are not noise, they are sector weeks

```
week       n>=20%   roster median |return|
2025-W46      16              28.9%
2025-W37      11              23.9%
2026-W16      11              22.1%
2026-W19       8              18.3%
...
2026-W17       0               4.1%
```

**The five weeks firing ≥8 tickers have a roster median |return| of 22.1%,
against 7.8% overall.** When bitcoin moves 30% every miner moves with it, and
an absolute threshold cannot tell *this company had news* from *everything
moved*.

**Raising the bar does not fix it — it makes it worse.** A higher threshold
empties the ordinary weeks while the sector weeks still name three quarters of
the roster, which is the exact firehose shape the persistence rule was rejected
for, arriving from the opposite direction.

---

## 2. The rule that does separate them

Fire when the move is **large in absolute terms AND large relative to what the
rest of the roster did that week.** The roster median is what differs between
the two cases, and it is already in hand.

| rule | mean/wk | median | **max** | weeks ≥1 | weeks ≥5 |
|---|---|---|---|---|---|
| ≥15% & ≥1.5× | 2.8 | 2.0 | 7 | 50/53 | 8 |
| ≥15% & ≥2.0× | 2.1 | 2.0 | 7 | 44/53 | 3 |
| **≥18% & ≥2.0×** | **1.8** | **2.0** | **6** | **42/53** | **3** |
| ≥20% & ≥2.0× | 1.6 | 1.0 | 6 | 40/53 | 3 |
| ≥20% & ≥2.5× | 1.3 | 1.0 | 5 | 34/53 | 2 |

**My candidate is ≥18% and ≥2.0× the roster's own median |return| that week.**
Mean 1.8 a week, max 6 across 53 weeks, and it names five or more in only 3 of
53.

The reason to prefer it over ≥20% & ≥2.0× is coverage rather than volume: it
fires in 42 weeks against 40 at almost identical cost, and 18% is close to the
p75 of the comparable window (15.6%) rather than deep in the tail, so the
section is about *notable* rather than *extraordinary*.

### It closes on exactly the weeks it should

```
2026-W16  roster median 22.1%  ->  2   SLNH +59.2%, BGDE +45.8%
2026-W26  roster median 13.0%  ->  0
2026-W27  roster median 18.2%  ->  0
2026-W17  roster median  4.1%  ->  0
2026-W20  roster median  3.9%  ->  3   ANY +28.7%, VIP +20.5%, SLNH +19.0%
2026-W30  roster median  5.9%  ->  2   VIP +44.1%, CIFR +23.3%
```

**W27 fired 15 of 19 on a plain 15% rule and fires zero here** — it was a
sector week and nothing stood out within it. **W16 was an even bigger sector
week and still surfaces two**, because +59% and +46% stood out even against a
22% median. That is the behaviour I would want and it was not designed in, it
fell out of the ratio.

### W32, the week that motivated this

```
roster median |return| 8.2%
  SPCX  +25.1%  3.07x  FIRES
  ABTC  +21.8%  2.67x  FIRES
  CIFR  -21.2%  2.59x  FIRES
  NUAI  +19.7%  2.41x  FIRES
  HUT   -14.7%  1.80x
  IREN  +12.9%  1.58x
```

Four names, including CIFR — the case that started this — and NUAI and ABTC,
which the current post also buries.

---

## 3. One caveat that must be settled before the constant is fixed

**My probe computed week return as first-open → last-close. The digest's
`week_return_pct` gives different numbers** — CIFR −23.0% against my −21.2%,
SPCX +22.8% against my +25.1%. Probably prior-close → last-close.

The gap is 2 points and it does not change which four names fire in W32, but
**a threshold derived on one definition and applied to another is precisely
the adjacent-population mistake this repo keeps recording.** Before 18/2.0×
goes into code I will re-derive it against the exact field the section will
read. I expect it to hold; I am not going to assume it.

---

## 4. Symmetry — rank by magnitude, show the sign, do not split

The two windows disagree, and the disagreement is the answer:

| | ≥+15% | ≤−15% | ratio |
|---|---|---|---|
| comparable (W22–W31) | 11 | 40 | **0.28** |
| long (53 weeks) | 127 | 122 | **1.04** |

**The ten-week window was a falling stretch.** Down moves are 3.6× more common
in it and essentially equally common over the full year. Building an
asymmetric rule off the comparable window would encode a bear market into a
permanent threshold — the same shape as measuring a filing-time distribution
off one morning's filings.

You are right that a −23% and a +22.8% are not the same kind of news. But the
place to express that is the sign next to the number, not two sections with
different empty rates — an empty "large falls" heading in a rising week is
noise, and it doubles the section count for a section averaging 1.8 entries.

---

## 5. Placement — above convergence

**Large moves first.** The deciding factor is the empty rate, which is
measured on both sides:

| | fires |
|---|---|
| convergence | 5 ticker-weeks in 190 — **empty in 6 of 10** backfill weeks |
| large moves | **42 of 53 weeks**, mean 1.8 |

If convergence stays first, roughly three posts in five open with *"Nothing
converged this week."* That teaches exactly the wrong reflex — the reader
learns the digest opens with nothing and starts scrolling past the top. With
large moves first, four posts in five open with content, and convergence keeps
its place as the thing you read *after* the week's events, which is also what
it is: the answer to "what might I have missed", not "what happened".

The risk is real and worth naming: putting raw magnitude above the filter's
headline finding could turn the digest into a price ticker. The guard is that
the section stays tight (1.8/week, max 6) and is framed as a pointer rather
than a finding.

---

## 6. Not double-counting — it must be a rendering, not a contributor

Your constraint decides the implementation. A large move on heavy volume
through a 52-week high is already three market-family contributors, and the
collapse exists so that reads as one family.

**So the section is computed in the renderer from the existing `price` and
`volume` verdicts plus the roster median — not registered as a contributor.**
No new key, no new family, no entry in `SOURCE_FAMILY`, and `convergence`
arithmetic is untouched. The move is named once in prose and stays one `market`
cell in the grid.

I checked the overlap with the price contributor, which asks a different
question — a move against the company's *own* 12-week SD:

```
both: 34   large-move only: 44   price only: 35
```

**The section adds 44 findings the price contributor does not make.** CIFR is
one of them: at −23% it was *routine* on the price contributor because CIFR is
always volatile (baseline SD 15.2%). That is the gap you identified, quantified
— and it also confirms the two measures are not redundant in either direction.

---

## What I have not built, and why

**Nothing.** Changes 2–5 are unstarted, deliberately: all four touch
`digest_render.py`'s week table and record, and so does change 1. Doing them
now means two passes over the same code and two rounds of dry runs. Change 3
already depends on change 4 by your own sequencing; change 1 depends on the
record carrying prices too.

Say go on the threshold and placement and all five land together, with the
re-derivation against `week_return_pct` done first.

---

## The decisions, in one place

| | |
|---|---|
| Threshold | **≥18% AND ≥2.0× the roster's median \|return\| that week** — 1.8/wk, max 6 in 53 weeks |
| Absolute-only | **rejected** — max 14–17 of 19 at every value from 10% to 25% |
| Symmetry | **ranked by magnitude, sign shown, not split** — the asymmetry is in the 10-week window and not in the year |
| Placement | **above convergence** — convergence is empty 6 weeks in 10, large moves fire 42 in 53 |
| Implementation | **a rendering over existing verdicts, not a contributor** — no new family, convergence untouched |
| Open | re-derive the constant against `week_return_pct` rather than my open→close |
