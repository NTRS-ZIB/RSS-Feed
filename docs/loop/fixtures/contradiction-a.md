# ABTC built, GLXY comment fixed, and the dedupe design

2026-08-09. Pushed: `f18a9d3`, `a77b26a`, `515ed05`.

```
ABTC: 22 items (Sanity CMS)
GLXY: 4 items (scraped); skipped 4 newsroom-media, 3 newsroom-our-stories,
      3 newsroom-video, 1 research

Dry run: would post 5 press and 0 insider item(s). State not saved.
  [press] ABTC · IR newsroom — American Bitcoin Reports Second Quarter 2026 Results
```

**All nineteen companies are now read from something faster than EDGAR.**

---

## First: I was wrong about the selector swap being equivalent

I said the class selector was "equivalent today, and it survives a slug scheme
change". **The dry run says 7 items → 4.** It is not equivalent.

The `/newsroom/<slug>` path match was catching `newsroom-our-stories` posts,
because those live under the same path. The class filter excludes them — the
CEO Letter and "Written in Code: This code is building rails for the world's
banks" are gone.

**That is arguably the better behaviour** — they are editorial, not
announcements, and this is a press-release channel. But it is a scope change
you did not approve, you approved it on my claim of equivalence, and *is a CEO
letter a press release* is your call rather than mine. Two options, both
one-line:

- **Leave it.** Announcements only, 4 items, tightest reading.
- **Widen to `newsroom-announcements` + `newsroom-our-stories`.** Restores the
  previous 7 and keeps the robustness against a slug change, which was the
  actual reason for the swap.

Nothing else in the change depends on which you pick.

---

## 1. Cross-host dedupe — the design, and my recommendation is not to build it

### What I measured

Ten feed items against the 276-card archive, plus every archive release against
every other:

| | |
|---|---|
| feed items with an exact normalised-title counterpart | **6 of 10** |
| feed items already sharing a URL with a card | **0** |
| worst score among true matches | **1.000** |
| **closest pair of two genuinely DIFFERENT releases** | **0.984** |

The probe printed `MARGIN: worst true match 1.000 vs closest false pair 0.984
-> a threshold exists`.

**That line is exactly the failure you warned about, and I am not going to
build on it.** A 0.016 margin is not a threshold, it is a coincidence of this
sample. Here is what sits at 0.984:

```
Galaxy Digital Announces First Quarter 2022 Financial Results
Galaxy Digital Announces First Quarter 2021 Financial Results
```

Two different releases, a year apart, 98.4% identical. And at 0.951, Q3 2021
against Q1 2021. **The near-collisions are concentrated in quarterly results
announcements — which are the highest-value items the channel carries.** A
fuzzy rule tuned anywhere below 1.000 suppresses Q1 2027 results as a duplicate
of Q1 2026, silently, once a quarter.

So fuzzy matching is out, and not narrowly.

### What about exact matching only

Exact normalised match caught 6 of 6, and none of the false pairs reached
1.000. That reads clean. **But there is a hole in that measurement and it is
mine:** the probe excluded pairs whose normalised titles were identical, on the
assumption they were archive duplicates. So *the false-positive rate of exact
matching is the one thing I did not measure.* I saw same-title pairs in the
archive — "Galaxy Expands into the Middle East with ADGM Office Opening" twice
— and treated them as card duplication without checking whether any such pair
was two distinct releases.

I could close that with one more query. I am not proposing it, because of the
next section.

### The near-miss behaviour, which is where the damage is

| rule | fails to match | matches too eagerly |
|---|---|---|
| fuzzy ≥0.95 | posts twice — visible | **suppresses quarterly results — silent, quarterly** |
| exact only | posts twice — visible | needs two distinct releases with identical titles |
| exact + within 7 days | posts twice — visible | needs that **within a week**, which kills the year-apart hazard outright |

If a rule is built, it is the third: **exact normalised title AND published
within 7 days.** The date window does the work the title cannot — Q1 2022 and
Q1 2021 are 1.000-similar in the limit and can never be seven days apart.

### But I do not think it should be built, and the reason is the shape of the
### overlap rather than the rule

The premise was that dedupe is the cost of adding the feed. Look at what the
feed actually adds:

| | |
|---|---|
| feed items **with** a newsroom counterpart | 6 — BNY, data-centre footprint, and four more |
| feed items **without** one | 4 — **Q2 Financial Results, $3.507bn notes pricing, Q2 webcast, ERCOT 830 MW Helios** |

**The four unique items are the entire reason to add the feed, and none of them
needs dedupe.** The six overlaps are the ones the newsroom already covers.

That reframes it. This is not "add a feed and solve dedupe". It is: the feed's
value is concentrated in items the scraper cannot see, and the duplicate
problem lives entirely in the items where the two sources agree.

### So: three options, and I recommend the second

**(a) Add the feed, accept duplicates.** 6 of 10 IR releases post twice. That
is routine noise, not a bounded cost — I would not call this the cheap option
you described, because the overlap is the majority case rather than the edge.

**(b) Add the feed, filtered to what the newsroom cannot carry.** The
discriminator is not a title comparison at all — it is `is_edgar`-style source
knowledge. `newsroom-announcements` is on-domain by construction (0 of 200
off-domain, measured). The feed's unique items are precisely the ones with no
on-domain newsroom page. **Suppress a feed item when an item with the same
normalised title and a `www.galaxy.com` link was already seen in this run.**

