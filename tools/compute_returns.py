"""Compute realized P&L over rolling windows from transactions.jsonl.

Reads the JSONL trade log, joins open/close on trade_id, and emits a JSON object
with realized P&L (dollars + %) for the last 24h, 7d, 30d, 12m, and all-time.

Pure math. NO trading decisions, NO recommendations.

Usage:
    python tools/compute_returns.py                 # reads ./transactions.jsonl
    python tools/compute_returns.py path/to.jsonl   # explicit path
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


WINDOWS = [
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
    ("30d", timedelta(days=30)),
    ("12m", timedelta(days=365)),
    ("all", None),
]


def load_trades(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"warn: skipping malformed line: {e}", file=sys.stderr)
    return rows


def parse_iso_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def cost_basis(tr: dict) -> float:
    """Capital deployed in the trade — used as the % denominator."""
    size = float(tr.get("size_usd") or 0)
    return size if size > 0 else 1.0


def aggregate(closed: list[dict], cutoff: datetime | None) -> dict:
    if cutoff is None:
        in_window = closed
    else:
        in_window = [t for t in closed if parse_iso_utc(t["closed_at"]) >= cutoff]
    if not in_window:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "pnl_usd": 0.0,
            "pnl_pct_of_capital_deployed": 0.0,
            "fees_usd": 0.0,
        }
    pnls = [float(t.get("realized_pnl_usd") or 0) for t in in_window]
    fees = [
        float(t.get("open_fee_usd") or 0)
        + float(t.get("close_fee_usd") or 0)
        + float(t.get("swap_fee_usd") or 0)
        for t in in_window
    ]
    capital = sum(cost_basis(t) for t in in_window)
    total_pnl = sum(pnls)
    return {
        "trades": len(in_window),
        "wins": sum(1 for p in pnls if p > 0),
        "losses": sum(1 for p in pnls if p < 0),
        "pnl_usd": round(total_pnl, 2),
        "pnl_pct_of_capital_deployed": round(total_pnl / capital * 100, 3) if capital else 0.0,
        "fees_usd": round(sum(fees), 2),
    }


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("transactions.jsonl")
    trades = load_trades(path)
    closed = [t for t in trades if (t.get("status") == "closed" and t.get("closed_at"))]
    open_trades = [t for t in trades if t.get("status") == "open"]
    now = datetime.now(timezone.utc)

    out = {
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "source_file": str(path),
        "open_positions": len(open_trades),
        "closed_trades": len(closed),
        "windows": {},
    }
    for label, delta in WINDOWS:
        cutoff = now - delta if delta else None
        out["windows"][label] = aggregate(closed, cutoff)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
