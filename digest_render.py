#!/usr/bin/env python3
"""
Weekly digest — the two renderings. NOTHING IS DERIVED HERE.

Both are pure functions of the verdict record `weekly_digest.py` produces. A
renderer that computed anything would be a second derivation to keep in step
with the first, and the two would disagree the week it mattered.

    render_post(records)      -> a Discord embed
    render_markdown(records)  -> the article-source file

`records` is [older, ..., this week], so a claim that spans weeks reads them
rather than recomputing them. That is what the middle layer is for.

THE TWO CONSUMERS WANT OPPOSITE THINGS
--------------------------------------
The post has a 4,096-character description and a 28-character monospace
ceiling, and is read once on a phone. The file is read by Claude as source for
writing, wants density, figures, baselines and a citation per claim, and will
be read a year from now by someone with no memory of this week.

So the post is a strict subset chosen by rank, and the file is the complete
grid including every cell that produced no finding.

THREE RULES THAT ARE NOT STYLISTIC
----------------------------------
1. AN EMPTY SECTION STILL PRINTS. Six of the ten backfilled weeks had nothing
   at three families. A section that vanishes when empty teaches the reader
   that its absence means nothing happened, when it means the filter worked.

2. THE SECONDARY TIER IS LISTED, NEVER PROMOTED. Two families runs 3.7
   companies a week, a fifth of the roster. Promoting it into the convergence
   section would be the firehose the threshold exists to prevent.

3. NEVER A SILENT CAP. When the post runs out of budget it says how many it
   dropped and where they are. A truncated list that looks complete is worse
   than a short one that says it is short.
"""

import json
import os
import sys
from datetime import date, datetime, timezone

import weekly_digest as wd

# The post carries ⚠ and the grid carries ●·~✕, and a Windows console defaults
# to cp1252, where printing either raises UnicodeEncodeError. The runner is
# UTF-8 so CI never sees it — which is exactly why it is worth handling: a dry
# run that crashes on the author's own machine is a dry run that does not get
# done. `errors="replace"` so a future glyph degrades to a box rather than
# taking the run down.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# ------------------------------------------------------------------ LIMITS --

# Discord's own limits, and this repo's.
DESC_LIMIT = 4096
FIELD_LIMIT = 1024
EMBED_LIMIT = 6000
MONO_WIDTH = 28          # Discord mobile wraps a code block past roughly this

# Reserved so the footer note about dropped names always fits.
DESC_BUDGET = DESC_LIMIT - 200

FAMILY_LABEL = {
    "market": "price, volume and 52-week crossings — one bar series",
    "short_volume": "short volume",
    "short_interest": "short interest",
    "filings": "filings",
    "comment_letters": "comment letters",
    "threshold_list": "Reg SHO threshold list",
    "dilution": "shares outstanding",
    "ftd": "fails to deliver",
}

# Column headings for the grid. A family, not a contributor — that is the
# collapsing. A new contributor either joins a family or adds one column, so
# the table's shape survives contributor fifteen.
FAMILY_COLUMN = {
    "short_volume": "sh vol",
    "short_interest": "sh int",
    "market": "market",
    "filings": "filings",
    "comment_letters": "letters",
    "threshold_list": "thresh",
    "dilution": "shares",
    "ftd": "FTD",
}

GLYPH = {
    wd.NOTABLE: "●",
    wd.ROUTINE: "·",
    wd.NOT_TESTABLE: "~",
    wd.SOURCE_FAILED: "✕",
}
NOT_PUBLISHED = "–"


# ------------------------------------------------------------------ SHARED --


def families_of(record, ticker):
    return record["convergence"][ticker]["families"]


def notable_verdicts(record, ticker):
    """[(contributor key, verdict)] for everything that fired, ranked so the
    persistence-carrying ones lead — those are the ones a daily post cannot
    have shown."""
    vs = record["verdicts"].get(ticker, {})
    out = [(k, v) for k, v in vs.items() if v["level"] == wd.NOTABLE]
    return sorted(out, key=lambda kv: (kv[1]["persistence"] is None, kv[0]))


def converged(record):
    return sorted((t for t in record["roster"]
                   if record["convergence"][t]["converged"]),
                  key=lambda t: (-record["convergence"][t]["count"], t))


