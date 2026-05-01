"""EUR/USD multi-timeframe snapshot + DXY context.

Pure data presentation. NO trading decisions, no buy/sell signals.
The AI reads this output and reasons about it.

Usage:
    python tools/eurusd_snapshot.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    print(
        json.dumps(
            {
                "error": "yfinance not installed",
                "fix": "pip install -r tools/requirements.txt",
            }
        )
    )
    sys.exit(1)


EURUSD = "EURUSD=X"
DXY = "DX=F"


def fetch_ohlc(ticker: str, period: str, interval: str):
    """Return a list of OHLC dicts for the given ticker/period/interval."""
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if df.empty:
        return []
    df = df.tail(120)  # cap rows
    out = []
    for ts, row in df.iterrows():
        out.append(
            {
                "t": ts.isoformat(),
                "o": round(float(row["Open"]), 5),
                "h": round(float(row["High"]), 5),
                "l": round(float(row["Low"]), 5),
                "c": round(float(row["Close"]), 5),
            }
        )
    return out


def atr(candles: list, period: int = 14) -> float | None:
    """Average True Range. Pure math, no signal interpretation."""
    if len(candles) < period + 1:
        return None
    trs = []
    prev_close = candles[0]["c"]
    for c in candles[1:]:
        tr = max(
            c["h"] - c["l"],
            abs(c["h"] - prev_close),
            abs(c["l"] - prev_close),
        )
        trs.append(tr)
        prev_close = c["c"]
    last = trs[-period:]
    return round(sum(last) / len(last), 5)


def summarize_tf(candles: list) -> dict:
    if not candles:
        return {"bars": 0}
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    return {
        "bars": len(candles),
        "first_t": candles[0]["t"],
        "last_t": candles[-1]["t"],
        "last_close": candles[-1]["c"],
        "period_high": round(max(highs), 5),
        "period_low": round(min(lows), 5),
        "period_range_pips": round((max(highs) - min(lows)) * 10000, 1),
        "atr14": atr(candles, 14),
    }


def prior_day_levels(h1: list) -> dict:
    """High/low of the prior UTC calendar day, derived from H1 candles."""
    if not h1:
        return {}
    today = datetime.now(timezone.utc).date()
    prior_bars = [c for c in h1 if datetime.fromisoformat(c["t"]).date() < today]
    if not prior_bars:
        return {}
    last_day = max(datetime.fromisoformat(c["t"]).date() for c in prior_bars)
    day_bars = [c for c in prior_bars if datetime.fromisoformat(c["t"]).date() == last_day]
    if not day_bars:
        return {}
    return {
        "date": last_day.isoformat(),
        "high": round(max(c["h"] for c in day_bars), 5),
        "low": round(min(c["l"] for c in day_bars), 5),
        "open": day_bars[0]["o"],
        "close": day_bars[-1]["c"],
    }


def today_range(h1: list) -> dict:
    if not h1:
        return {}
    today = datetime.now(timezone.utc).date()
    today_bars = [c for c in h1 if datetime.fromisoformat(c["t"]).date() == today]
    if not today_bars:
        return {}
    return {
        "high": round(max(c["h"] for c in today_bars), 5),
        "low": round(min(c["l"] for c in today_bars), 5),
        "open": today_bars[0]["o"],
        "bars": len(today_bars),
    }


def dxy_context() -> dict:
    """DXY (US dollar index) level + 1d/5d change."""
    try:
        df = yf.Ticker(DXY).history(period="10d", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 2:
            return {"error": "no DXY data"}
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        five = float(df["Close"].iloc[-6]) if len(df) >= 6 else float(df["Close"].iloc[0])
        return {
            "last": round(last, 3),
            "change_1d_pct": round((last - prev) / prev * 100, 3),
            "change_5d_pct": round((last - five) / five * 100, 3),
        }
    except Exception as e:
        return {"error": f"DXY fetch failed: {e}"}


def main() -> None:
    h1 = fetch_ohlc(EURUSD, period="5d", interval="1h")
    m15 = fetch_ohlc(EURUSD, period="2d", interval="15m")
    m5 = fetch_ohlc(EURUSD, period="1d", interval="5m")

    out = {
        "now_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "instrument": "EURUSD",
        "spread_estimate_pips": "~1.0 (placeholder; widens during news / off-session)",
        "current_price": h1[-1]["c"] if h1 else None,
        "today_so_far": today_range(h1),
        "prior_day": prior_day_levels(h1),
        "timeframes": {
            "h1_5d": summarize_tf(h1),
            "m15_2d": summarize_tf(m15),
            "m5_1d": summarize_tf(m5),
        },
        "recent_h1_bars": h1[-12:],
        "recent_m15_bars": m15[-16:],
        "recent_m5_bars": m5[-12:],
        "dxy": dxy_context(),
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