That is still a title match — but it is scoped to one run, one company and two
known sources, so the year-apart hazard cannot arise: Q1 2021 is not in the
same run as Q1 2022. It degrades to posting twice, never to suppressing.

**(c) Do not add the feed.** Keeps the status quo, loses the ERCOT release and
the quarterly results to EDGAR latency. Not free, but not fatal — they all
reach EDGAR as 8-Ks.

**(b) is what I would build**, and the thing that makes it safe is not the
matching, it is the scope: same run, same company, exact title, and a bias to
posting twice on any doubt. If you would rather not have any suppression rule
at all, **(c) is a defensible answer and I would take it over a rule nobody can
verify** — which was your instruction, and it applies more than I expected
going in.

**What I would not do is (a).** Six duplicates in ten is not a visible
annoyance, it is the channel's normal state.

---

## 2. ABTC — built

`read_abtc()`, `read_dgxx()`'s shape. Dry run: **22 items**, and the Q2 results
release posts.

The docstring carries the three things you asked for:

**The date field, with the case rather than the preference.**

> `_createdAt 2026-06-03` · `_updatedAt 2026-06-26` · `date 2026-04-22`
> Created in June, edited in June, published in April. **Using `_createdAt`
> would have been six weeks wrong on that release**, and it is the field that
> looks more canonical, so this is exactly the substitution a later reader
> makes while tidying.

**The reconciliation as completeness evidence**, with why it beats a single
check — a paginated endpoint returning one page looks identical to a complete
one returning everything:

```
22 pressRelease + 6 investorPresentation = 28   (Sanity)
28 /news-and-insights/ slugs                    (delivered HTML)
28 release pages with lastmod                   (sitemap.xml)
```

**The count floor as the failure treatment**, three states with three distinct
log lines: host did not respond, answered and refused (401/403 is what a
project made private looks like, and it is separable from an empty result), and
answered with fewer than five documents — which cannot be a quiet month because
an archive does not shrink.

Two decisions I made and recorded:

- **`uid` is the document id, not the link.** A slug can be edited after
  publication; the id cannot. Otherwise a retitled release reposts.
- **The URL is verified rather than constructed.** The 28 slugs in the
  delivered HTML are exactly these paths, which is what separates this from
  the DGXX case where a derived URL resolved 6 of 8 against a soft-404ing site.

Vendor caveat carried across verbatim in spirit: undocumented endpoint on
third-party infrastructure, and ABTC could make the project private without
knowing they had broken anything.

---

## 3. The GLXY comment, fixed

The false claim is gone and replaced with the measurement:

```
newsroom-announcements   200 cards, 200 dated,   0 off-domain
newsroom-media            19 cards,  19 dated,  19 off-domain
newsroom-our-stories      38 cards,  38 dated,   0 off-domain
newsroom-video            18 cards,  18 dated,   0 off-domain
```

And the part that is not what it looks like:

> `newsroom-announcements` is a reliable ON-DOMAIN CORPORATE POST filter and
> NOT a reliable "company announcement" filter. Galaxy files its own IR
> releases under `newsroom-media`, because they are hosted on
> investor.galaxy.com … **That exclusion is only harmless because
> investor.galaxy.com has its own feed.** If that feed is ever removed this
> filter silently stops covering GLXY's material announcements, and nothing
> here would say so.

That last sentence is the one worth having — the current arrangement is safe
because of a fact about a *different* source, and that dependency is invisible
from either one alone.

---

## The two rules, strengthened

**Off-domain**, from "check other hosts" to the sharper form:

> It has now happened three times — BGDE, WYFI, GLXY — and the sharper form of
> the rule is not "check other hosts". It is that **the reference is usually
> already in front of you.** … The release that motivated re-opening it was
> sitting on the page the whole time with
> `href="https://investor.galaxy.com/news-releases/..."`. The IR host was in
> the markup being parsed.
>
> So the check is cheap and specific: **enumerate the distinct hosts the
> newsroom links out to, and probe each one.**

**Autodiscovery**, amended as found:

> **Autodiscovery finding nothing is not evidence there is no feed. Run the
> host-path list too, and only then conclude absence.**

With the reason it matters stated: a method that worked once, stated as *the*
method, is what stops the next person looking further.

---

## My own two mistakes, recorded as a rule

New subsection in `docs/press-monitor.md`, immediately above the scraper rule
it generalises:

> ### A probe that finds nothing looks exactly like a source that has nothing
>
> | reported | actually | would have cost |
> |---|---|---|
> | 278 cards, **0 dated** | 276 cards, **all dated** | ruling out a usable source |
> | **0 bundles, 0 chars of JS** | 8 bundles, 637,688 chars | ruling out the only ABTC route that worked |
>
> Both read as findings about the source and were failures of the tool, and
> both pointed the same way — toward *there is nothing here*, which is the
> conclusion that ends an investigation rather than continuing it.

And the practical part: in both cases a second signal already existed and went
unread — the page obviously renders dates in a browser, and a React app
obviously ships JavaScript.

---

## Housekeeping

Four probe scripts and the `Probe sources` workflow deleted, and removed from
the notifier list. Nothing recurring in them.

`python watchlist.py` validates, 15 IR feeds, worktree clean, dry run posted
nothing and saved no state.
