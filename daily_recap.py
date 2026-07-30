#!/usr/bin/env python3
"""
Daily post-close recap -> Discord.

Pulls end-of-day OHLCV from Stooq (no API key required), builds a performance
table and a chart grid, and posts both to a webhook.

Stooq is used instead of Yahoo/yfinance because Yahoo deprecated its API and
actively discourages scraping; anything built on it breaks unpredictably.
"""

import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

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
STOOQ_CSV = "https://stooq.com/q/d/l/?s={symbol}&i=d"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

UP, DOWN, FLAT = "#3FB950", "#F85149", "#8B949E"


def fetch_series(symbol):
    """Return [(date, close, volume), ...] oldest first, or [] on failure."""
    try:
        r = requests.get(STOOQ_CSV.format(symbol=symbol),
                         headers=HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"    fetch failed: {type(e).__name__}")
        return []
    if r.status_code != 200 or not r.text.startswith("Date"):
        # Stooq returns a plain-text error body rather than a 404 for unknown
        # symbols, so check the header row rather than trusting the status.
        print(f"    no data (HTTP {r.status_code})")
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
    if not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL_MARKET is not set.")

    stats, missing = [], []
    for label, symbol in TICKERS.items():
        print(f"  {label} ({symbol})...")
        summary = summarise(label, fetch_series(symbol))
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

    header = f"Close {latest:%a %d %b %Y}"
    if missing:
        header += f"   |  no data: {', '.join(missing)}"
    if stale:
        header += f"   |  lagging: {', '.join(stale)}"

    text = header + "\n\n" + build_table(stats)
    print(f"\n{text}\n")

    if post(text, build_chart(stats)):
        print(f"Posted recap for {len(stats)} ticker(s).")
    else:
        sys.exit("Post failed.")


if __name__ == "__main__":
    main()
