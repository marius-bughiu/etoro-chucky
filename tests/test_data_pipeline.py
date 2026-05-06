"""Smoke tests for the data pipeline (snapshot + calendar).

These hit live network, so they're slow and not for CI hot paths — run
them on demand after changing tools/eurusd_snapshot.py or
tools/calendar_fetch.py.

    pytest tests/test_data_pipeline.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "tools" / "eurusd_snapshot.py"
CALENDAR = REPO_ROOT / "tools" / "calendar_fetch.py"


def _run(script: Path, timeout: int = 90) -> dict:
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{script.name} exited {result.returncode}\nSTDERR:\n{result.stderr}"
    )
    return json.loads(result.stdout)


def test_snapshot_returns_eurusd():
    data = _run(SNAPSHOT)
    assert "data_quality" in data, "snapshot must include data_quality block"
    assert data["data_quality"]["eurusd_h1"] in {"yfinance", "stooq"}, (
        f"EUR/USD H1 source unexpected: {data['data_quality']}"
    )
    price = data.get("current_price")
    assert isinstance(price, (int, float)), f"current_price not numeric: {price}"
    assert 0.5 <= price <= 2.0, f"EUR/USD price implausible: {price}"


def test_snapshot_returns_dxy():
    data = _run(SNAPSHOT)
    assert data["data_quality"]["dxy"] in {"yfinance", "stooq"}, (
        f"DXY source unexpected: {data['data_quality']}"
    )
    dxy = data.get("dxy", {})
    last = dxy.get("last")
    assert isinstance(last, (int, float)), f"DXY last not numeric: {dxy}"
    assert 80 <= last <= 120, f"DXY level implausible: {last}"


def test_calendar_returns_events():
    data = _run(CALENDAR)
    assert data["source"] in {"forexfactory_xml", "investing_ajax", "none"}, (
        f"unexpected calendar source: {data['source']}"
    )
    events = data.get("events_next_24h")
    assert isinstance(events, list), f"events_next_24h must be a list, got {type(events)}"
    for ev in events:
        # Either a parseable UTC time or explicitly None for "all day" / "tentative".
        assert "currency" in ev and ev["currency"] in {"USD", "EUR"}, ev
        assert "impact" in ev, ev
        assert "name" in ev, ev


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
