#!/usr/bin/env python3
"""Tests for volume_spike's session series and peak selection. No network.

WHY THIS EXISTS NOW. `volume_spike.py` had no suite at all, and on 2026-08-26
it started losing alerts. `ratio_for` divides today's cumulative volume by the
baseline's cumulative volume THROUGH THE CURRENT WALL-CLOCK HOUR, so the
denominator grows as the day advances whether or not the stock keeps trading:

    a stock reading R at hour h reads 1 + (R-1) * S(h)/S(h') at a later h'

Nothing re-evaluated a past hour and state resets at ET midnight, so when
GitHub stopped delivering this workflow's morning fires the readings for those
hours were never taken. Measured: the first look of a session moved from 09:09
ET (19 of 19 sessions) to 12:49 ET (16 of 16), on distributions that do not
overlap, and two sessions were first looked at after the close.

The fixtures below are the shape that costs an alert: a burst in one hour
followed by ordinary trading. Under the old code a 4.9x at 10:00 read 3.0x by
noon and 2.2x by the close; the tier that reaches Discord depended on when
GitHub felt like delivering a fire.

EVERY CHECK HERE HAS BEEN WATCHED TO FAIL under a named one-line change to
volume_spike.py. The sweep is in backup/local/reviews/.
"""

import os
import sys

# Refuses to load without them, and fetches nothing at import.
os.environ.setdefault("ALPACA_KEY_ID", "offline-suite")
os.environ.setdefault("ALPACA_SECRET_KEY", "offline-suite")

import volume_spike as vs

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


# A burst at 10:00 on an otherwise ordinary day. 5,000 shares pre-market at
# 04:00, so the extended-hours asymmetry below has something to bite on.
BURST = {4: 5_000.0, 9: 40_000.0, 10: 300_000.0, 11: 20_000.0, 12: 20_000.0}
# Twelve flat baseline sessions: MIN_BASELINE_BARS is 10, so the slot baseline
# is thick enough for the normalised branch to engage from hour 10.
FLAT = [{9: 40_000.0, 10: 30_000.0, 11: 30_000.0, 12: 30_000.0}
        for _ in range(12)]
FULL = [130_000.0] * 12


def metrics(series, hour, volume=None, close=100.0, prev=100.0):
    return {"volume": volume if volume is not None else series[-1][1],
            "hour": hour, "series": series, "close": close, "prev_close": prev}


