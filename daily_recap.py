#!/usr/bin/env python3
"""
Daily post-close recap -> Discord.

Pulls end-of-day OHLCV, builds a performance table and a chart grid, and posts
both to a webhook.

Data source: Twelve Data (free tier, ~800 requests/day; this needs 11).

Not Yahoo/yfinance: Yahoo deprecated its API and discourages scraping, so
anything built on it breaks unpredictably.
Not Stooq: it enforces a low PER-IP daily quota and returns a plain-text
"Exceeded the daily hits limit" body with HTTP 200. GitHub Actions runners
share an Azure IP pool, so that quota is routinely already spent by unrelated
jobs before this one starts. Stooq is kept as a fallback for local runs only.
"""

import csv
import io
import json
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:          # no tzdata: assume EDT
    EASTERN = timezone(timedelta(hours=-4))

import matplotlib
matplotlib.use("Agg")  # headless: no display on the runner
import matplotlib.pyplot as plt
import requests

# ------------------------------------------------------------------ CONFIG

# Display label -> Stooq symbol. US equities are lowercase with a .us suffix.
# Recently renamed tickers may still sit under their old symbol on Stooq, so
# override here if one stops resolving.
TICKERS = {
    "BGDE": "bgde.us",
    "ANY":  "any.us",
    "NUAI": "nuai.us",
    "SLNH": "slnh.us",
    "DGXX": "dgxx.us",
    "BKKT": "bkkt.us",
    "MARA": "mara.us",
    "WYFI": "wyfi.us",
    "IREN": "iren.us",
    "CLSK": "clsk.us",
    "VIP":  "vip.us",   # renamed from GREE Jul 2026; try gree.us if this fails
}

# Volume flagging. Matches the first tier in volume_spike.py so the intraday
# alert and this end-of-day confirmation agree on what "unusual" means.
# Note this figure is CONSOLIDATED (sip), unlike the intraday alerter's IEX
# proxy, so it is the authoritative version of the same signal.
VOLUME_FLAG_TIER = 1.5

# Below this, a consolidated session is too thin for the ratio to mean much.
MIN_FLAG_VOLUME = 50_000

# Chart mode: "intraday" plots today's session; "daily" plots CHART_DAYS of
# closes. Intraday requires Alpaca — the fallback providers have no usable
# intraday data, so the chart silently reverts to daily on that path.
CHART_MODE = "intraday"
CHART_INTERVAL = "5Min"
CHART_EXTENDED = False   # True to include 04:00-20:00 ET rather than 09:30-16:00

CHART_DAYS = 60        # trading days shown per sparkline in "daily" mode
VOL_AVG_DAYS = 30      # baseline for the volume comparison
GRID_COLS = 2

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
# Dry run: build everything, print the table, save the chart, post nothing.
# Lets you validate ticker symbols before creating the webhook.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
CHART_FILE = "recap.png"
ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
# Consolidated (all-exchange) data. IEX alone would give a wrong close — it
# sits out the closing auction — and volume a fraction of the real figure.
#
# NOTE: "delayed_sip" is a STREAMING/latest-quote feed name and is rejected by
# the historical bars endpoint with HTTP 400. Historical bars use "sip". Free
# plans are restricted on RECENCY rather than on the feed, so requests ending
# outside the last 15 minutes are generally permitted. The recap runs ~90 min
# after the close, so this costs nothing.
ALPACA_FEED = "sip"
ALPACA_DELAY_MINUTES = 20
ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"

TWELVEDATA_KEY = os.environ.get("TWELVEDATA_KEY", "").strip()
TWELVEDATA_URL = ("https://api.twelvedata.com/time_series"
                  "?symbol={symbol}&interval=1day&outputsize=300&apikey={key}")
# Free tier allows 8 requests/minute, so pace them.
TWELVEDATA_GAP = 8.0
STOOQ_CSV = "https://stooq.com/q/d/l/?s={symbol}&i=d"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

UP, DOWN, FLAT = "#3FB950", "#F85149", "#8B949E"


