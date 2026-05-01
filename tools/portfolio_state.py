"""eToro agent-portfolio state snapshot.

Wraps GET /api/v1/trading/info/real/pnl. Computes Available Cash, Total Invested,
Equity, and per-position dollar size + unrealized PnL.

NO trading decisions, no recommendations, no "you should close X" output.

Reads ETORO_USER_TOKEN from environment. Errors cleanly if absent.

Usage:
    python tools/portfolio_state.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


PUBLIC_API_KEY = "sdgdskldFPLGfjHn1421dgnlxdGTbngdflg6290bRjslfihsjhSDsdgGHH25hjf"
BASE = "https://public-api.etoro.com/api/v1"


def load_dotenv() -> None:
    """Minimal .env loader. No external dep."""
    repo_root = Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def fetch_pnl(token: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/trading/info/real/pnl",
        headers={
            "x-request-id": str(uuid.uuid4()),
            "x-api-key": PUBLIC_API_KEY,
            "x-user-key": token,
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def compute_view(pnl: dict) -> dict:
    """Compute Available Cash / Total Invested / Equity per SKILL.md."""
    cp = pnl.get("clientPortfolio", {}) or {}
    credit = float(cp.get("credit", 0))

    positions = cp.get("positions", []) or []
    mirrors = cp.get("mirrors", []) or []
    orders = cp.get("orders", []) or []
    orders_for_open = cp.get("ordersForOpen", []) or []

    manual_open_orders = [o for o in orders_for_open if o.get("mirrorID", 0) == 0]
    sum_manual_open_orders = sum(float(o.get("amount", 0)) for o in manual_open_orders)
    sum_close_orders = sum(float(o.get("amount", 0)) for o in orders)

    available_cash = credit - sum_manual_open_orders - sum_close_orders

    sum_positions = sum(float(p.get("amount", 0)) for p in positions)
    sum_mirror_positions = sum(
        float(p.get("amount", 0))
        for m in mirrors
        for p in (m.get("positions", []) or [])
    )
    sum_mirror_residual = sum(
        float(m.get("availableAmount", 0)) - float(m.get("closedPositionsNetProfit", 0))
        for m in mirrors
    )
    sum_open_costs = sum(
        float(o.get("totalExternalCosts", 0)) for o in manual_open_orders
    )

    total_invested = (
        sum_positions
        + sum_mirror_positions
        + sum_mirror_residual
        + sum_manual_open_orders
        + sum_close_orders
        + sum_open_costs
    )

    sum_position_pnl = sum(
        float((p.get("unrealizedPnL") or {}).get("pnL", 0)) for p in positions
    )
    sum_mirror_pnl = sum(
        float((p.get("unrealizedPnL") or {}).get("pnL", 0))
        for m in mirrors
        for p in (m.get("positions", []) or [])
    )
    sum_mirror_realized = sum(
        float(m.get("closedPositionsNetProfit", 0)) for m in mirrors
    )

    unrealized_pnl = sum_position_pnl + sum_mirror_pnl + sum_mirror_realized
    equity = available_cash + total_invested + unrealized_pnl

    def position_view(p: dict) -> dict:
        amount = float(p.get("amount", 0))
        upnl = float((p.get("unrealizedPnL") or {}).get("pnL", 0))
        return {
            "instrument_id": p.get("instrumentID"),
            "position_id": p.get("positionID"),
            "side": "long" if p.get("isBuy") else "short",
            "leverage": p.get("leverage"),
            "amount_usd": round(amount, 2),
            "amount_pct_equity": round(amount / equity * 100, 2) if equity else None,
            "unrealized_pnl_usd": round(upnl, 2),
            "unrealized_pnl_pct_equity": round(upnl / equity * 100, 3) if equity else None,
            "open_rate": p.get("openRate"),
            "stop_loss_rate": p.get("stopLossRate"),
            "take_profit_rate": p.get("takeProfitRate"),
            "is_tsl_enabled": p.get("isTslEnabled"),
        }

    return {
        "credit_raw_usd": round(credit, 2),
        "available_cash_usd": round(available_cash, 2),
        "total_invested_usd": round(total_invested, 2),
        "unrealized_pnl_usd": round(unrealized_pnl, 2),
        "equity_usd": round(equity, 2),
        "open_position_count": len(positions),
        "pending_open_orders_count": len(manual_open_orders),
        "pending_close_orders_count": len(orders),
        "positions": [position_view(p) for p in positions],
        "pending_open_orders": [
            {
                "instrument_id": o.get("instrumentID"),
                "side": "long" if o.get("isBuy") else "short",
                "amount_usd": round(float(o.get("amount", 0)), 2),
                "leverage": o.get("leverage"),
            }
            for o in manual_open_orders
        ],
    }


def main() -> None:
    load_dotenv()
    token = os.environ.get("ETORO_USER_TOKEN", "").strip()
    if not token:
        print(
            json.dumps(
                {
                    "error": "ETORO_USER_TOKEN not set",
                    "fix": "Copy .env.example to .env and paste your eToro agent-portfolio user token.",
                }
            )
        )
        sys.exit(1)

    try:
        pnl = fetch_pnl(token)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        print(json.dumps({"error": f"HTTP {e.code}", "body": body}))
        sys.exit(2)
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"Request failed: {e.reason}"}))
        sys.exit(2)

    view = compute_view(pnl)
    print(json.dumps(view, indent=2))


if __name__ == "__main__":
    main()
