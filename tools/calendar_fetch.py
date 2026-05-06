"""Forex calendar fetcher — high-impact USD + EUR events in the next 24h.

Pure data fetch. NO trading decisions. The LLM reads this output and
decides whether the news-blackout rule applies.

Source order (first one that returns data wins):
  1. ForexFactory weekly XML feed (https://nfs.faireconomy.media/ff_calendar_thisweek.xml)
     — public, no auth, far less aggressive about 403'ing than the HTML page.
  2. Investing.com AJAX endpoint (does not 403 the way the HTML page does).

Output schema:
  {
    "now_utc": "...",
    "source": "forexfactory_xml" | "investing_ajax" | "none",
    "warnings": [...],
    "events_next_24h": [
      {
        "currency": "USD",
        "time_utc": "2026-05-06T13:30:00Z",
        "impact": "high",
        "name": "Non-Farm Payrolls",
        "forecast": "200K",
        "previous": "187K"
      },
      ...
    ]
  }

Usage:
    python tools/calendar_fetch.py
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

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


TARGET_CURRENCIES = {"USD", "EUR"}
HIGH_IMPACT_TOKENS = {"high", "red"}
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------- ForexFactory XML feed ----------


def _parse_ff_dt(date_str: str, time_str: str) -> datetime | None:
    """ForexFactory XML uses local-ish formats. Try a few."""
    if not date_str:
        return None
    date_str = date_str.strip()
    time_str = (time_str or "").strip()

    # Times like "All Day" / "Tentative" / empty mean we cannot pin a UTC time.
    if not time_str or not re.match(r"^\d", time_str):
        return None

    # FF XML date is MM-DD-YYYY, time is "h:mmam" / "h:mmpm".
    fmts_date = ["%m-%d-%Y", "%Y-%m-%d"]
    parsed_date = None
    for f in fmts_date:
        try:
            parsed_date = datetime.strptime(date_str, f).date()
            break
        except ValueError:
            continue
    if parsed_date is None:
        return None

    # Normalize time: "8:30am" -> "08:30 AM"
    t = time_str.lower().replace(" ", "")
    m = re.match(r"^(\d{1,2}):(\d{2})(am|pm)$", t)
    if not m:
        return None
    hour = int(m.group(1)) % 12
    if m.group(3) == "pm":
        hour += 12
    minute = int(m.group(2))

    # FF feed times are New York / EST/EDT. Approximate by treating as US/Eastern.
    # We don't have zoneinfo guaranteed across platforms — assume EDT (UTC-4) for May.
    # The LLM reads the raw "time_local" field too as a sanity check.
    naive = datetime.combine(parsed_date, datetime.min.time()).replace(
        hour=hour, minute=minute
    )
    # EDT is UTC-4. Close enough for blackout-window decisions; LLM confirms.
    utc_dt = naive + timedelta(hours=4)
    return utc_dt.replace(tzinfo=timezone.utc)


def fetch_forexfactory(warnings: list[str]) -> list[dict]:
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            warnings.append(f"forexfactory XML returned HTTP {r.status_code}")
            return []
    except Exception as e:  # noqa: BLE001
        warnings.append(f"forexfactory XML fetch error: {e!r}")
        return []

    # The CDN occasionally serves an HTML "Request Denied" page with HTTP 200.
    # Reject anything that doesn't look like the actual XML feed.
    head = r.content[:200].lower()
    if b"weeklyevents" not in head and not head.lstrip().startswith(b"<?xml"):
        warnings.append("forexfactory XML returned non-XML payload (likely rate-limited)")
        return []

    try:
        # Pass bytes so ElementTree honors the windows-1252 XML declaration.
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        warnings.append(f"forexfactory XML parse error: {e!r}")
        return []

    events = []
    for ev in root.iter("event"):
        currency = (ev.findtext("country") or "").strip().upper()
        if currency not in TARGET_CURRENCIES:
            continue
        impact = (ev.findtext("impact") or "").strip().lower()
        if impact not in HIGH_IMPACT_TOKENS:
            continue
        date_str = ev.findtext("date") or ""
        time_str = ev.findtext("time") or ""
        utc_dt = _parse_ff_dt(date_str, time_str)
        events.append(
            {
                "currency": currency,
                "time_utc": utc_dt.isoformat().replace("+00:00", "Z") if utc_dt else None,
                "time_local_raw": f"{date_str} {time_str}".strip(),
                "impact": impact,
                "name": (ev.findtext("title") or "").strip(),
                "forecast": (ev.findtext("forecast") or "").strip(),
                "previous": (ev.findtext("previous") or "").strip(),
            }
        )
    return events


# ---------- Investing.com fallback ----------


def fetch_investing(warnings: list[str]) -> list[dict]:
    """Investing.com economic calendar AJAX endpoint."""
    url = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
    headers = {
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.investing.com",
        "Referer": "https://www.investing.com/economic-calendar/",
    }
    # currentTab=today | tomorrow | thisWeek
    body = (
        "country%5B%5D=5&country%5B%5D=72&"  # 5=USA, 72=Eurozone
        "importance%5B%5D=3&"  # 3 = high impact
        "timeZone=55&timeFilter=timeRemain&currentTab=thisWeek&submitFilters=1&limit_from=0"
    )
    try:
        r = requests.post(url, data=body, headers=headers, timeout=15)
        if r.status_code != 200:
            warnings.append(f"investing.com returned HTTP {r.status_code}")
            return []
        data = r.json()
    except Exception as e:  # noqa: BLE001
        warnings.append(f"investing.com fetch/parse error: {e!r}")
        return []

    html = (data or {}).get("data", "") if isinstance(data, dict) else ""
    if not html:
        warnings.append("investing.com response missing 'data'")
        return []

    # Extract rows from the HTML payload. Rough but effective.
    events = []
    row_re = re.compile(
        r"data-event-datetime=\"([^\"]+)\".*?"
        r"<td[^>]*flagCur[^>]*>.*?<span[^>]*title=\"([^\"]+)\".*?"
        r"data-img_key=\"bull(\d+)\".*?"
        r"<a[^>]*>([^<]+)</a>",
        re.DOTALL,
    )
    for m in row_re.finditer(html):
        ts_str, cur_full, impact_n, name = m.groups()
        currency = "USD" if "United States" in cur_full else ("EUR" if "Euro" in cur_full else "")
        if currency not in TARGET_CURRENCIES:
            continue
        try:
            # data-event-datetime is "YYYY/MM/DD HH:MM:SS" in the requested timeZone.
            # We requested timeZone=55 which is GMT (UTC).
            ts = datetime.strptime(ts_str, "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = None
        events.append(
            {
                "currency": currency,
                "time_utc": ts.isoformat().replace("+00:00", "Z") if ts else None,
                "time_local_raw": ts_str,
                "impact": "high" if impact_n == "3" else f"impact_{impact_n}",
                "name": name.strip(),
                "forecast": "",
                "previous": "",
            }
        )
    return events


# ---------- Main ----------


def filter_next_24h(events: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=24)
    out = []
    for ev in events:
        ts_str = ev.get("time_utc")
        if not ts_str:
            # Keep undated high-impact events flagged — LLM decides what to do.
            out.append(ev)
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            out.append(ev)
            continue
        if now - timedelta(minutes=30) <= ts <= horizon:
            out.append(ev)
    out.sort(key=lambda e: e.get("time_utc") or "9999")
    return out


def main() -> None:
    warnings: list[str] = []
    source = "none"

    events = fetch_forexfactory(warnings)
    if events:
        source = "forexfactory_xml"
    else:
        events = fetch_investing(warnings)
        if events:
            source = "investing_ajax"

    out = {
        "now_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "warnings": warnings,
        "events_next_24h": filter_next_24h(events),
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