def fetch_alpaca_all(symbols):
    """One call for every ticker. Returns {symbol: [(date, close, volume)]}.

    Returns None (not {}) if the plan can't access the feed, so the caller
    knows to fall back rather than treating it as "no data".
    """
    out, token, pages = {}, None, 0
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=430)).date().isoformat()
    # Stay clear of the real-time window that free plans can't access.
    end = (now - timedelta(minutes=ALPACA_DELAY_MINUTES)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    while pages < 6:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "limit": 10000,
            "feed": ALPACA_FEED,
            "adjustment": "all",
        }
        if token:
            params["page_token"] = token
        try:
            r = requests.get(ALPACA_BARS, params=params, timeout=(10, 30),
                             headers={"APCA-API-KEY-ID": ALPACA_KEY_ID,
                                      "APCA-API-SECRET-KEY": ALPACA_SECRET})
        except requests.RequestException as e:
            print(f"  Alpaca request failed: {type(e).__name__}")
            return None
        if r.status_code in (401, 403):
            print(f"  Alpaca: {ALPACA_FEED} not permitted on this plan "
                  f"(HTTP {r.status_code}) — falling back")
            return None
        if r.status_code != 200:
            print(f"  Alpaca: HTTP {r.status_code} {r.text[:160]} — "
                  f"falling back")
            return None
        data = r.json()
        for symbol, rows in (data.get("bars") or {}).items():
            out.setdefault(symbol, []).extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break

    series = {}
    for symbol, rows in out.items():
        parsed = []
        for b in rows:
            try:
                parsed.append((
                    datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date(),
                    float(b["c"]),
                    float(b.get("v") or 0),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        series[symbol] = sorted(parsed)
    return series


def fetch_twelvedata(symbol):
    """Twelve Data time_series -> [(date, close, volume), ...] oldest first."""
    url = TWELVEDATA_URL.format(symbol=symbol, key=TWELVEDATA_KEY)
    try:
        r = requests.get(url, headers=HEADERS, timeout=(10, 30))
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"    fetch failed: {type(e).__name__}")
        return []

    if data.get("status") != "ok" or "values" not in data:
        # Surface the provider's own message rather than guessing.
        print(f"    no data: {str(data.get('message', data))[:120]}")
        return []

    rows = []
    for v in data["values"]:
        try:
            rows.append((
                datetime.strptime(v["datetime"][:10], "%Y-%m-%d").date(),
                float(v["close"]),
                float(v.get("volume") or 0),
            ))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(rows)          # API returns newest first


def fetch_stooq(symbol):
    """Return [(date, close, volume), ...] oldest first, or [] on failure."""
    try:
        r = requests.get(STOOQ_CSV.format(symbol=symbol),
                         headers=HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"    fetch failed: {type(e).__name__}")
        return []
    if r.status_code != 200 or not r.text.startswith("Date"):
        # Stooq returns a plain-text error body with HTTP 200 for both unknown
        # symbols and quota exhaustion. Print it — the distinction matters.
        print(f"    no data (HTTP {r.status_code}): {r.text.strip()[:120]!r}")
        return []

    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            rows.append((
                datetime.strptime(row["Date"], "%Y-%m-%d").date(),
                float(row["Close"]),
                float(row["Volume"] or 0),
            ))
        except (ValueError, KeyError):
            continue
    return rows


def fetch_series(symbol, stooq_symbol):
    """Twelve Data when a key is present, Stooq otherwise."""
    if TWELVEDATA_KEY:
        return fetch_twelvedata(symbol)
    return fetch_stooq(stooq_symbol)


def fetch_intraday(symbols):
    """Today's bars per symbol, for the day chart. {symbol: [closes]}."""
    now = datetime.now(timezone.utc)
    today_et = now.astimezone(EASTERN).date()
    open_hour = dtime(4, 0) if CHART_EXTENDED else dtime(9, 30)
    start = datetime.combine(today_et, open_hour, tzinfo=EASTERN)
    end = now - timedelta(minutes=ALPACA_DELAY_MINUTES)
    if end <= start:
        return {}

    out, token, pages = {}, None, 0
    while pages < 6:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": CHART_INTERVAL,
            "start": start.astimezone(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
            "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "limit": 10000,
            "feed": ALPACA_FEED,
        }
        if token:
            params["page_token"] = token
        try:
            r = requests.get(ALPACA_BARS, params=params, timeout=(10, 30),
                             headers={"APCA-API-KEY-ID": ALPACA_KEY_ID,
                                      "APCA-API-SECRET-KEY": ALPACA_SECRET})
        except requests.RequestException as e:
            print(f"  intraday fetch failed: {type(e).__name__}")
            return out
        if r.status_code != 200:
            print(f"  intraday: HTTP {r.status_code} — chart falls back to daily")
            return out
        data = r.json()
        for symbol, rows in (data.get("bars") or {}).items():
            out.setdefault(symbol, []).extend(
                float(b["c"]) for b in rows if b.get("c") is not None)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break
    return out


def summarise(label, rows):
    """Reduce a price series to the figures shown in the table."""
    if len(rows) < 2:
        return None
    closes = [c for _, c, _ in rows]
    vols = [v for _, _, v in rows]
    last, prev = closes[-1], closes[-2]

    window = closes[-252:]          # ~1 trading year
    vol_base = vols[-VOL_AVG_DAYS - 1:-1] or [0]
    avg_vol = sum(vol_base) / len(vol_base)

    return {
        "label": label,
        "date": rows[-1][0],
        "close": last,
        "pct": (last - prev) / prev * 100 if prev else 0.0,
        "vol": vols[-1],
        "vol_x": (vols[-1] / avg_vol) if avg_vol else 0.0,
        "hi": max(window),
        "lo": min(window),
        "series": closes[-CHART_DAYS:],
        "prev_close": prev,
        "intraday": None,          # filled in later when available
    }


def session_in_progress(latest):
    """True if the newest bar is today's and the US close hasn't happened yet.

    Twelve Data's 1day interval includes the current, incomplete session. A
    partial bar looks like a real one except the volume is a fraction of
    normal — which silently corrupts both the % change and the volume ratio.
    """
    now = datetime.now(EASTERN)
    return latest == now.date() and now.time() < dtime(16, 0)


def human_vol(v):
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div:
            return f"{v/div:.1f}{suffix}"
    return f"{v:.0f}"


def flagged(stats, partial):
    """Tickers whose completed-session volume was unusual.

    Returns [] for a partial session: today's incomplete volume against a
    full-day average understates every ratio, so flagging would be wrong.
    """
    if partial:
        return []
    return sorted(
        (s for s in stats
         if s["vol_x"] >= VOLUME_FLAG_TIER and s["vol"] >= MIN_FLAG_VOLUME),
        key=lambda s: s["vol_x"], reverse=True)


def build_table(stats, partial=False):
    """Monospace table, sized for a phone.

    Discord mobile wraps code blocks past ~28 characters. Absolute volume is
    dropped from the grid — the x30d ratio is the actual signal, and the raw
    share count is repeated for flagged names in the footer where it matters.
    """
    hot = {s["label"] for s in flagged(stats, partial)}
    stats = sorted(stats, key=lambda s: s["pct"], reverse=True)
    lines = [f"{'':5}{'Close':>6}{'Chg':>7}{'Vol':>5} {'52w':>3}"]
    lines.append("-" * 26)
    for s in stats:
        span = s["hi"] - s["lo"]
        pos = ((s["close"] - s["lo"]) / span * 100) if span else 0
        mark = "*" if s["label"] in hot else " "
        lines.append(
            f"{s['label']:<5}{s['close']:>6.2f}{s['pct']:>6.1f}%"
            f"{s['vol_x']:>4.1f}x{mark}{pos:>3.0f}"
        )
    return "\n".join(lines)


def build_chart(stats):
    """Grid of sparklines. Returns PNG bytes.

    In intraday mode each panel is today's session with a dashed line at the
    previous close, and the fill sits between the two — so the shaded area
    reads directly as gain or loss on the day. Colour is driven by the same
    figure shown in the title, unlike daily mode where a 60-day direction and
    a one-day percentage could disagree.
    """
    n = len(stats)
    rows = (n + GRID_COLS - 1) // GRID_COLS
    fig, axes = plt.subplots(rows, GRID_COLS,
                             figsize=(GRID_COLS * 3.4, rows * 1.9))
    fig.patch.set_facecolor("#0D1117")
    axes = axes.flatten() if n > 1 else [axes]

    intraday_used = 0
    for ax, s in zip(axes, stats):
        series = s.get("intraday") or s["series"]
        is_intraday = bool(s.get("intraday"))
        intraday_used += is_intraday

        if is_intraday:
            # Title and colour now describe the same thing: the day's move.
            colour = UP if s["pct"] >= 0 else DOWN
            baseline = s.get("prev_close") or series[0]
        else:
            colour = UP if series[-1] >= series[0] else DOWN
            baseline = min(series)

        ax.plot(series, color=colour, linewidth=1.4)
        ax.fill_between(range(len(series)), series, baseline,
                        color=colour, alpha=0.12)

        if is_intraday and s.get("prev_close"):
            ax.axhline(s["prev_close"], color=FLAT, linewidth=0.8,
                       linestyle=(0, (4, 3)), alpha=0.7)
            # Keep the previous close on screen even on a big gap.
            lo = min(min(series), s["prev_close"])
            hi = max(max(series), s["prev_close"])
            pad = (hi - lo) * 0.08 or hi * 0.01
            ax.set_ylim(lo - pad, hi + pad)

        ax.set_title(f"{s['label']}  {s['pct']:+.1f}%",
                     color="#E6EDF3", fontsize=10, pad=4)
        ax.set_facecolor("#0D1117")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)

    for ax in axes[n:]:
        ax.set_visible(False)

    if intraday_used == n and n:
        window = "04:00-20:00 ET" if CHART_EXTENDED else "09:30-16:00 ET"
        caption = f"today's session  {window}   - - -  previous close"
    elif intraday_used:
        caption = f"today's session ({intraday_used}/{n}); rest {CHART_DAYS}-day close"
    else:
        caption = f"{CHART_DAYS}-day close"
    fig.suptitle(caption, color=FLAT, fontsize=9, y=0.99)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def post(text, png):
    """Discord webhook, multipart so the chart embeds inline."""
    payload = {"content": f"```\n{text}\n```"}
    try:
        r = requests.post(
            WEBHOOK_URL,
            data={"payload_json": json.dumps(payload)},
            files={"file": ("recap.png", png, "image/png")},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"webhook failed: {type(e).__name__}")
        return False
    if r.status_code >= 300:
        print(f"webhook returned {r.status_code}: {r.text[:200]}")
        return False
    return True


