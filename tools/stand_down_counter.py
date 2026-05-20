"""Consecutive stand-down streak counter. Pure stdlib. NO trading decisions.

Scans logs/cycle-*.md newest-first and counts cycles that did NOT execute an
OPEN or CLOSE order. Surfaces an optional advisory nudge string when the
streak crosses 50 / 100 — the nudge is informational text the LLM may read,
never a directive, and never mentions a direction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ORDER_LINE = re.compile(r"^- (\*\*)?(OPEN|CLOSE)\b", re.MULTILINE)

NUDGE_100 = (
    "100+ consecutive stand-downs. Consider whether your setup-grade threshold has "
    "drifted from 'wait for A+' to 'wait for A++'. Setup #3 Variant B exists for "
    "exactly this market state — re-read strategy/chucky.md and check whether it "
    "applies before standing down again."
)
NUDGE_50 = (
    "50+ consecutive stand-downs. Normal in dead tape, but worth a sanity check: "
    "am I rejecting B+ setups out of habit, or is the tape really this dead?"
)


def count(logs_dir: Path) -> dict:
    cycle_files = sorted(logs_dir.glob("cycle-*.md"), reverse=True)

    streak = 0
    last_trade: str | None = None

    for log in cycle_files:
        try:
            content = log.read_text(encoding="utf-8")
        except OSError:
            continue
        if ORDER_LINE.search(content):
            last_trade = log.name
            break
        streak += 1

    if streak >= 100:
        nudge = NUDGE_100
    elif streak >= 50:
        nudge = NUDGE_50
    else:
        nudge = None

    return {
        "consecutive_stand_downs": streak,
        "last_trade_cycle": last_trade,
        "nudge": nudge,
    }


def main() -> None:
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    print(json.dumps(count(logs_dir), indent=2))


if __name__ == "__main__":
    main()