def secondary(record):
    return sorted(t for t in record["roster"]
                  if wd.SECONDARY_TIER <= record["convergence"][t]["count"]
                  < wd.CONVERGENCE_THRESHOLD)


def persistent(records):
    """Everything carrying a persistence claim, with its run length.

    The run is counted backwards through the supplied records for the SAME
    ticker and the SAME contributor. It stops at the first week that did not
    qualify — a gap is a break, not a pause, or "four weeks running" would be
    true of something that fired in weeks 1 and 8.
    """
    current = records[-1]
    out = []
    for t in current["roster"]:
        for key, v in notable_verdicts(current, t):
            if not v["persistence"]:
                continue
            run = 1
            for earlier in reversed(records[:-1]):
                prior = earlier["verdicts"].get(t, {}).get(key, {})
                if prior.get("level") == wd.NOTABLE and prior.get("persistence"):
                    run += 1
                else:
                    break
            out.append((t, key, v, run))
    return sorted(out, key=lambda r: (-r[3], r[0]))


def silent(record):
    """(companies, unmeasured) — produced nothing at all, and what was not looked at.

    Stricter than "no notable", deliberately: a company can cross no threshold
    while filing an 8-K, and that is not silence.

    SILENCE IS THE ONE CLAIM A MISSING SOURCE TURNS INTO A LIE, so it is the
    one claim that has to name what it could not see. A local dry run caught
    this: with the EDGAR fetch unavailable it reported eleven companies as
    having filed nothing, which nothing had measured. Every other section
    understates when a source fails. This one INVENTS a finding, because
    absence is its subject.

    `unmeasured` is contributors that were never fetched. A contributor that
    simply did not publish this week is not in it — a fortnightly source being
    quiet is the normal case and does not undermine the claim.
    """
    unmeasured = sorted(k for k, c in record["contributors"].items()
                        if not c["fetched"])
    out = []
    for t in record["roster"]:
        cv = record["convergence"][t]
        if cv["count"] or cv["source_failed"]:
            continue
        detail = record["verdicts"].get(t, {}).get("filings", {}).get("detail") or {}
        if detail.get("filings_in_week"):
            continue
        out.append(t)
    return sorted(out), unmeasured


def not_testable(record):
    """(ticker, contributor, basis) for every cell the rule could not be
    applied to. Carried into both renderings because "we could not tell" and
    "we looked and there was nothing" are different measurements."""
    out = []
    for t in record["roster"]:
        for key, v in sorted(record["verdicts"].get(t, {}).items()):
            if v["level"] == wd.NOT_TESTABLE and v.get("basis"):
                out.append((t, key, v["basis"]))
    return out


def failed_sources(record):
    return sorted(k for k, v in record["sources"].items()
                  if v["status"] not in ("ok", "partial"))


def bar_figure(record, ticker):
    """Close, week return and volume multiple, from the market contributors."""
    vs = record["verdicts"].get(ticker, {})
    price = (vs.get("price") or {}).get("detail") or {}
    vol = (vs.get("volume") or {}).get("detail") or {}
    cross = (vs.get("crossings") or {}).get("detail") or {}
    return {
        "ret": price.get("week_return_pct"),
        "volx": vol.get("peak_multiple"),
        "short_window": bool(cross.get("short_window")),
        "high": bool(cross.get("new_highs")),
        "low": bool(cross.get("new_lows")),
    }


def week_title(record):
    lo = date.fromisoformat(record["monday"])
    hi = date.fromisoformat(record["friday"])
    if lo.month == hi.month:
        return f"{lo.day}–{hi.day} {hi:%b %Y}"
    return f"{lo.day} {lo:%b} – {hi.day} {hi:%b %Y}"


# -------------------------------------------------------------- THE POST ----


