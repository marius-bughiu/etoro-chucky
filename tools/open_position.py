"""Thin executor: resolve EURUSD instrument id and open ONE position with a stop.
Chucky decides the args; this only executes. No decision logic here.

Usage:
  python tools/open_position.py --side short --amount 2500 --leverage 10 --stop 1.16215 --tp 1.15915
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
    ap.add_argument("--side", required=True, choices=["long", "short"])
    ap.add_argument("--amount", required=True, type=float)
    ap.add_argument("--leverage", required=True, type=int)
    ap.add_argument("--stop", required=True, type=float)
    ap.add_argument("--tp", type=float, default=None)
    args = ap.parse_args()

    token = load_token()

    # Resolve instrument id
    s, j = req("GET", f"{BASE}/market-data/search?internalSymbolFull=EURUSD", token)
    if s != 200:
        print(f"ERROR resolve instrument: HTTP {s} {j}", file=sys.stderr)
        sys.exit(1)
    items = j.get("items", [])
    match = next((it for it in items if it.get("internalSymbolFull") == "EURUSD"), None)
    if not match:
        print(f"ERROR: no EURUSD match in {items}", file=sys.stderr)
        sys.exit(1)
    iid = match.get("internalInstrumentId") or match.get("instrumentId")
    print(f"instrument EURUSD -> {iid} (tradable={match.get('isCurrentlyTradable')})")

    body = {
        "InstrumentID": int(iid),
        "IsBuy": args.side == "long",
        "Leverage": args.leverage,
        "Amount": args.amount,
        "StopLossRate": args.stop,
    }
    if args.tp is not None:
        body["TakeProfitRate"] = args.tp

    print("OPEN body:", json.dumps(body))
    s, j = req("POST", f"{BASE}/trading/execution/market-open-orders/by-amount", token, body)
    print(f"HTTP {s}")
    print(json.dumps(j, indent=2))
    if s not in (200, 201):
        sys.exit(1)


if __name__ == "__main__":
    main()
