#!/usr/bin/env python3
"""Update popular US stock 180-trading-day DCA data.

The fixed-amount DCA cost uses the harmonic-mean style formula:

    cost = N / sum(1 / close_i)

where N is 180 and close_i are the latest 180 trading-day closes in the
calculation window.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


WINDOW_DAYS = 180
PUBLIC_SERIES_ROWS = 1265
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PRICE_DIR = DATA_DIR / "prices"
PUBLIC_DATA_DIR = PROJECT_ROOT / "public" / "data"
MARKET_JSON = PUBLIC_DATA_DIR / "market_dca.json"
MARKET_JS = PUBLIC_DATA_DIR / "market_dca.js"

# Compatibility outputs used by the original single-QQQ site.
QQQ_PRICE_CSV = DATA_DIR / "qqq_prices.csv"
QQQ_DCA_CSV = DATA_DIR / "qqq_180d_dca.csv"
PUBLIC_QQQ_DCA_CSV = PUBLIC_DATA_DIR / "qqq_180d_dca.csv"
PUBLIC_QQQ_JSON = PUBLIC_DATA_DIR / "qqq_180d_dca.json"
PUBLIC_QQQ_JS = PUBLIC_DATA_DIR / "qqq_180d_dca.js"

SYMBOLS: list[dict[str, str]] = [
    {"symbol": "QQQ", "name": "纳斯达克100ETF", "index": "Nasdaq 100", "sector": "ETF"},
    {"symbol": "SPY", "name": "标普500ETF", "index": "S&P 500", "sector": "ETF"},
    {"symbol": "AAPL", "name": "苹果", "index": "Nasdaq 100 / S&P 500", "sector": "科技硬件"},
    {"symbol": "MSFT", "name": "微软", "index": "Nasdaq 100 / S&P 500", "sector": "软件"},
    {"symbol": "NVDA", "name": "英伟达", "index": "Nasdaq 100 / S&P 500", "sector": "半导体"},
    {"symbol": "AMZN", "name": "亚马逊", "index": "Nasdaq 100 / S&P 500", "sector": "互联网零售"},
    {"symbol": "GOOGL", "name": "谷歌A", "index": "Nasdaq 100 / S&P 500", "sector": "互联网"},
    {"symbol": "META", "name": "Meta", "index": "Nasdaq 100 / S&P 500", "sector": "互联网"},
    {"symbol": "TSLA", "name": "特斯拉", "index": "Nasdaq 100 / S&P 500", "sector": "汽车"},
    {"symbol": "AVGO", "name": "博通", "index": "Nasdaq 100 / S&P 500", "sector": "半导体"},
    {"symbol": "COST", "name": "好市多", "index": "Nasdaq 100 / S&P 500", "sector": "零售"},
    {"symbol": "NFLX", "name": "奈飞", "index": "Nasdaq 100 / S&P 500", "sector": "流媒体"},
    {"symbol": "AMD", "name": "AMD", "index": "Nasdaq 100 / S&P 500", "sector": "半导体"},
    {"symbol": "ADBE", "name": "Adobe", "index": "Nasdaq 100 / S&P 500", "sector": "软件"},
    {"symbol": "CSCO", "name": "思科", "index": "Nasdaq 100 / S&P 500", "sector": "网络设备"},
    {"symbol": "PEP", "name": "百事", "index": "Nasdaq 100 / S&P 500", "sector": "消费品"},
    {"symbol": "QCOM", "name": "高通", "index": "Nasdaq 100 / S&P 500", "sector": "半导体"},
    {"symbol": "AMAT", "name": "应用材料", "index": "Nasdaq 100 / S&P 500", "sector": "半导体设备"},
    {"symbol": "INTU", "name": "Intuit", "index": "Nasdaq 100 / S&P 500", "sector": "软件"},
    {"symbol": "BKNG", "name": "Booking", "index": "Nasdaq 100 / S&P 500", "sector": "在线旅游"},
    {"symbol": "JPM", "name": "摩根大通", "index": "S&P 500", "sector": "金融"},
    {"symbol": "V", "name": "Visa", "index": "S&P 500", "sector": "支付"},
    {"symbol": "MA", "name": "万事达", "index": "S&P 500", "sector": "支付"},
    {"symbol": "LLY", "name": "礼来", "index": "S&P 500", "sector": "医药"},
    {"symbol": "UNH", "name": "联合健康", "index": "S&P 500", "sector": "医疗保险"},
    {"symbol": "XOM", "name": "埃克森美孚", "index": "S&P 500", "sector": "能源"},
    {"symbol": "JNJ", "name": "强生", "index": "S&P 500", "sector": "医药消费"},
    {"symbol": "PG", "name": "宝洁", "index": "S&P 500", "sector": "消费品"},
    {"symbol": "HD", "name": "家得宝", "index": "S&P 500", "sector": "家装零售"},
    {"symbol": "WMT", "name": "沃尔玛", "index": "S&P 500", "sector": "零售"},
    {"symbol": "KO", "name": "可口可乐", "index": "S&P 500", "sector": "消费品"},
    {"symbol": "BAC", "name": "美国银行", "index": "S&P 500", "sector": "金融"},
    {"symbol": "ORCL", "name": "甲骨文", "index": "S&P 500", "sector": "软件"},
    {"symbol": "CRM", "name": "Salesforce", "index": "S&P 500", "sector": "软件"},
    {"symbol": "MCD", "name": "麦当劳", "index": "S&P 500", "sector": "餐饮"},
    {"symbol": "GE", "name": "GE Aerospace", "index": "S&P 500", "sector": "工业"},
]


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


def price_path(symbol: str) -> Path:
    return PRICE_DIR / f"{symbol.replace('.', '-').replace('/', '-')}.csv"


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
            "User-Agent": "Mozilla/5.0 investment-dca-site/2.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=35) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_yahoo_chart_payload(payload)


def parse_yahoo_chart_payload(payload: dict[str, Any]) -> list[PriceRow]:
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
        return [
            PriceRow(
                date=row["date"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                adj_close=float(row.get("adj_close") or row["close"]),
                volume=int(float(row.get("volume") or 0)),
            )
            for row in reader
        ]


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


def zone_for(row: dict[str, Any]) -> dict[str, str]:
    ratio = float(row["price_to_dca_pct"])
    drawdown = float(row["drawdown_from_window_high_pct"])
    if ratio <= 90 or drawdown <= -30:
        return {"label": "深度关注", "tone": "buy"}
    if ratio <= 97 or drawdown <= -20:
        return {"label": "偏低区", "tone": "watch"}
    if ratio <= 105:
        return {"label": "正常区", "tone": "neutral"}
    if ratio <= 115:
        return {"label": "偏热区", "tone": "warm"}
    return {"label": "高位区", "tone": "hot"}


def calculate_dca(prices: list[PriceRow]) -> list[dict[str, Any]]:
    if len(prices) < WINDOW_DAYS:
        return []

    rows: list[dict[str, Any]] = []
    for i in range(WINDOW_DAYS - 1, len(prices)):
        window = prices[i - WINDOW_DAYS + 1 : i + 1]
        close = window[-1].close
        shares = sum(1.0 / row.close for row in window)
        fixed_amount_cost = WINDOW_DAYS / shares
        moving_avg = sum(row.close for row in window) / WINDOW_DAYS
        min_close = min(row.close for row in window)
        max_close = max(row.close for row in window)
        row: dict[str, Any] = {
            "date": window[-1].date,
            "window_trading_days": WINDOW_DAYS,
            "window_start": window[0].date,
            "window_end": window[-1].date,
            "close": round(close, 4),
            "fixed_amount_dca_cost": round(fixed_amount_cost, 4),
            "moving_avg_180": round(moving_avg, 4),
            "price_to_dca_pct": round(close / fixed_amount_cost * 100.0, 4),
            "price_to_ma_pct": round(close / moving_avg * 100.0, 4),
            "min_close_in_window": round(min_close, 4),
            "max_close_in_window": round(max_close, 4),
            "drawdown_from_window_high_pct": round((close / max_close - 1.0) * 100.0, 4),
            "above_window_low_pct": round((close / min_close - 1.0) * 100.0, 4),
            "volume": window[-1].volume,
        }
        row["zone"] = zone_for(row)
        rows.append(row)
    return rows


def summarize_symbol(meta: dict[str, str], prices: list[PriceRow], rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest = rows[-1]
    min_ratio = min(rows, key=lambda row: float(row["price_to_dca_pct"]))
    max_ratio = max(rows, key=lambda row: float(row["price_to_dca_pct"]))
    return {
        **meta,
        "latestPriceDate": prices[-1].date,
        "historyStart": prices[0].date,
        "historyRows": len(prices),
        "dcaRows": len(rows),
        "latest": latest,
        "minRatio": min_ratio,
        "maxRatio": max_ratio,
    }


def write_symbol_csv(symbol: str, rows: list[dict[str, Any]]) -> None:
    fields = [
        "date",
        "window_trading_days",
        "window_start",
        "window_end",
        "close",
        "fixed_amount_dca_cost",
        "moving_avg_180",
        "price_to_dca_pct",
        "price_to_ma_pct",
        "min_close_in_window",
        "max_close_in_window",
        "drawdown_from_window_high_pct",
        "above_window_low_pct",
        "volume",
    ]
    path = DATA_DIR / f"{symbol.lower()}_180d_dca.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fields})


def compact_public_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row["date"],
            row["window_start"],
            row["window_end"],
            row["close"],
            row["fixed_amount_dca_cost"],
            row["moving_avg_180"],
            row["price_to_dca_pct"],
            row["price_to_ma_pct"],
            row["min_close_in_window"],
            row["max_close_in_window"],
            row["drawdown_from_window_high_pct"],
            row["above_window_low_pct"],
            row["volume"],
            row["zone"]["label"],
            row["zone"]["tone"],
        ]
        for row in rows[-PUBLIC_SERIES_ROWS:]
    ]


def write_qqq_compat(prices: list[PriceRow], rows: list[dict[str, Any]], payload: dict[str, Any]) -> None:
    write_prices(QQQ_PRICE_CSV, prices)
    write_symbol_csv("qqq", rows)
    PUBLIC_QQQ_DCA_CSV.write_text(QQQ_DCA_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    qqq_payload = {
        "symbol": "QQQ",
        "windowTradingDays": WINDOW_DAYS,
        "updatedAt": payload["updatedAt"],
        "latestPriceDate": prices[-1].date if prices else None,
        "latest": rows[-1] if rows else None,
        "minRatio": min(rows, key=lambda row: float(row["price_to_dca_pct"])) if rows else None,
        "maxRatio": max(rows, key=lambda row: float(row["price_to_dca_pct"])) if rows else None,
        "rows": rows,
    }
    text = json.dumps(qqq_payload, ensure_ascii=False, separators=(",", ":"))
    PUBLIC_QQQ_JSON.write_text(text + "\n", encoding="utf-8")
    PUBLIC_QQQ_JS.write_text("window.QQQ_DCA_DATA = " + text + ";\n", encoding="utf-8")


def update_symbol(meta: dict[str, str], as_of: date, no_fetch: bool) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[PriceRow], str | None]:
    symbol = meta["symbol"]
    path = QQQ_PRICE_CSV if symbol == "QQQ" and QQQ_PRICE_CSV.exists() else price_path(symbol)
    prices = load_prices(path)

    if not no_fetch:
        start = parse_date(prices[-1].date) - timedelta(days=10) if prices else date(2010, 1, 1)
        end = as_of + timedelta(days=2)
        fetched = fetch_yahoo_prices(symbol, start, end)
        prices = merge_prices(prices, fetched)
        time.sleep(0.2)

    if len(prices) < WINDOW_DAYS:
        return None, [], prices, f"{symbol}: price history shorter than {WINDOW_DAYS} rows"

    write_prices(price_path(symbol), prices)
    rows = calculate_dca(prices)
    write_symbol_csv(symbol, rows)
    return summarize_symbol(meta, prices, rows), rows, prices, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", help="Calendar date to fetch through, yyyy-mm-dd")
    parser.add_argument("--no-fetch", action="store_true", help="Use local CSV files only")
    parser.add_argument(
        "--symbols",
        help="Comma-separated Yahoo symbols to update. Defaults to the curated popular list.",
    )
    args = parser.parse_args()

    as_of = parse_date(args.as_of) if args.as_of else date.today()
    wanted = {item.strip().upper() for item in args.symbols.split(",")} if args.symbols else None
    metas = [meta for meta in SYMBOLS if wanted is None or meta["symbol"].upper() in wanted]

    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    series: dict[str, list[list[Any]]] = {}
    errors: list[str] = []
    qqq_prices: list[PriceRow] = []
    qqq_rows: list[dict[str, Any]] = []

    for meta in metas:
        symbol = meta["symbol"]
        try:
            summary, rows, prices, error = update_symbol(meta, as_of=as_of, no_fetch=args.no_fetch)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            print(f"Failed {symbol}: {exc}", file=sys.stderr)
            continue

        if error:
            errors.append(error)
            print(error, file=sys.stderr)
            continue

        assert summary is not None
        summaries.append(summary)
        series[symbol] = compact_public_rows(rows)
        if symbol == "QQQ":
            qqq_prices = prices
            qqq_rows = rows
        print(f"Updated {symbol}: {len(prices)} prices, latest {rows[-1]['date']}")

    summaries.sort(key=lambda item: (item["index"] != "Nasdaq 100", item["symbol"]))
    payload = {
        "windowTradingDays": WINDOW_DAYS,
        "publicSeriesRows": PUBLIC_SERIES_ROWS,
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Yahoo Finance chart endpoint",
        "seriesColumns": [
            "date",
            "window_start",
            "window_end",
            "close",
            "fixed_amount_dca_cost",
            "moving_avg_180",
            "price_to_dca_pct",
            "price_to_ma_pct",
            "min_close_in_window",
            "max_close_in_window",
            "drawdown_from_window_high_pct",
            "above_window_low_pct",
            "volume",
            "zone_label",
            "zone_tone",
        ],
        "symbols": summaries,
        "series": series,
        "errors": errors,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    MARKET_JSON.write_text(text + "\n", encoding="utf-8")
    MARKET_JS.write_text("window.MARKET_DCA_DATA = " + text + ";\n", encoding="utf-8")

    if qqq_prices and qqq_rows:
        write_qqq_compat(qqq_prices, qqq_rows, payload)

    if not summaries:
        print("No symbols updated.", file=sys.stderr)
        return 1

    print(f"Updated {len(summaries)} symbols. Errors: {len(errors)}")
    return 0 if len(summaries) >= max(1, len(metas) // 2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
