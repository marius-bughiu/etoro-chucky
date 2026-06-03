"""Thin executor: close ONE position by positionID. Chucky decides; this only executes.

Usage:
  python tools/close_position.py --position-id 3465069498 --instrument-id 1
  python tools/close_position.py --position-id 3465069498 --instrument-id 1 --units 1000  # partial
"""
import argparse
import json
import os
import sys
import uuid
import urllib.request
import urllib.error
from pathlib import Path

API_KEY = "sdgdskldFPLGfjHn1421dgnlxdGTbngdflg6290bRjslfihsjhSDsdgGHH25hjf"
BASE = "https://public-api.etoro.com/api/v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def load_token():
    tok = os.environ.get("ETORO_USER_TOKEN")
    if tok:
        return tok.strip()
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line.startswith("ETORO_USER_TOKEN") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("ERROR: ETORO_USER_TOKEN not found", file=sys.stderr)
    sys.exit(2)


def req(method, url, token, body=None):
    headers = {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": API_KEY,
        "x-user-key": token,
        "User-Agent": UA,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--position-id", required=True)
    ap.add_argument("--instrument-id", required=True, type=int)
    ap.add_argument("--units", type=float, default=None,
                    help="UnitsToDeduct for partial close; omit for full close")
    args = ap.parse_args()

    token = load_token()
    body = {
        "InstrumentId": args.instrument_id,
        "UnitsToDeduct": args.units,  # None -> full close
    }
    url = f"{BASE}/trading/execution/market-close-orders/positions/{args.position_id}"
    print("CLOSE body:", json.dumps(body))
    s, j = req("POST", url, token, body)
    print(f"HTTP {s}")
    print(json.dumps(j, indent=2))
    if s not in (200, 201):
        sys.exit(1)


if __name__ == "__main__":
    main()
