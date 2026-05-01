"""FX session classifier. Pure stdlib. NO trading decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone


SESSIONS = [
    ("asia", 0, 6),
    ("london-open", 6, 10),
    ("london", 10, 13),
    ("overlap", 13, 16),
    ("ny", 16, 21),
    ("dead", 21, 24),
]


def classify(now_utc: datetime) -> dict:
    h = now_utc.hour
    m = now_utc.minute
    weekday = now_utc.weekday()  # Mon=0, Sun=6
    is_weekend = weekday >= 5

    label = next(name for name, lo, hi in SESSIONS if lo <= h < hi)
    session_start_h = next(lo for name, lo, hi in SESSIONS if name == label)
    minutes_into = (h - session_start_h) * 60 + m
    session_len = next((hi - lo) * 60 for name, lo, hi in SESSIONS if name == label)
    minutes_remaining = session_len - minutes_into

    return {
        "now_utc": now_utc.isoformat().replace("+00:00", "Z"),
        "session": label,
        "minutes_into_session": minutes_into,
        "minutes_remaining_in_session": minutes_remaining,
        "weekday": now_utc.strftime("%A"),
        "is_weekend": is_weekend,
    }


def main() -> None:
    info = classify(datetime.now(timezone.utc))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