def mono_table(record):
    """The week's moves. <=28 characters, checked rather than trusted."""
    head = f"{'':5}{'Wk%':>7}{'Vol':>6}{'52w':>4}"
    lines = [head, "-" * 26]
    rows = []
    for t in record["roster"]:
        f = bar_figure(record, t)
        if f["ret"] is None:
            continue
        rows.append((t, f))
    for t, f in sorted(rows, key=lambda r: -abs(r[1]["ret"])):
        volx = f"{f['volx']:.1f}x" if f["volx"] is not None else "  n/a"
        mark = "hi" if f["high"] else ("lo" if f["low"] else "")
        lines.append(f"{t:<5}{f['ret']:>+6.1f}%{volx:>6}{mark:>4}"
                     + ("~" if f["short_window"] else ""))
    return lines


def render_post(records):
    """A Discord embed. Filter first; the summary is what is left over."""
    rec = records[-1]
    conv, sec = converged(rec), secondary(rec)
    runs, untestable = persistent(records), not_testable(rec)
    quiet, unmeasured = silent(rec)
    dropped = []

    def para(text):
        return text + "\n\n"

    body = ""
    # --- CONVERGENCE ------------------------------------------------------
    body += para(
        f"__**Convergence**__ · a company in "
        f"{wd.CONVERGENCE_THRESHOLD}+ independent source families in one week")
    if conv:
        for t in conv:
            cv = rec["convergence"][t]
            hits = notable_verdicts(rec, t)
            line = f"**{t}** — {cv['count']} families: " \
                   f"{', '.join(cv['families'])}\n"
            for key, v in hits:
                line += f"· {key.replace('_', ' ')} — {v['figure']}\n"
            if len(body) + len(line) > DESC_BUDGET:
                dropped.append(t)
                continue
            body += line
        body += "\n"
    else:
        # RULE 1. This prints. Six of ten backfilled weeks land here, and a
        # section that disappears would read as "nothing happened" when it
        # means the filter did its job.
        body += para("Nothing converged this week.")

    # RULE 2. Listed, never promoted.
    if sec:
        body += para(f"At {wd.SECONDARY_TIER} families, not promoted: "
                     + ", ".join(sec))

    # --- PERSISTENCE ------------------------------------------------------
    body += para("__**Persistence**__ · held across sessions rather than "
                 "spiking once")
    if runs:
        for t, key, v, run in runs:
            tail = f" — **{run} weeks running**" if run > 1 else ""
            line = f"**{t}** {key.replace('_', ' ')} — {v['figure']}. " \
                   f"{v['basis']}{tail}\n"
            if len(body) + len(line) > DESC_BUDGET:
                dropped.append(f"{t}/{key}")
                continue
            body += line
        body += "\n"
    else:
        body += para("Nothing held across sessions this week.")

    # --- SILENCE ----------------------------------------------------------
    if unmeasured:
        # Not a silence claim, because the thing that would falsify it was not
        # looked at. Downgraded rather than dropped: the reader still learns
        # which companies were quiet on what did answer.
        body += para(f"__**Quiet on what answered**__ · not silence — "
                     f"{', '.join(unmeasured)} did not run, so nobody here "
                     f"has been checked for it")
        body += para(", ".join(quiet) if quiet
                     else "Nothing was quiet across the measures that ran.")
    else:
        body += para("__**Silence**__ · no measure above threshold, and "
                     "nothing filed")
        body += para(", ".join(quiet) if quiet
                     else "Every company on the roster produced something.")

    # --- WHAT COULD NOT BE MEASURED ---------------------------------------
    # Its own section, never folded into silence. A count, not a name in a
    # list: the count says both that nothing is wrong and roughly when it
    # resolves.
    if untestable:
        lines = [f"{t} {key.replace('_', ' ')}: {basis}"
                 for t, key, basis in untestable]
        text = "__**Not measurable this week**__\n" + "\n".join(lines[:6])
        if len(lines) > 6:
            text += f"\n…and {len(lines) - 6} more, in the file"
        if len(body) + len(text) < DESC_BUDGET:
            body += para(text)

    # --- WHAT THE OUTPUT CANNOT VOUCH FOR ---------------------------------
    bad = failed_sources(rec)
    if bad:
        body += para(f"⚠ Source did not answer: {', '.join(bad)}. Every "
                     f"contributor resting on it is absent from this week's "
                     f"count, so a company missing above may be unmeasured "
                     f"rather than quiet.")
    unexercised = [k for k in wd.UNEXERCISED
                   if rec["contributors"].get(k, {}).get("counted_in_denominator")]
    if unexercised:
        body += para(f"⚠ Never yet fired against a real occurrence: "
                     f"{', '.join(sorted(unexercised))}. Silence from "
                     f"{'it' if len(unexercised) == 1 else 'them'} is not "
                     f"evidence of a working check.")

    if dropped:
        body += para(f"{len(dropped)} more did not fit this post — see the "
                     f"file.")

    fields = []
    table = mono_table(rec)
    if len(table) > 2:
        fields.append({"name": "​",
                       "value": "```\n" + "\n".join(table) + "\n```"})

    material = []
    for t in rec["roster"]:
        v = rec["verdicts"].get(t, {}).get("filings") or {}
        if v.get("level") != wd.NOTABLE:
            continue
        material.append(f"**{t}** {v['figure']}")
    if material:
        fields.append({"name": "Material filings",
                       "value": "\n".join(material)[:FIELD_LIMIT]})

    den = rec["denominator"]
    return {
        "title": f"Weekly digest · {rec['week']} · {week_title(rec)}",
        "description": body.rstrip(),
        "color": 0xD29922 if conv else 0x5A6672,
        "fields": fields,
        "footer": {"text": (
            f"Re-derived from source, not from posts · "
            f"{den['families']} source families counted · "
            f"filings <1d, short volume T+1, short interest ~2wk, "
            f"FTD 2-6wk · digest/{rec['week']}.md")},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def check_post(embed):
    """Every limit this post has to live inside, measured rather than assumed.

    Returns a list of problems. The recap and the earnings calendar were both
    rebuilt narrower rather than accepting the wrap, so a renderer that could
    silently exceed the ceiling would undo that.
    """
    problems = []
    desc = embed["description"]
    if len(desc) > DESC_LIMIT:
        problems.append(f"description {len(desc)} > {DESC_LIMIT}")
    total = len(embed["title"]) + len(desc) + len(embed["footer"]["text"])
    for f in embed["fields"]:
        total += len(f["name"]) + len(f["value"])
        if len(f["value"]) > FIELD_LIMIT:
            problems.append(f"field {f['name']!r} {len(f['value'])} "
                            f"> {FIELD_LIMIT}")
        if not f["value"].startswith("```"):
            continue
        for line in f["value"].strip("`\n").split("\n"):
            if len(line) > MONO_WIDTH:
                problems.append(f"monospace line {len(line)} > {MONO_WIDTH}: "
                                f"{line!r}")
    if total > EMBED_LIMIT:
        problems.append(f"embed total {total} > {EMBED_LIMIT}")
    return problems


# -------------------------------------------------------------- THE FILE ----


def md_grid(record):
    """THE COLLAPSED GRID — every company against every source family.

    One glyph per cell rather than a block of prose per cell. That is what
    keeps the file's size flat as contributors are added: a new contributor
    either joins an existing family or adds ONE COLUMN, and no other section
    changes shape. The alternative — a subsection per company per contributor
    — is 19 x N blocks and has to be restructured the first time N grows.

    The cells that say nothing are the point. "Nobody else on the roster did
    this" is a claim only the complete grid supports, and it is the sentence
    an article is built on.
    """
    fams = sorted({wd.SOURCE_FAMILY.get(k, k)
                   for k, c in record["contributors"].items() if c["fetched"]})
    head = "| | " + " | ".join(FAMILY_COLUMN.get(f, f) for f in fams) + " |"
    rule = "|---|" + "|".join(["---"] * len(fams)) + "|"
    rows = [head, rule]
    for t in record["roster"]:
        cells = []
        for fam in fams:
            keys = [k for k in record["contributors"]
                    if wd.SOURCE_FAMILY.get(k, k) == fam]
            levels = [record["verdicts"].get(t, {}).get(k, {}).get("level")
                      for k in keys]
            levels = [x for x in levels if x]
            published = any(record["contributors"][k]["counted_in_denominator"]
                            for k in keys)
            if not published:
                cells.append(NOT_PUBLISHED)
            elif wd.NOTABLE in levels:
                cells.append(GLYPH[wd.NOTABLE])
            elif wd.SOURCE_FAILED in levels:
                cells.append(GLYPH[wd.SOURCE_FAILED])
            elif wd.NOT_TESTABLE in levels:
                cells.append(GLYPH[wd.NOT_TESTABLE])
            else:
                cells.append(GLYPH[wd.ROUTINE])
        rows.append(f"| **{t}** | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def md_detail(record, ticker):
    """Every figure with the baseline it is measured against, and a citation."""
    out = []
    for key, v in notable_verdicts(record, ticker):
        c = record["contributors"][key]
        out.append(f"- **{key.replace('_', ' ')}** — {v['figure']}")
        if v.get("basis"):
            out.append(f"  - {v['basis']}")
        d = v.get("detail") or {}
        if d.get("baseline_mean") is not None:
            out.append(f"  - baseline {d['baseline_mean']}% over "
                       f"{d['baseline_sessions']} sessions, SD "
                       f"{d['baseline_sd']}, week median "
                       f"{d['week_median_dev']:+} points "
                       f"({d.get('sd_multiple')}x SD)")
        if d.get("daily_dev"):
            out.append("  - by session: " + ", ".join(
                f"{day} {dev:+}" for day, dev in d["daily_dev"]))
        if d.get("daily_multiple"):
            out.append("  - by session: " + ", ".join(
                f"{day} {m}x" for day, m in d["daily_multiple"]))
        if d.get("baseline_volume_median") is not None:
            out.append(f"  - baseline {d['baseline_volume_median']:,} shares, "
                       f"median over {d.get('baseline_sessions')} sessions; "
                       f"peak {d.get('peak_multiple')}x")
        if d.get("baseline_median") is not None:
            out.append(f"  - baseline median {d['baseline_median']:,.0f} peak "
                       f"fails over {d.get('baseline_periods')} prior periods, "
                       f"period {d.get('period')}, "
                       f"{d.get('days')} settlement dates with a fail")
        if d.get("step_pct") is not None:
            out.append(f"  - {d['from'][1]:,} on {d['from'][0]} "
                       f"({d['from'][2]}) to {d['to'][1]:,} on {d['to'][0]} "
                       f"({d['to'][2]}), concept {d.get('concept')}")
        if d.get("prior_high") is not None and (d.get("new_highs")
                                                or d.get("new_lows")):
            out.append(f"  - prior range {d['prior_low']}–{d['prior_high']} "
                       f"over {d['window_bars']} bars")
        if d.get("settlement"):
            prev = d.get("previous")
            out.append(f"  - settlement {d['settlement']}, "
                       f"{d.get('current'):,.0f} shares"
                       + (f", against {prev[1]:,.0f} on {prev[0]}"
                          if prev else ""))
        if d.get("dates"):
            out.append(f"  - listed on {', '.join(d['dates'])} of "
                       f"{d.get('files_read')} files published")
        # LATENCY PER FIGURE, not per section. An FTD number and a short-volume
        # number in the same table are six weeks apart.
        out.append(f"  - latency: {c['latency']} · cadence {c['cadence']}"
                   + ("" if c["may_claim_persistence"]
                      else " — cannot carry a persistence claim about a week"))
        for s in v.get("sources") or []:
            out.append(f"  - source: {s}")
    return out


def render_markdown(records):
    rec = records[-1]
    conv, sec = converged(rec), secondary(rec)
    runs, untestable = persistent(records), not_testable(rec)
    quiet, unmeasured = silent(rec)
    den = rec["denominator"]
    L = []
    A = L.append

    A(f"[← Watchlist monitor](../README.md) · "
      f"[the component](../docs/weekly-digest.md)")
    A("")
    A(f"# {rec['week']} — {week_title(rec)}")
    A("")
    A(f"Re-derived from source, not aggregated from posted messages. "
      f"Schema {rec['schema']}. "
      f"Convergence threshold {den['convergence_threshold']} source families "
      f"({den['threshold_basis']}). "
      f"{den['families']} families counted this week out of "
      f"{den['registered']} registered contributors.")
    A("")
    A("**This file is generated and is never hand-edited.** An edited digest "
      "makes an article cite something that was never derived.")
    A("")

    # ------------------------------------------------------------ FILTER --
    A("## The filter")
    A("")
    A(f"### Convergence — {wd.CONVERGENCE_THRESHOLD}+ source families")
    A("")
    if conv:
        for t in conv:
            cv = rec["convergence"][t]
            A(f"#### {t} — {cv['count']} families: {', '.join(cv['families'])}")
            A("")
            if cv["component_count"] != cv["count"]:
                A(f"*{cv['component_count']} contributors fired but "
                  f"{cv['count']} families: "
                  f"{', '.join(cv['components'])}. Contributors sharing a "
                  f"family are one source read more than one way.*")
                A("")
            L.extend(md_detail(rec, t))
            A("")
    else:
        A("**Nothing converged this week.**")
        A("")
        A("This section prints when it is empty. In the ten-week backfill six "
          "weeks landed here, so an empty convergence section is the ordinary "
          "case and means the filter worked — not that the digest found "
          "nothing to look at.")
        A("")

    A(f"### At {wd.SECONDARY_TIER} families — listed, not promoted")
    A("")
    if sec:
        for t in sec:
            cv = rec["convergence"][t]
            A(f"- **{t}** — {', '.join(cv['families'])}: "
              + "; ".join(f"{k.replace('_', ' ')} {v['figure']}"
                          for k, v in notable_verdicts(rec, t)))
        A("")
        A(f"*Below the threshold on purpose. At {wd.SECONDARY_TIER} families "
          f"this tier runs 3.7 companies a week across the backfill, a fifth "
          f"of the roster.*")
    else:
        A(f"Nothing at {wd.SECONDARY_TIER} families this week.")
    A("")

    A("### Persistence — held across sessions")
    A("")
    if runs:
        for t, key, v, run in runs:
            c = rec["contributors"][key]
            A(f"- **{t}** {key.replace('_', ' ')} — {v['figure']}. "
              f"{v['basis']}."
              + (f" **{run} weeks running** "
                 f"({', '.join(r['week'] for r in records[-run:])})."
                 if run > 1 else "")
              + f" Cadence {c['cadence']}, latency {c['latency']}.")
        A("")
        A("*Only a daily-cadence contributor can appear here. The claim is "
          "enforced at construction against the contributor's declared "
          "cadence, not left to the author — see the guard in "
          "`weekly_digest.mk()`.*")
    else:
        A("Nothing held across sessions this week.")
    A("")

    if unmeasured:
        A("### Quiet on the measures that ran — NOT silence")
        A("")
        A(f"**{', '.join(unmeasured)} did not run this week.** Nobody below "
          f"has been checked against "
          f"{'it' if len(unmeasured) == 1 else 'them'}, so this is not a "
          f"silence claim and must not be quoted as one. Silence is the one "
          f"section a missing source turns into an invention rather than an "
          f"understatement, because absence is its subject.")
        A("")
    else:
        A("### Silence — no measure above threshold, and nothing filed")
        A("")
    A(", ".join(f"**{t}**" for t in quiet) if quiet
      else "Every company on the roster produced something this week.")
    A("")
    if quiet:
        A("Per company, so the absence can be quoted:")
        A("")
        for t in quiet:
            parts = []
            for key in sorted(rec["verdicts"].get(t, {})):
                v = rec["verdicts"][t][key]
                if v["level"] != wd.ROUTINE:
                    continue
                fig = v.get("figure")
                # "-0pts" is a rounding artefact reading as a measurement.
                if fig in ("-0pts", "+0pts", "-0.0%", "+0.0%"):
                    fig = "flat"
                parts.append(f"{key.replace('_', ' ')}"
                             + (f" {fig}" if fig else ""))
            A(f"- **{t}** — " + "; ".join(parts))
        A("")

    A("### Not measurable this week")
    A("")
    if untestable:
        A("Neither a finding nor a fault. A count rather than a bare name, "
          "because the count says both that nothing is wrong and roughly when "
          "it resolves.")
        A("")
        for t, key, basis in untestable:
            A(f"- **{t}** {key.replace('_', ' ')} — {basis}")
    else:
        A("Every rule could be applied to every company this week.")
    A("")

    # -------------------------------------------------------------- WEEK --
    A("## The week")
    A("")
    if rec["sources"].get("bars", {}).get("status") not in ("ok", "partial"):
        A(f"**The bar series did not answer "
          f"({rec['sources'].get('bars', {}).get('note', 'no detail')}), so "
          f"every cell below is unmeasured rather than flat.** A dash here is "
          f"not a zero.")
        A("")
    A("| | week % | peak volume | 52w | close |")
    A("|---|---|---|---|---|")
    for t in rec["roster"]:
        f = bar_figure(rec, t)
        if f["ret"] is None:
            A(f"| **{t}** | — | — | — | — |")
            continue
        pos = "new high" if f["high"] else ("new low" if f["low"] else "")
        if f["short_window"]:
            pos += " (short window)"
        px = ((rec["verdicts"][t].get("price") or {}).get("detail") or {})
        A(f"| **{t}** | {f['ret']:+.1f}% | "
          f"{f['volx']}x | {pos or '·'} | "
          f"{px.get('sessions_in_week', '—')} sessions |")
    A("")

    A("### Material filings")
    A("")
    any_filing = False
    for t in rec["roster"]:
        v = rec["verdicts"].get(t, {}).get("filings") or {}
        d = v.get("detail") or {}
        for item in d.get("always_post_items") or []:
            any_filing = True
            A(f"- **{t}** {item['form']} {', '.join(item['items'])} — "
              f"{', '.join(item['labels'])}, filed {item['filed']} · "
              f"[{item['accession']}]({item['url']})")
        if v.get("level") == wd.NOTABLE and not (d.get("always_post_items")):
            any_filing = True
            A(f"- **{t}** {v['figure']}, filed this week")
            for s in v.get("sources") or []:
                A(f"  - {s}")
    if not any_filing:
        A("No material filing on the roster this week. Routine filings are in "
          "the grid below; presence alone fires for 57% of roster-weeks and "
          "is not reported as an event.")
    A("")

    # -------------------------------------------------------------- GRID --
    A("## The grid")
    A("")
    A("Every company against every source family, including the cells that "
      "produced no finding. The cells saying nothing are the point: *nobody "
      "else on the roster did this* is a claim only the complete grid "
      "supports.")
    A("")
    A(f"`{GLYPH[wd.NOTABLE]}` above threshold · "
      f"`{GLYPH[wd.ROUTINE]}` measured, routine · "
      f"`{GLYPH[wd.NOT_TESTABLE]}` rule not applicable · "
      f"`{GLYPH[wd.SOURCE_FAILED]}` source failed · "
      f"`{NOT_PUBLISHED}` nothing published this week")
    A("")
    A(md_grid(rec))
    A("")
    A("Columns are **families, not contributors**. `market` collapses price, "
      "volume and 52-week crossings, which are three readings of one Alpaca "
      "bar series — they co-occur at 4-5x what independence would predict, "
      "and counting them separately inflates convergence for the one company "
      "a filter should never need to surface. A contributor added later "
      "joins a family or adds one column; no other section changes shape.")
    A("")

    # -------------------------------------------------------- PROVENANCE --
    A("## Provenance")
    A("")
    A("### Sources")
    A("")
    A("| source | status | requests | seconds | note |")
    A("|---|---|---|---|---|")
    for k, s in sorted(rec["sources"].items()):
        A(f"| {k} | {s['status']} | {s['requests']} | {s['seconds']} | "
          f"{s['note']} |")
    A("")
    bad = failed_sources(rec)
    if bad:
        A(f"**{', '.join(bad)} did not answer.** Every contributor resting on "
          f"a failed source is absent from this week's count, so a company "
          f"reported quiet above may be unmeasured rather than quiet. Do not "
          f"quote an absence from this week without checking here first.")
        A("")

    A("### Contributors")
    A("")
    A("| contributor | family | cadence | may claim persistence | counted |")
    A("|---|---|---|---|---|")
    for k, c in sorted(rec["contributors"].items()):
        A(f"| {k} | {wd.SOURCE_FAMILY.get(k, k)} | {c['cadence']} | "
          f"{'yes' if c['may_claim_persistence'] else 'no'} | "
          f"{'yes' if c['counted_in_denominator'] else 'no — nothing published'} |")
    A("")
    if den["not_published"]:
        A(f"Not counted this week, and behaving normally: "
          f"{', '.join(den['not_published'])}. A fortnightly source is silent "
          f"in most weeks because nothing was published, not because nothing "
          f"happened, and counting it would make convergence look rarer than "
          f"it is.")
        A("")

    unexercised = {k: why for k, why in wd.UNEXERCISED.items()
                   if k in rec["contributors"]}
    A("### Contributors whose rule has never fired")
    A("")
    if unexercised:
        for k, why in sorted(unexercised.items()):
            A(f"- **{k}** — {why}")
        A("")
        A("An empty section from one of these cannot yet be read as a working "
          "one. It is the same standing trap as an EDGAR form type that has "
          "never matched: a rule matching nothing looks exactly like one whose "
          "occurrences have not happened.")
    else:
        A("Every registered contributor has fired against a real occurrence.")
    A("")

    A("### Roster")
    A("")
    A(f"{len(rec['roster'])} companies, from `watchlist.py` and nowhere else: "
      f"{', '.join(rec['roster'])}.")
    A("")
    A(f"Generated {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}"
      f" · `weekly_digest.py` schema {rec['schema']}.")
    A("")
    return "\n".join(L)


# --------------------------------------------------------------- DRY RUN ----


def dry_run(week_key, prior=3):
    records, _ctx = wd.derive_one(week_key, prior_weeks=prior)
    rec = records[-1]
    embed = render_post(records)
    md = render_markdown(records)
    problems = check_post(embed)

    print("=" * 72)
    print(f"POST — {rec['week']}")
    print("=" * 72)
    print(f"title: {embed['title']}")
    print("-" * 72)
    print(embed["description"])
    for f in embed["fields"]:
        print("-" * 72)
        print(f"[field] {f['name']!r}")
        print(f["value"])
    print("-" * 72)
    print(f"footer: {embed['footer']['text']}")
    print("=" * 72)

    desc = embed["description"]
    total = (len(embed["title"]) + len(desc) + len(embed["footer"]["text"])
             + sum(len(f["name"]) + len(f["value"]) for f in embed["fields"]))
    widths = [len(x) for f in embed["fields"]
              if f["value"].startswith("```")
              for x in f["value"].strip("`\n").split("\n")]
    print(f"description {len(desc)}/{DESC_LIMIT}   "
          f"embed total {total}/{EMBED_LIMIT}   "
          f"widest monospace line {max(widths) if widths else 0}/{MONO_WIDTH}")
    print("LIMITS OK" if not problems else "PROBLEMS: " + "; ".join(problems))
    print()
    return records, embed, md, problems


def main():
    weeks = [w.strip() for w in
             os.environ.get("DIGEST_WEEKS", "").split(",") if w.strip()]
    if not weeks:
        sys.exit("Set DIGEST_WEEKS=2026-W31,2026-W30 — a dry run renders named "
                 "weeks and writes nothing. There is no live path yet.")
    outdir = os.environ.get("DIGEST_DIR", "digest")

    wd.demonstrate_cadence_guard()
    allmd = []
    failures = 0
    for week in weeks:
        records, embed, md, problems = dry_run(week)
        failures += len(problems)
        path = os.path.join(outdir, f"{week}.md")
        allmd.append((path, md, records[-1]))

    print("=" * 72)
    print("FILE")
    print("=" * 72)
    for path, md, rec in allmd:
        conv = converged(rec)
        print(f"  {path:<24} {len(md) / 1024:5.1f} KB  "
              f"{len(md.splitlines()):4d} lines  "
              f"converged: {', '.join(conv) if conv else 'nothing'}")
    if os.environ.get("DIGEST_WRITE", "").lower() in ("1", "true", "yes"):
        os.makedirs(outdir, exist_ok=True)
        for path, md, _ in allmd:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(md)
            print(f"  wrote {path}")
    else:
        print("  DIGEST_WRITE unset — nothing written.")
        for path, md, _ in allmd:
            print()
            print("=" * 72)
            print(path)
            print("=" * 72)
            print(md)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
