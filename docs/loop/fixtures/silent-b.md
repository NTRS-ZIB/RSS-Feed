# Cross-host dedupe built — dry run on a branch, main untouched

2026-08-09. Branch `glxy-cross-host`, two commits. **`main` is still at
`515ed05`.**

You asked to dry-run before committing. The workflow can only run committed
refs — a dispatch tests the code on GitHub, not local edits — so this went to a
branch and was dispatched with `--ref glxy-cross-host`. Nothing is on `main`
and nothing is live.

---

## The real run

```
GLXY: 4 items (scraped); skipped 4 newsroom-media, 3 newsroom-our-stories,
      3 newsroom-video, 1 research
GLXY: 10 items
GLXY: cross-host dedupe kept 8, suppressed 2 already carried by the newsroom
      (of 4 newsroom items)
  suppressed: Galaxy and BNY Collaborate to Advance Digital Asset Infrastructu
  suppressed: Galaxy Expands Data Center Footprint with Acquisition of 500 Acr

6 candidate(s) checked, 6 to post.
  [press] GLXY · IR newsroom — Galaxy and Sharplink Launch First-of-Its-Kind $125M
  [press] GLXY · IR newsroom — Galaxy Announces Second Quarter 2026 Financial Results
  [press] SPCX · IR newsroom — SpaceX Reports Second Quarter 2026 Results
  [press] BTDR · IR newsroom — Bitdeer Announces $4.7 Billion, 16-Year AI/HPC Data Center L
  [press] GLXY · IR newsroom — Galaxy and BNY Collaborate to Advance Digital Asset Infrastr
  [press] ABTC · IR newsroom — American Bitcoin Reports Second Quarter 2026 Results

Dry run: would post 6 press and 0 insider item(s). State not saved.
```

**Suppression count: 2. No duplicate titles in the post list.** The two
suppressed items are the feed's copies; BNY still posts, from the newsroom,
which is the intended side of the pair.

And **"Galaxy Announces Second Quarter 2026 Financial Results" posts** — that
is the item the feed was added for. It has no newsroom page and would have
waited for the 8-K.

---

## What was built

`suppress_cross_host()`, and the docstring leads with scope as you asked:

> **WHAT MAKES THIS SAFE IS THE SCOPE, NOT THE MATCHING.** Same run, same
> company, two known sources, exact normalised title, and within
> `CROSS_HOST_DAYS`. Every one of those narrows the population being compared
> until an accidental match cannot happen — and the bias throughout is to post
> twice rather than to suppress.

Then the measurement that forecloses anything fuzzy — 0.984 on Q1 2022 against
Q1 2021, 0.951 on Q3 against Q1, clustered in quarterly results, and the note
that the probe's `a threshold exists` was a 0.016 margin in one sample
presented as a finding.

Then the window, framed as construction rather than tuning:

> Q1 2021 and Q1 2022 are a year apart, so they can never both be inside seven
> days of each other whatever their titles say.

### The two things you wanted in the implementation

**It degrades to posting twice, and the empty case is separated from the
partial one.**

```python
if not newsroom_items:
    print(f"  {label}: cross-host dedupe SKIPPED — the newsroom produced 0 "
          f"items, so all {len(feed_items)} feed items post. This is not "
          f"{len(feed_items)} unique releases; it is the newsroom being "
          f"unavailable, and duplicates are expected.")
    return feed_items
```

A newsroom that yields nothing skips dedupe entirely rather than matching
against an empty set, and the log line says explicitly that ten posting items
is not ten unique releases. **A partial scrape is deliberately left to run** —
it can only fail to match, which posts a duplicate, and a duplicate is visible
where a suppression is not. That asymmetry is stated in the docstring rather
than left to be inferred.

A missing timestamp on either side also falls through to posting, for the same
reason.

**Suppressions are logged**, in the shape the skip count already uses, plus the
titles — the count should be small and boring, so an unexpected number is the
informative case:

```
GLXY: cross-host dedupe kept 8, suppressed 2 already carried by the newsroom
      (of 4 newsroom items)
  suppressed: Galaxy and BNY Collaborate to Advance Digital Asset Infrastructu
```

The `(of 4 newsroom items)` is there so a reader can tell "suppressed 0 because
nothing overlapped" from "suppressed 0 because the newsroom yielded almost
nothing".

### The unmeasured hole, in the comment

> **ONE THING WAS NOT MEASURED AND SHOULD BE SAID PLAINLY.** The
> false-positive rate of EXACT title matching is unknown. The probe excluded
> pairs with identical normalised titles as archive duplicates — an
> assumption, not a check … **The seven-day window is what makes that moot in
> practice** … Widening the window reintroduces the hole, and that is the
> reason not to.

That last clause is the point: it attaches the hazard to the specific edit that
would reintroduce it.

---

## GLXY scope, recorded as deliberate

In `scrape_galaxy()`, with the correction that it was not a refactor:

> Selecting on the class … **The two are NOT equivalent, and the difference
> was a scope change rather than a refactor.** … swapping to the class took the
> run from 7 items to 4.
>
> **`newsroom-our-stories` IS EXCLUDED ON PURPOSE.** It is editorial — CEO
> letters, "Written in Code" — and this is a press-release channel, so company
> announcements only. Approved 2026-08-09.
>
> That is written down because the class filter now does it silently, and the
> narrowing looks exactly like a side effect of the selector. It is not.
> **GLXY is the only company on this roster whose newsroom separates
> announcements from editorial in markup**, so the decision exists here and
> nowhere else, and there is no precedent elsewhere in the repo to point at or
> to argue from.

---

## The digest check: no change needed, and structurally so

I checked rather than reasoned, and the answer is cleaner than "it handles it".

**The digest has no press contributor at all.** Its eleven are `short_volume`,
`price`, `volume`, `crossings`, `threshold_list`, `filings`, `comment_letters`,
`holders`, `dilution`, `short_interest`, `ftd`. It imports two constants from
`press_monitor` — `ALWAYS_POST_ITEMS` and `ITEM_LABELS`, the 8-K item taxonomy
— and reads no press items and no IR feeds.

And convergence counts **contributor keys**, not sources:

```python
hits = sorted(k for k, v in vs.items() if v["level"] == NOTABLE)
families = sorted({SOURCE_FAMILY.get(k, k) for k in hits})
```

So a company cannot contribute twice to convergence by having two press
sources, because press is not in the count at all. The `SOURCE_FAMILY`
collapse that exists for the market contributors is the mechanism that would
have been needed here, and it is not needed because the case cannot arise.

**One thing worth noting rather than acting on:** if a press contributor is
ever added to the digest, GLXY would be the company it gets wrong first, and
the fix would be to count companies-with-any-press rather than press-sources.
That is a note for whoever adds it, not a change now.

---

## Status

| | |
|---|---|
| Branch | `glxy-cross-host`, pushed, 2 commits |
| `main` | untouched at `515ed05` |
| Dry run | dispatched `--ref glxy-cross-host`, success |
| Suppression count | **2**, both correct |
| Duplicate titles in the post list | **0** |
| `python watchlist.py` | OK, 16 IR feeds |
| Posted / state | nothing, nothing |

Ready to merge to `main` on your word. Merging is what makes it live — the
press monitor runs from `main` on a cron.