def main():
    print("CUMULATIVE_THROUGH IS NOT ELAPSED_THROUGH")
    # Mutation: `if h <= hour` -> `if vs.SESSION_OPEN.hour <= h <= hour`, i.e.
    # make cumulative_through a copy of elapsed_through. The numerator has
    # always counted pre-market volume (daily_totals sums every bar of the
    # day) while the slot baseline counts only 09:00 onward. Collapsing the
    # two would quietly change the live ratio for every ticker that trades
    # pre-market.
    day = {4: 5_000.0, 9: 40_000.0, 10: 10_000.0}
    check("cumulative_through counts the pre-market hour",
          vs.cumulative_through(day, 10) == 55_000.0,
          f"got {vs.cumulative_through(day, 10):,.0f}")
    check("elapsed_through does not",
          vs.elapsed_through(day, 10) == 50_000.0,
          f"got {vs.elapsed_through(day, 10):,.0f}")

    print("\nTHE SERIES REPRODUCES THE LIVE READING")
    # Mutation: `cumulative_through(today_slots, hour)` -> `elapsed_through(...)`.
    # THE REGRESSION GUARANTEE. The last entry must equal what daily_totals
    # computes for today, or wiring the series in moved a published number
    # while claiming to recover past ones.
    s = vs.session_series(BURST, FLAT, FULL, 12)
    check("the last entry equals today's full volume",
          s[-1][1] == sum(BURST.values()),
          f"{s[-1][1]:,.0f} vs {sum(BURST.values()):,.0f}")
    live_ratio, live_basis = vs.ratio_for(
        sum(BURST.values()), 12,
        [v for v in (vs.elapsed_through(d, 12) for d in FLAT) if v > 0], FULL)
    check("and the last ratio equals ratio_for at that hour",
          abs(s[-1][2] - live_ratio) < 1e-9 and s[-1][3] == live_basis,
          f"series {s[-1][2]:.4f} vs ratio_for {live_ratio:.4f}")

    print("\nTHE DECAY THE BACKFILL EXISTS FOR")
    # Mutation: the whole series loop replaced by a single entry at upto_hour.
    by_hour = {h: r for h, _v, r, _b in s}
    # THROUGH .get(), NOT [], and that is not defensive style. Removing the
    # backfill leaves one entry, and subscripting a missing hour raises
    # KeyError — which takes the suite down instead of failing the check, and
    # a mutation that crashes the harness has shown nothing. The sweep
    # reported exactly that before this was changed.
    check("the series covers every elapsed hour, not just the last",
          {9, 10, 11, 12} <= set(by_hour), f"got hours {sorted(by_hour)}")
    check("THE RATIO DECAYS ACROSS THE SESSION",
          by_hour.get(10, 0) > by_hour.get(11, 0) > by_hour.get(12, 0),
          "  ".join(f"{h}:00 {by_hour[h]:.2f}x" for h in sorted(by_hour)))
    check("the peak hour crosses a tier the last hour does not",
          vs.tier_for(by_hour.get(10, 0)) == 3.0
          and vs.tier_for(by_hour.get(12, 0)) == 1.5,
          f"peak tier {vs.tier_for(by_hour.get(10, 0))}, "
          f"late tier {vs.tier_for(by_hour.get(12, 0))}")

    print("\nTHE NORMALISE GATE STILL HOLDS")
    # Mutation: drop `hour >= NORMALISE_FROM_HOUR` from ratio_for. Hour 09 is
    # one venue's opening sixty minutes; BKKT read 16.8x on 35,588 shares
    # there and was not a spike. Backfilling must not reach behind that gate.
    basis = {h: b for h, _v, _r, b in s}
    check("hours below NORMALISE_FROM_HOUR stay on the full-session basis",
          basis.get(9) == "full-session", f"got {basis.get(9)}")
    check("hours at or above it normalise",
          basis.get(10) == basis.get(12) == "normalised",
          f"got {basis.get(10)}, {basis.get(12)}")

    # Mutation: drop `len(slot_base) >= MIN_BASELINE_BARS`.
    thin = vs.session_series(BURST, FLAT[:3], FULL, 12)
    check("a slot baseline under MIN_BASELINE_BARS falls back",
          {b for _h, _v, _r, b in thin} == {"full-session"},
          f"got {sorted({b for _h, _v, _r, b in thin})}")

    print("\nFLOORS ARE APPLIED PER HOUR, NOT AGAINST THE DAY'S TOTAL")
    # Mutation: in peak_reading, test `m["volume"]` instead of the hour's own
    # `volume`. A morning ratio measured on 5,000 shares must not be qualified
    # by an afternoon that later traded 500,000.
    # THE EARLY HOUR MUST WIN ON RATIO, or the check passes for the wrong
    # reason. The first fixture here gave 10:00 a LOWER ratio than 11:00, so
    # 11:00 was the peak whether the floor was applied per hour or not, and the
    # sweep reported the mutation as not reddened. 10:00 now reads 4.55x on
    # 5,000 shares against 11:00's 3.01x on 605,000.
    tiny_then_busy = {9: 1_000.0, 10: 4_000.0, 11: 600_000.0}
    base = [{9: 1_000.0, 10: 100.0, 11: 200_000.0} for _ in range(12)]
    ss = vs.session_series(tiny_then_busy, base, [201_100.0] * 12, 11)
    # [0] would IndexError when the hour is absent, which is what removing
    # the backfill does — a crash, not a failure, and a crash shows nothing.
    early = next(((h, v, r) for h, v, r, _b in ss if h == 10), (None, 0, 0))
    check("the 10:00 reading is the day's HIGHEST ratio on a tiny volume",
          early[1] < vs.MIN_ALERT_VOLUME
          and early[2] == max(r for _h, _v, r, _b in ss),
          f"{early[1]:,.0f} shares at {early[2]:.2f}x")
    best = vs.peak_reading(metrics(ss, 11))
    check("SO IT IS NOT THE PEAK, despite the highest ratio of the day",
          best is not None and best[0] != 10,
          f"peak hour {best[0] if best else None}")

    # Mutation: drop the `basis == "normalised"` floor from peak_reading.
    # BETWEEN THE TWO FLOORS, which is the only band where the normalised one
    # does any work: 30,000 shares clears MIN_ALERT_VOLUME (25,000) and fails
    # MIN_NORMALISED_VOLUME (46,880) at 3.0x on a normalised basis. The first
    # fixture used 300 shares, which the first floor already rejected, so
    # deleting the second changed nothing and the sweep said so.
    between = vs.session_series({9: 10_000.0, 10: 20_000.0},
                                [{9: 5_000.0, 10: 5_000.0} for _ in range(12)],
                                [20_000.0] * 12, 10)
    at_ten = next(((v, r, b) for h, v, r, b in between if h == 10),
                  (0, 0, "absent"))
    check("the fixture sits between the two volume floors",
          vs.MIN_ALERT_VOLUME <= at_ten[0] < vs.MIN_NORMALISED_VOLUME
          and at_ten[2] == "normalised" and at_ten[1] >= vs.TIERS[0],
          f"{at_ten[0]:,.0f} shares at {at_ten[1]:.1f}x, {at_ten[2]}")
    check("a normalised reading under MIN_NORMALISED_VOLUME is not a peak",
          vs.peak_reading(metrics(between, 10)) is None,
          f"got {vs.peak_reading(metrics(between, 10))}")

    print("\nPEAK SELECTION")
    # Mutation: `ratio > best[2]` -> `ratio >= best[2]`. A tie must go to the
    # earlier hour: the question is when the move started.
    # A GENUINE TIE HAS TO BE CONSTRUCTED, and the first attempt was not one.
    # The baseline is flat, so S(10) = 70,000 and S(11) = 100,000; a tie needs
    # today to trade exactly proportionally between the two hours, which is
    # 210,000 by 10:00 and 300,000 by 11:00. Feeding a quiet hour instead just
    # decays the ratio and tests nothing about ties.
    tied = vs.session_series({9: 40_000.0, 10: 170_000.0, 11: 90_000.0},
                             FLAT, FULL, 11)
    same = [r for _h, _v, r, _b in tied]
    # Both guarded against a one-entry series: removing the backfill leaves one
    # hour, and same[-2] would IndexError while peak_reading(...)[0] would
    # subscript None. Either is a crash, and a crash shows nothing.
    check("the fixture really does tie, to the digit",
          len(same) >= 2 and abs(same[-1] - same[-2]) < 1e-9,
          "  ".join(f"{h}:00 {r:.6f}x" for h, _v, r, _b in tied))
    tied_peak = vs.peak_reading(metrics(tied, 11))
    check("a tied ratio keeps the EARLIER hour",
          tied_peak is not None and tied_peak[0] == 10,
          f"peak hour {tied_peak[0] if tied_peak else None}")

    print("\nEVALUATE ALERTS AT THE PEAK, NOT THE DECAYED READING")
    # Mutation: `best = peak_reading(m)` -> use ratio_for at m["hour"].
    state = {"date": "never", "alerted": {}}
    alerts = vs.evaluate({"ABTC": metrics(s, 12, close=12.0, prev=10.0)}, state)
    check("ONE ALERT, AT THE PEAK TIER", len(alerts) == 1
          and alerts[0]["tier"] == 3.0,
          f"got {[(a['tier'], round(a['ratio'], 2)) for a in alerts]}")
    check("it carries the hour the peak was read at",
          alerts[0]["peak_hour"] == 10 and alerts[0]["read_hour"] == 12)
    check("and the volume of that hour, not the day's",
          alerts[0]["volume"] == vs.cumulative_through(BURST, 10),
          f"got {alerts[0]['volume']:,.0f}")

    # Mutation: delete the `state["alerted"].get(symbol, 0) >= tier` guard.
    again = vs.evaluate({"ABTC": metrics(s, 12, close=12.0, prev=10.0)}, state)
    check("a second run at the same peak posts nothing", again == [],
          f"got {len(again)} alert(s)")

    # Mutation: `state["alerted"][symbol] = tier` -> `= 0`.
    check("the ratchet recorded the peak tier", state["alerted"] == {"ABTC": 3.0},
          f"got {state['alerted']}")

    print("\nTHE POST SAYS WHICH ROWS ARE RECOVERED")
    # Mutation: `mark = "*" if ... else " "` -> always " ".
    embed = vs.build_embed(alerts)
    block = embed["fields"][0]["value"]
    rows = [r for r in block.split("\n") if r and not r.startswith("```")]
    check("the recovered row is marked", rows and "*" in rows[0], rows[0] if rows else "")
    check("EVERY ROW IS AT OR UNDER 28 CHARACTERS",
          all(len(r) <= 28 for r in rows),
          f"widths {[len(r) for r in rows]}")
    # Mutation: `recovered = ""` unconditionally.
    check("the footer states the hour the peak was read at",
          "10:00 ET" in embed["footer"]["text"],
          embed["footer"]["text"][-60:])

    # Mutation: `a.get("peak_hour") != a.get("read_hour")` -> `!= None`.
    live = dict(alerts[0], peak_hour=12, read_hour=12)
    embed2 = vs.build_embed([live])
    rows2 = [r for r in embed2["fields"][0]["value"].split("\n")
             if r and not r.startswith("```")]
    check("A LIVE ROW IS NOT MARKED", rows2 and "*" not in rows2[0],
          rows2[0] if rows2 else "")
    check("and its footer carries no recovery note",
          "peak read at" not in embed2["footer"]["text"])

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
