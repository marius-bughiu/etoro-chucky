"""EUR/USD multi-timeframe snapshot + DXY context.

Pure data presentation. NO trading decisions, no buy/sell signals.
The AI reads this output and reasons about it.

Usage:
    python tools/eurusd_snapshot.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, date


EURUSD = "EURUSD=X"
DXY = "DX-Y.NYB"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Chucky/1.0)"}
TIMEOUT = 15


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def fetch_ohlc(ticker: str, rng: str, interval: str) -> list:
    """Return a list of OHLC dicts for the given ticker/range/interval."""
    url = YAHOO_CHART.format(symbol=ticker, interval=interval, rng=rng)
    try:
        data = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    res_list = data.get("chart", {}).get("result")
    if not res_list:
        return []
    res = res_list[0]
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    out = []
    for t, o, h, l, c in zip(timestamps, opens, highs, lows, closes):
        if None in (o, h, l, c):
            continue
        out.append(
            {
                "t": datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z"),
                "o": round(float(o), 5),
                "h": round(float(h), 5),
                "l": round(float(l), 5),
                "c": round(float(c), 5),
            }
        )
    return out[-120:]


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


def _bar_date(c: dict) -> date:
    return datetime.fromisoformat(c["t"].replace("Z", "+00:00")).date()


def prior_day_levels(h1: list) -> dict:
    """High/low of the prior UTC calendar day, derived from H1 candles."""
    if not h1:
        return {}
    today = datetime.now(timezone.utc).date()
    prior_bars = [c for c in h1 if _bar_date(c) < today]
    if not prior_bars:
        return {}
    last_day = max(_bar_date(c) for c in prior_bars)
    day_bars = [c for c in prior_bars if _bar_date(c) == last_day]
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
    today_bars = [c for c in h1 if _bar_date(c) == today]
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
    url = YAHOO_CHART.format(symbol=DXY, interval="1d", rng="10d")
    try:
        data = _http_get_json(url)
    except Exception as e:
        return {"error": f"DXY fetch failed: {e}"}
    res_list = data.get("chart", {}).get("result")
    if not res_list:
        return {"error": "no DXY data"}
    closes = (res_list[0].get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    closes = [c for c in closes if c is not None]
    if len(closes) < 2:
        return {"error": "no DXY data"}
    last = float(closes[-1])
    prev = float(closes[-2])
    five = float(closes[-6]) if len(closes) >= 6 else float(closes[0])
    return {
        "last": round(last, 3),
        "change_1d_pct": round((last - prev) / prev * 100, 3),
        "change_5d_pct": round((last - five) / five * 100, 3),
    }


def main() -> None:
    h1 = fetch_ohlc(EURUSD, rng="5d", interval="1h")
    m15 = fetch_ohlc(EURUSD, rng="2d", interval="15m")
    m5 = fetch_ohlc(EURUSD, rng="1d", interval="5m")

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
