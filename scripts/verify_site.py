#!/usr/bin/env python3
"""Validate both index snapshots and confirm a Pages deployment matches them."""

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

from update_qqq import latest_completed_market_date, parse_date


def validate_priority(payload):
    by_symbol = {item["symbol"]: item for item in payload["symbols"]}
    for symbol in ("QQQ", "SPY"):
        latest = by_symbol[symbol]["latest"]
        day = parse_date(latest["date"])
        expected = latest_completed_market_date()
        if not expected - timedelta(days=4) <= day <= expected:
            raise ValueError(f"{symbol}: stale or unfinished trading session {day}; expected near {expected}")
        for field in ("close", "fixed_amount_dca_cost", "moving_avg_180"):
            if not math.isfinite(latest[field]) or latest[field] <= 0:
                raise ValueError(f"{symbol}: invalid {field}")
        if payload["series"][symbol][-1][0] != latest["date"]:
            raise ValueError(f"{symbol}: summary and chart dates differ")
    if by_symbol["QQQ"]["latest"]["date"] != by_symbol["SPY"]["latest"]["date"]:
        raise ValueError("QQQ and SPY have different trading dates")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Also verify this deployed site matches local data")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "public"
    expected = json.loads((root / "data/market_priority.json").read_text(encoding="utf-8"))
    validate_priority(expected)
    summary = json.loads((root / expected["summaryPath"]).read_text(encoding="utf-8"))
    for symbol in ("QQQ", "SPY"):
        history = json.loads((root / summary["historyPaths"][symbol]).read_text(encoding="utf-8"))
        if history["rows"][0][0] != "2000-01-03":
            raise ValueError(f"{symbol}: missing history from 2000")
        if history["rows"][-1][0] != next(item["latest"]["date"] for item in expected["symbols"] if item["symbol"] == symbol):
            raise ValueError(f"{symbol}: full history and latest snapshot differ")
    if args.url:
        url = urllib.parse.urljoin(args.url.rstrip("/") + "/", "data/market_priority.json")
        url += "?" + urllib.parse.urlencode({"verify": expected["updatedAt"]})
        for attempt in range(5):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "investment-dca-verify/1.0", "Cache-Control": "no-cache"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    actual = json.load(response)
                validate_priority(actual)
                if actual != expected:
                    raise ValueError("Production snapshot does not match this deployment")
                break
            except Exception:
                if attempt == 4:
                    raise
                print(f"Production verification retry {attempt + 1}/4", flush=True)
                time.sleep(10)
    print("Verified QQQ and SPY: current closing data and complete history from 2000.")


if __name__ == "__main__":
    main()
