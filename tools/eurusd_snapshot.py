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
import os
import signal
import subprocess
import sys
import tempfile
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
    timeout: int = 7,
    attempts: int = 1,
):
    """Fetch a yfinance history dataframe.

    NOTE: yfinance's own ``timeout`` kwarg is unreliable — a wedged Yahoo
    endpoint can hang while holding the GIL, which defeats in-process
    (thread-based) timeouts. The real safety net is that all of this fetching
    runs inside a worker subprocess that ``main()`` kills on overrun (see
    ``gather_raw`` / the ``--worker`` path). Keep attempts low so a healthy
    endpoint is quick and a dead one fails fast within the worker budget."""
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
        if i + 1 < attempts:
            time.sleep(1)
    return None, last_err or "empty result after retries"


def _keyless_spot(warnings: list[str]):
    """Keyless EUR/USD spot reference. No OHLC — a courtesy price only.

    Used to populate current_price when all OHLC feeds are down, clearly
    flagged so the LLM never mistakes a bare spot for tradeable structure."""
    sources = [
        ("open.er-api.com", "https://open.er-api.com/v6/latest/EUR"),
        ("frankfurter", "https://api.frankfurter.app/latest?from=EUR&to=USD"),
    ]
    for name, url in sources:
        try:
            r = requests.get(url, timeout=8)
            usd = (r.json().get("rates") or {}).get("USD")
            if usd:
                return {"price": round(float(usd), 5), "source": name}
        except Exception as e:  # noqa: BLE001
            warnings.append(f"keyless spot {name} failed: {e!r}")
    return None


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


def gather_raw() -> dict:
    """Do the actual upstream fetching. Runs inside the worker subprocess so a
    GIL-holding hang can be killed by the parent. Returns JSON-safe dict."""
    warnings: list[str] = []
    h1, h1_src = fetch_eurusd_tf("5d", "1h", "60", warnings)
    # Stooq doesn't expose a clean 15m feed; if Stooq is needed we'll use 5m.
    m15, m15_src = fetch_eurusd_tf("2d", "15m", "5", warnings)
    m5, m5_src = fetch_eurusd_tf("1d", "5m", "5", warnings)
    dxy, dxy_src = fetch_dxy(warnings)
    return {
        "h1": h1, "h1_src": h1_src,
        "m15": m15, "m15_src": m15_src,
        "m5": m5, "m5_src": m5_src,
        "dxy": dxy, "dxy_src": dxy_src,
        "warnings": warnings,
    }


def _kill_tree(pid: int) -> None:
    """Kill a process *and its descendants*. A wedged yfinance worker can spawn
    grandchildren/threads; killing only the direct child leaves them holding
    handles. On Windows use taskkill /T (whole tree); elsewhere kill the group."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:  # noqa: BLE001
        pass


def _gather_via_worker(budget_s: int = 30) -> dict:
    """Spawn this script with --worker and hard-kill it if it overruns.

    A subprocess is the only reliable bound: yfinance can hang while holding
    the GIL, which defeats thread/signal timeouts in-process.

    CRITICAL (the bug that wedged ~1650 cycles): do NOT use capture_output /
    PIPE here. On Windows a wedged child (or any grandchild it spawned) keeps
    the stdout pipe's write-end open, so the post-kill ``communicate()`` blocks
    *forever* reading until EOF — the 'hard timeout' never actually returns.
    Instead we redirect the worker's stdout to a real temp FILE (no pipe to
    drain) and bound it with ``proc.wait(timeout)``, which touches no pipes. On
    overrun we kill the whole process tree. The parent therefore ALWAYS returns
    within ~budget_s, degrading every source to 'missing' on failure."""
    out_path = None
    try:
        fd, out_path = tempfile.mkstemp(suffix=".json", prefix="eurusd_snap_")
        os.close(fd)
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with open(out_path, "w", encoding="utf-8") as out_f:
            proc = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--worker"],
                stdout=out_f, stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            try:
                proc.wait(timeout=budget_s)
            except subprocess.TimeoutExpired:
                _kill_tree(proc.pid)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass  # tree already force-killed; don't let reap-wait mask the real reason
                return _empty_raw(
                    f"worker exceeded {budget_s}s hard timeout (upstream wedged) — tree killed"
                )
        with open(out_path, "r", encoding="utf-8") as f:
            data = f.read().strip()
        if proc.returncode == 0 and data:
            try:
                return json.loads(data)
            except json.JSONDecodeError as e:
                return _empty_raw(f"worker output unparseable: {e!r}")
        return _empty_raw(f"worker rc={proc.returncode}; no usable output")
    except Exception as e:  # noqa: BLE001
        return _empty_raw(f"worker spawn/parse failed: {e!r}")
    finally:
        if out_path:
            try:
                os.unlink(out_path)
            except OSError:
                pass


def _empty_raw(reason: str) -> dict:
    return {
        "h1": [], "h1_src": "missing",
        "m15": [], "m15_src": "missing",
        "m5": [], "m5_src": "missing",
        "dxy": {"error": "DXY data unavailable"}, "dxy_src": "missing",
        "warnings": [reason],
    }


def main() -> None:
    raw = _gather_via_worker()
    h1, h1_src = raw["h1"], raw["h1_src"]
    m15, m15_src = raw["m15"], raw["m15_src"]
    m5, m5_src = raw["m5"], raw["m5_src"]
    dxy, dxy_src = raw["dxy"], raw["dxy_src"]
    warnings = list(raw.get("warnings", []))

    # Keyless spot reference — only needed when OHLC is entirely missing.
    spot = None
    if not h1 and not m15 and not m5:
        spot = _keyless_spot(warnings)

    out = {
        "now_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "instrument": "EURUSD",
        "spread_estimate_pips": "~1.0 (placeholder; widens during news / off-session)",
        "data_quality": {
            "eurusd_h1": h1_src,
            "eurusd_m15": m15_src,
            "eurusd_m5": m5_src,
            "dxy": dxy_src,
            "spot_fallback": spot["source"] if spot else None,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "warnings": warnings,
        },
        "current_price": h1[-1]["c"] if h1 else (spot["price"] if spot else None),
        "spot_reference": spot,
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
    if "--worker" in sys.argv:
        # Child process: do the (possibly hanging) upstream fetching and emit
        # raw JSON. The parent kills us if we overrun its hard budget.
        print(json.dumps(gather_raw(), default=str))
    else:
        main()
