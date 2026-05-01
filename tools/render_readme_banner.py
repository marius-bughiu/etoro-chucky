"""Render the README.md performance banner from transactions.jsonl.

Replaces the section between <!-- CHUCKY-BANNER:START --> and
<!-- CHUCKY-BANNER:END --> with a fresh dollars-first table + last 10 trades.

Idempotent. NO trading decisions. Pure formatting.

Usage:
    python tools/render_readme_banner.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
TXLOG = REPO_ROOT / "transactions.jsonl"
START = "<!-- CHUCKY-BANNER:START -->"
END = "<!-- CHUCKY-BANNER:END -->"


def load_trades() -> list[dict]:
    if not TXLOG.exists():
        return []
    rows = []
    for line in TXLOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def fmt_money(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "n/a"
    if signed:
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v):,.2f}"
    return f"${v:,.2f}"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "+" if v >= 0 else "-"
    return f"{sign}{abs(v):.2f}%"


def aggregate(closed: list[dict], cutoff: datetime | None) -> tuple[float, float]:
    """Return (pnl_usd, pnl_pct_of_capital_deployed) for trades closed >= cutoff."""
    if cutoff is None:
        rows = closed
    else:
        rows = [t for t in closed if parse_iso(t.get("closed_at")) and parse_iso(t["closed_at"]) >= cutoff]
    if not rows:
        return 0.0, 0.0
    pnl = sum(float(t.get("realized_pnl_usd") or 0) for t in rows)
    capital = sum(float(t.get("size_usd") or 0) for t in rows) or 1.0
    return pnl, pnl / capital * 100


def build_returns_table(closed: list[dict], now: datetime) -> str:
    from datetime import timedelta

    windows = [
        ("24h", timedelta(hours=24)),
        ("7d", timedelta(days=7)),
        ("30d", timedelta(days=30)),
        ("12m", timedelta(days=365)),
        ("All-time", None),
    ]
    lines = ["| Window | P&L | Return % | Trades |", "|---|---|---|---|"]
    for label, delta in windows:
        cutoff = (now - delta) if delta else None
        if cutoff is None:
            rows = closed
        else:
            rows = [
                t for t in closed
                if parse_iso(t.get("closed_at")) and parse_iso(t["closed_at"]) >= cutoff
            ]
        pnl, pct = aggregate(closed, cutoff)
        n = len(rows)
        if n == 0:
            lines.append(f"| {label} | n/a | n/a | 0 |")
        else:
            lines.append(f"| {label} | {fmt_money(pnl)} | {fmt_pct(pct)} | {n} |")
    return "\n".join(lines)


def build_last_10_table(closed: list[dict]) -> str:
    last = sorted(
        closed,
        key=lambda t: parse_iso(t.get("closed_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:10]
    if not last:
        return "_No closed trades yet._"
    header = "| # | opened (UTC) | side | size | entry | closed (UTC) | exit | fees | P&L $ | P&L % |"
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for i, t in enumerate(last, 1):
        opened = (t.get("opened_at") or "").replace("T", " ").replace("Z", "")
        closed_at = (t.get("closed_at") or "").replace("T", " ").replace("Z", "")
        size = float(t.get("size_usd") or 0)
        entry = t.get("open_price")
        exit_ = t.get("close_price")
        fees = (
            float(t.get("open_fee_usd") or 0)
            + float(t.get("close_fee_usd") or 0)
            + float(t.get("swap_fee_usd") or 0)
        )
        pnl_usd = float(t.get("realized_pnl_usd") or 0)
        pnl_pct = float(t.get("realized_pnl_pct") or 0) if t.get("realized_pnl_pct") is not None else None
        rows.append(
            f"| {i} | {opened} | {t.get('side','?')} | {fmt_money(size, signed=False)} | "
            f"{entry if entry is not None else '—'} | {closed_at} | "
            f"{exit_ if exit_ is not None else '—'} | {fmt_money(fees, signed=False)} | "
            f"{fmt_money(pnl_usd)} | {fmt_pct(pnl_pct)} |"
        )
    return "\n".join(rows)


def render_banner() -> str:
    trades = load_trades()
    closed = [t for t in trades if t.get("status") == "closed" and t.get("closed_at")]
    open_trades = [t for t in trades if t.get("status") == "open"]
    now = datetime.now(timezone.utc)

    cycle_ts = now.isoformat(timespec="minutes").replace("+00:00", "Z")
    open_count = len(open_trades)

    open_summary = ""
    if open_trades:
        bits = []
        for t in open_trades:
            bits.append(f"{t.get('side','?')} {fmt_money(float(t.get('size_usd') or 0), signed=False)} @ {t.get('open_price','?')}")
        open_summary = " — open now: " + ", ".join(bits)

    parts = [
        START,
        f"## Live performance — last cycle {cycle_ts}",
        "",
        f"**Open positions:** {open_count}{open_summary}",
        "",
        build_returns_table(closed, now),
        "",
        "### Last 10 trades",
        build_last_10_table(closed),
        END,
    ]
    return "\n".join(parts)


def patch_readme(banner: str) -> None:
    if not README.exists():
        # Bootstrap: write a minimal README with just the banner. The full
        # README body is normally written by hand above the banner.
        README.write_text(banner + "\n", encoding="utf-8")
        return
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        # Banner markers absent — append at the bottom.
        sep = "" if text.endswith("\n") else "\n"
        README.write_text(text + sep + "\n" + banner + "\n", encoding="utf-8")
        return
    pre = text.split(START)[0]
    post = text.split(END, 1)[1]
    new = pre + banner + post
    README.write_text(new, encoding="utf-8")


def main() -> None:
    banner = render_banner()
    patch_readme(banner)
    print(f"banner refreshed in {README}")


if __name__ == "__main__":
    main()
