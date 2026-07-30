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

CHART_DAYS = 60        # trading days shown per sparkline
VOL_AVG_DAYS = 30      # baseline for the volume comparison
GRID_COLS = 3

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
# Dry run: build everything, print the table, save the chart, post nothing.
# Lets you validate ticker symbols before creating the webhook.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
CHART_FILE = "recap.png"
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


def build_table(stats):
    """Monospace table, sorted by move size."""
    stats = sorted(stats, key=lambda s: s["pct"], reverse=True)
    lines = [f"{'':6}{'Close':>9}{'Chg':>9}{'Vol':>8}{'x30d':>7}{'52w':>7}"]
    lines.append("-" * 46)
    for s in stats:
        span = s["hi"] - s["lo"]
        pos = ((s["close"] - s["lo"]) / span * 100) if span else 0
        lines.append(
            f"{s['label']:<6}{s['close']:>9.2f}{s['pct']:>8.1f}%"
            f"{human_vol(s['vol']):>8}{s['vol_x']:>6.1f}x{pos:>6.0f}%"
        )
    return "\n".join(lines)


def build_chart(stats):
    """Grid of closing-price sparklines. Returns PNG bytes."""
    n = len(stats)
    rows = (n + GRID_COLS - 1) // GRID_COLS
    fig, axes = plt.subplots(rows, GRID_COLS,
                             figsize=(GRID_COLS * 3.2, rows * 2.0))
    fig.patch.set_facecolor("#0D1117")
    axes = axes.flatten() if n > 1 else [axes]

    for ax, s in zip(axes, stats):
        series = s["series"]
        colour = UP if series[-1] >= series[0] else DOWN
        ax.plot(series, color=colour, linewidth=1.4)
        ax.fill_between(range(len(series)), series, min(series),
                        color=colour, alpha=0.12)
        ax.set_title(f"{s['label']}  {s['pct']:+.1f}%",
                     color="#E6EDF3", fontsize=10, pad=4)
        ax.set_facecolor("#0D1117")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)

    for ax in axes[n:]:
        ax.set_visible(False)

    fig.suptitle(f"{CHART_DAYS}-day close", color=FLAT, fontsize=9, y=0.99)
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

    if TWELVEDATA_KEY:
        print("Source: Twelve Data\n")
    else:
        print("Source: Stooq (no TWELVEDATA_KEY set — expect quota errors "
              "on shared cloud IPs)\n")

    stats, missing = [], []
    for i, (label, stooq_symbol) in enumerate(TICKERS.items()):
        if TWELVEDATA_KEY and i:
            time.sleep(TWELVEDATA_GAP)      # 8 req/min free-tier ceiling
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
        header = (f"INTRADAY {latest:%a %d %b %Y} — session still open, "
                  f"volumes and changes are incomplete")
    else:
        header = f"Close {latest:%a %d %b %Y}"
    if missing:
        header += f"   |  no data: {', '.join(missing)}"
    if stale:
        header += f"   |  lagging: {', '.join(stale)}"

    text = header + "\n\n" + build_table(stats)
    print(f"\n{text}\n")

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
