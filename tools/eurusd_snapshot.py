"""EUR/USD multi-timeframe snapshot + DXY context.

Pure data presentation. NO trading decisions, no buy/sell signals.
The AI reads this output and reasons about it.

Hardened against the wedge issues seen in cycle logs:
  * Every yfinance call has a timeout + retry-with-backoff.
  * DXY ticker tries multiple Yahoo aliases (DX-Y.NYB, ^DXY) and falls
    back to Stooq (free, no key) when Yahoo throws 404.
  * EUR/USD also has a Stooq fallback for the same reason.
  * Every output carries a top-level `data_quality` block telling the
    LLM which source filled which timeframe and what fell back.

Usage:
    python tools/eurusd_snapshot.py
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
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

try:
    import requests
except ImportError:
    print(
        json.dumps(
            {
                "error": "requests not installed",
                "fix": "pip install -r tools/requirements.txt",
            }
        )
    )
    sys.exit(1)


EURUSD_YF = "EURUSD=X"
DXY_YF_CANDIDATES = ["DX-Y.NYB", "^DXY", "DX=F"]


# ---------- yfinance helpers ----------


def _yf_history(
    ticker: str,
    period: str,
    interval: str,
    timeout: int = 15,
    attempts: int = 3,
):
    """Fetch a yfinance history dataframe with timeout + exponential backoff."""
    last_err = None
    for i in range(attempts):
        try:
            df = yf.Ticker(ticker).history(
                period=period,
                interval=interval,
                auto_adjust=False,
                timeout=timeout,
            )
            if df is not None and not df.empty:
                return df, None
        except Exception as e:  # noqa: BLE001
            last_err = repr(e)
        time.sleep(2**i)
    return None, last_err or "empty result after retries"


def _df_to_candles(df) -> list[dict]:
    if df is None or df.empty:
        return []
    df = df.tail(120)
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


# ---------- Stooq fallback ----------


def _stooq_intraday(symbol: str, interval_code: str) -> list[dict]:
    """Fetch OHLC CSV from Stooq. Free, no key. Returns candle dicts."""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i={interval_code}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200 or not r.text or "Date" not in r.text[:20]:
            return []
    except Exception:  # noqa: BLE001
        return []

    candles: list[dict] = []
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        try:
            dt_str = row.get("Date", "")
            if "Time" in row and row.get("Time"):
                dt_str = f"{dt_str} {row['Time']}"
            try:
                ts = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    ts = datetime.strptime(dt_str, "%Y-%m-%d")
                except ValueError:
                    continue
            ts = ts.replace(tzinfo=timezone.utc)
            candles.append(
                {
                    "t": ts.isoformat(),
                    "o": round(float(row["Open"]), 5),
                    "h": round(float(row["High"]), 5),
                    "l": round(float(row["Low"]), 5),
                    "c": round(float(row["Close"]), 5),
                }
            )
        except (KeyError, ValueError, TypeError):
            continue
    return candles[-120:]


# ---------- Math (unchanged from before) ----------


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


# ---------- Fetch orchestration ----------


def fetch_eurusd_tf(
    period: str,
    yf_interval: str,
    stooq_interval: str,
    warnings: list[str],
) -> tuple[list[dict], str]:
    """Try yfinance with retry; fall back to Stooq. Returns (candles, source)."""
    df, err = _yf_history(EURUSD_YF, period=period, interval=yf_interval)
    if df is not None:
        candles = _df_to_candles(df)
        if candles:
            return candles, "yfinance"
    warnings.append(f"yfinance EURUSD {yf_interval} failed ({err}); trying Stooq")
    candles = _stooq_intraday("eurusd", stooq_interval)
    if candles:
        return candles, "stooq"
    warnings.append(f"Stooq EURUSD {stooq_interval} also empty")
    return [], "missing"


def fetch_dxy(warnings: list[str]) -> tuple[dict, str]:
    """Try Yahoo aliases, then Stooq. Returns (dxy_dict, source)."""
    for ticker in DXY_YF_CANDIDATES:
        df, err = _yf_history(ticker, period="10d", interval="1d", attempts=2)
        if df is not None and len(df) >= 2:
            try:
                last = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                five = float(df["Close"].iloc[-6]) if len(df) >= 6 else float(df["Close"].iloc[0])
                return (
                    {
                        "last": round(last, 3),
                        "change_1d_pct": round((last - prev) / prev * 100, 3),
                        "change_5d_pct": round((last - five) / five * 100, 3),
                        "ticker": ticker,
                    },
                    "yfinance",
                )
            except Exception as e:  # noqa: BLE001
                warnings.append(f"yfinance DXY {ticker} parse fail: {e!r}")
        else:
            warnings.append(f"yfinance DXY {ticker} unavailable ({err})")

    # Stooq fallback. dx.f is the DXY symbol on Stooq.
    candles = _stooq_intraday("dx.f", "d")
    if len(candles) >= 2:
        last = candles[-1]["c"]
        prev = candles[-2]["c"]
        five = candles[-6]["c"] if len(candles) >= 6 else candles[0]["c"]
        return (
            {
                "last": round(last, 3),
                "change_1d_pct": round((last - prev) / prev * 100, 3),
                "change_5d_pct": round((last - five) / five * 100, 3),
                "ticker": "dx.f@stooq",
            },
            "stooq",
        )
    warnings.append("Stooq DXY fallback also empty")
    return ({"error": "DXY data unavailable from all sources"}, "missing")


# ---------- Main ----------


def main() -> None:
    warnings: list[str] = []

    h1, h1_src = fetch_eurusd_tf("5d", "1h", "60", warnings)
    # Stooq doesn't expose a clean 15m feed; if Stooq is needed we'll use 5m.
    m15, m15_src = fetch_eurusd_tf("2d", "15m", "5", warnings)
    m5, m5_src = fetch_eurusd_tf("1d", "5m", "5", warnings)
    dxy, dxy_src = fetch_dxy(warnings)

    out = {
        "now_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "instrument": "EURUSD",
        "spread_estimate_pips": "~1.0 (placeholder; widens during news / off-session)",
        "data_quality": {
            "eurusd_h1": h1_src,
            "eurusd_m15": m15_src,
            "eurusd_m5": m5_src,
            "dxy": dxy_src,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "warnings": warnings,
        },
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
        "dxy": dxy,
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