def main():
    if DRY_RUN:
        print("DRY RUN — nothing will be posted.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL_MARKET is not set.")

    stats, missing = [], []
    alpaca, source = None, "unknown"

    if ALPACA_KEY_ID and ALPACA_SECRET:
        print(f"Trying Alpaca ({ALPACA_FEED})...")
        alpaca = fetch_alpaca_all(list(TICKERS))

    if alpaca:
        # One request for everything; no per-minute pacing needed.
        source = f"Alpaca {ALPACA_FEED}"
        print(f"Source: {source} — {len(alpaca)} symbol(s)\n")
        for label in TICKERS:
            summary = summarise(label, alpaca.get(label, []))
            (stats if summary else missing).append(summary or label)
    else:
        source = "Twelve Data" if TWELVEDATA_KEY else "Stooq"
        if ALPACA_KEY_ID:
            print(f"Falling back to {source}.\n")
        else:
            print(f"Source: {source}\n")
        if source == "Twelve Data":
            print("  NOTE: Twelve Data's free tier lags intraday. Observed "
                  "2026-07-30: it reported IREN at 7.6M shares while "
                  "consolidated volume was 46.0M. Treat same-day volume and "
                  "x30d as unreliable from this source.\n")
        for i, (label, stooq_symbol) in enumerate(TICKERS.items()):
            if TWELVEDATA_KEY and i:
                time.sleep(TWELVEDATA_GAP)   # 8 req/min free-tier ceiling
            print(f"  {label}...")
            summary = summarise(label, fetch_series(label, stooq_symbol))
            if summary:
                stats.append(summary)
            else:
                missing.append(label)

    if not stats:
        sys.exit("No data for any ticker; not posting.")

    # Stooq publishes EOD bars with a lag. Report the date actually shown
    # rather than implying the numbers are from today.
    latest = max(s["date"] for s in stats)
    stale = [s["label"] for s in stats if s["date"] != latest]

    partial = session_in_progress(latest)
    if partial:
        header = (f"INTRADAY {latest:%a %d %b}\n"
                  f"session open — figures partial")
    else:
        header = f"Close {latest:%a %d %b}"
    if missing:
        header += f"\nno data: {', '.join(missing)}"
    if stale:
        header += f"\nlagging: {', '.join(stale)}"

    header += f"\nvia {source}"
    text = header + "\n\n" + build_table(stats, partial)

    hot = flagged(stats, partial)
    if hot:
        text += "\n\n* unusual volume"
        for s in hot:
            text += f"\n  {s['label']:<5}{s['vol_x']:>5.1f}x {human_vol(s['vol'])}"
    elif not partial:
        text += "\n\nNo unusual volume."
    text += "\n\nVol = x30d avg\n52w = % of range"
    print(f"\n{text}\n")

    if CHART_MODE == "intraday" and alpaca:
        bars = fetch_intraday([s["label"] for s in stats])
        for s in stats:
            got = bars.get(s["label"]) or []
            if len(got) >= 3:          # too few points to be a meaningful line
                s["intraday"] = got
        have = sum(1 for s in stats if s["intraday"])
        print(f"Intraday chart data: {have}/{len(stats)} ticker(s)")

    png = build_chart(stats)
    with open(CHART_FILE, "wb") as fh:
        fh.write(png)
    print(f"Chart written to {CHART_FILE} ({len(png)/1024:.0f}KB).")

    if DRY_RUN:
        print(f"Dry run complete: {len(stats)} ticker(s) resolved, "
              f"{len(missing)} failed. Download the artifact to see the chart.")
        return

    if post(text, png):
        print(f"Posted recap for {len(stats)} ticker(s).")
    else:
        sys.exit("Post failed.")


if __name__ == "__main__":
    main()
