#!/usr/bin/env python3
"""Update QQQ price history and 180-trading-day DCA cost data.

The DCA cost uses the fixed-dollar formula:

    cost = N / sum(1 / close_i)

where N is 180 and close_i are the previous 180 trading-day closes before the
calendar date being calculated.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


SYMBOL = "QQQ"
WINDOW_DAYS = 180
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PUBLIC_DATA_DIR = PROJECT_ROOT / "public" / "data"
PRICE_CSV = DATA_DIR / "qqq_prices.csv"
DCA_CSV = DATA_DIR / "qqq_180d_dca.csv"
PUBLIC_DCA_CSV = PUBLIC_DATA_DIR / "qqq_180d_dca.csv"
DCA_JSON = PUBLIC_DATA_DIR / "qqq_180d_dca.json"
DCA_JS = PUBLIC_DATA_DIR / "qqq_180d_dca.js"


@dataclass(frozen=True)
class PriceRow:
    date: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def unix_seconds(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def fetch_yahoo_prices(symbol: str, start: date, end_exclusive: date) -> list[PriceRow]:
    params = {
        "period1": unix_seconds(start),
        "period2": unix_seconds(end_exclusive),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 qqq-dca-site/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_yahoo_chart_payload(payload)


def parse_yahoo_chart_payload(payload: dict[str, object]) -> list[PriceRow]:
    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(f"Yahoo chart error: {error}")

    results = chart.get("result") or []
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adj = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []

    rows: list[PriceRow] = []
    for i, ts in enumerate(timestamps):
        close = safe_float((quote.get("close") or [None])[i])
        open_ = safe_float((quote.get("open") or [None])[i])
        high = safe_float((quote.get("high") or [None])[i])
        low = safe_float((quote.get("low") or [None])[i])
        adj_close = safe_float(adj[i] if i < len(adj) else close)
        if close is None or open_ is None or high is None or low is None:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
        volume_value = (quote.get("volume") or [0])[i]
        rows.append(
            PriceRow(
                date=dt,
                open=open_,
                high=high,
                low=low,
                close=close,
                adj_close=adj_close if adj_close is not None else close,
                volume=int(volume_value or 0),
            )
        )
    return rows


def load_prices(path: Path) -> list[PriceRow]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append(
                PriceRow(
                    date=row["date"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    adj_close=float(row.get("adj_close") or row["close"]),
                    volume=int(float(row.get("volume") or 0)),
                )
            )
        return rows


def write_prices(path: Path, rows: list[PriceRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close", "adj_close", "volume"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "date": row.date,
                    "open": f"{row.open:.6f}",
                    "high": f"{row.high:.6f}",
                    "low": f"{row.low:.6f}",
                    "close": f"{row.close:.6f}",
                    "adj_close": f"{row.adj_close:.6f}",
                    "volume": row.volume,
                }
            )


def merge_prices(*groups: list[PriceRow]) -> list[PriceRow]:
    by_date: dict[str, PriceRow] = {}
    for rows in groups:
        for row in rows:
            by_date[row.date] = row
    return [by_date[key] for key in sorted(by_date)]


def calculate_dca(prices: list[PriceRow], as_of: date | None = None) -> list[dict[str, object]]:
    if len(prices) < WINDOW_DAYS:
        return []

    as_of = as_of or date.today()
    first_target = parse_date(prices[WINDOW_DAYS].date)
    last_target = max(as_of, parse_date(prices[-1].date))
    price_dates = {row.date: row for row in prices}

    rows: list[dict[str, object]] = []
    trade_index = 0
    target = first_target
    one_day = timedelta(days=1)

    while target <= last_target:
        target_key = target.isoformat()
        while trade_index < len(prices) and prices[trade_index].date < target_key:
            trade_index += 1
        window = prices[max(0, trade_index - WINDOW_DAYS) : trade_index]
        if len(window) == WINDOW_DAYS:
            shares = sum(1.0 / row.close for row in window)
            fixed_amount_cost = WINDOW_DAYS / shares
            fixed_share_avg = sum(row.close for row in window) / WINDOW_DAYS
            window_end_close = window[-1].close
            ratio = window_end_close / fixed_amount_cost * 100.0
            today = price_dates.get(target_key)
            rows.append(
                {
                    "date": target_key,
                    "window_trading_days": WINDOW_DAYS,
                    "window_start": window[0].date,
                    "window_end": window[-1].date,
                    "window_end_close": round(window_end_close, 4),
                    "qqq_close": round(today.close, 4) if today else None,
                    "fixed_amount_dca_cost": round(fixed_amount_cost, 4),
                    "fixed_share_avg_cost": round(fixed_share_avg, 4),
                    "price_to_dca_pct": round(ratio, 4),
                    "min_close_in_window": round(min(row.close for row in window), 4),
                    "max_close_in_window": round(max(row.close for row in window), 4),
                }
            )
        target += one_day

    return rows


def write_dca_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "date",
        "window_trading_days",
        "window_start",
        "window_end",
        "window_end_close",
        "qqq_close",
        "fixed_amount_dca_cost",
        "fixed_share_avg_cost",
        "price_to_dca_pct",
        "min_close_in_window",
        "max_close_in_window",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_public_payload(rows: list[dict[str, object]], prices: list[PriceRow]) -> None:
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    latest = rows[-1] if rows else None
    min_ratio = min(rows, key=lambda row: float(row["price_to_dca_pct"])) if rows else None
    max_ratio = max(rows, key=lambda row: float(row["price_to_dca_pct"])) if rows else None
    payload = {
        "symbol": SYMBOL,
        "windowTradingDays": WINDOW_DAYS,
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latestPriceDate": prices[-1].date if prices else None,
        "latest": latest,
        "minRatio": min_ratio,
        "maxRatio": max_ratio,
        "rows": rows,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    DCA_JSON.write_text(text + "\n", encoding="utf-8")
    DCA_JS.write_text("window.QQQ_DCA_DATA = " + text + ";\n", encoding="utf-8")


def ensure_initial_seed(seed: Path | None) -> None:
    if PRICE_CSV.exists() or not seed:
        return
    if not seed.exists():
        raise FileNotFoundError(f"Seed CSV not found: {seed}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRICE_CSV.write_text(seed.read_text(encoding="utf-8-sig"), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, help="Optional seed qqq_prices.csv path")
    parser.add_argument("--extra-yahoo-json", type=Path, help="Optional local Yahoo chart JSON to merge")
    parser.add_argument("--as-of", help="Calendar date to calculate through, yyyy-mm-dd")
    parser.add_argument("--no-fetch", action="store_true", help="Use local CSV only")
    args = parser.parse_args()

    ensure_initial_seed(args.seed)
    prices = load_prices(PRICE_CSV)
    as_of = parse_date(args.as_of) if args.as_of else date.today()

    if not args.no_fetch:
        if prices:
            start = parse_date(prices[-1].date) - timedelta(days=10)
        else:
            start = date(1999, 3, 1)
        end = as_of + timedelta(days=2)
        fetched = fetch_yahoo_prices(SYMBOL, start, end)
        prices = merge_prices(prices, fetched)

    if args.extra_yahoo_json:
        payload = json.loads(args.extra_yahoo_json.read_text(encoding="utf-8"))
        prices = merge_prices(prices, parse_yahoo_chart_payload(payload))

    if not prices:
        print("No price data available.", file=sys.stderr)
        return 1

    write_prices(PRICE_CSV, prices)
    rows = calculate_dca(prices, as_of=as_of)
    write_dca_csv(DCA_CSV, rows)
    write_dca_csv(PUBLIC_DCA_CSV, rows)
    write_public_payload(rows, prices)

    latest = rows[-1] if rows else {}
    print(f"Updated {len(prices)} price rows and {len(rows)} DCA rows.")
    if latest:
        print(
            "Latest:",
            latest["date"],
            "price",
            latest["window_end_close"],
            "dca",
            latest["fixed_amount_dca_cost"],
            "ratio",
            f"{latest['price_to_dca_pct']}%",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
