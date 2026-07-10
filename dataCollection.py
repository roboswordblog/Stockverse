import json
import os
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import certifi

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
BASE_DIR = Path(__file__).resolve().parent
ENV_FILES = [BASE_DIR / "api.env", BASE_DIR / ".env"]
CACHE_FILE = BASE_DIR / "data" / "market_cache.json"
QUOTE_REFRESH_SECONDS = 15
PRIORITY_SYMBOL_COUNT = 5
ROTATION_BATCH_SIZE = 5
CHART_RANGES = {
    "1D": {"resolution": "15", "seconds": 60 * 60 * 24},
    "1W": {"resolution": "60", "seconds": 60 * 60 * 24 * 7},
    "1M": {"resolution": "D", "seconds": 60 * 60 * 24 * 30},
}
TOP_100_STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "TSLA", "LLY", "AVGO",
    "JPM", "WMT", "V", "XOM", "MA", "UNH", "ORCL", "COST", "NFLX", "HD",
    "PG", "JNJ", "BAC", "ABBV", "KO", "CRM", "CVX", "TMUS", "MRK", "AMD",
    "PEP", "TMO", "LIN", "MCD", "CSCO", "WFC", "ACN", "ABT", "DHR", "DIS",
    "ADBE", "INTU", "TXN", "QCOM", "PM", "NEE", "MS", "BMY", "UNP", "VZ",
    "RTX", "IBM", "SPGI", "GS", "CAT", "AMGN", "LOW", "PFE", "ISRG", "BLK",
    "HON", "INTC", "AXP", "UBER", "CMCSA", "AMAT", "BKNG", "SYK", "TJX", "NOW",
    "COP", "DE", "ELV", "VRTX", "PLD", "MDT", "GE", "GILD", "SCHW", "ADP",
    "LRCX", "CB", "MMC", "C", "T", "NKE", "SO", "MO", "DUK", "PANW",
    "ANET", "ADI", "MDLZ", "UPS", "CI", "EOG", "REGN", "BA", "MU", "SNPS",
]


def _read_env_file_value(key: str) -> str:
    for env_file in ENV_FILES:
        if not env_file.exists():
            continue

        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            current_key, value = line.split("=", 1)
            if current_key.strip() == key:
                return value.strip().strip('"').strip("'")
    return ""


def _get_api_key() -> str:
    file_key = _read_env_file_value("FINNHUB_API_KEY")
    if file_key:
        return file_key
    return os.getenv("FINNHUB_API_KEY", "").strip()


def _read_cache() -> dict[str, dict]:
    if not CACHE_FILE.exists():
        return {}
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        if "stocks" in payload and isinstance(payload.get("stocks"), dict):
            return payload["stocks"]
        # Backward compatibility for older cache layout.
        return payload
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(stock_map: dict[str, dict]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stocks": stock_map, "meta": _read_cache_meta()}
    CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")


def _read_cache_meta() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
            return payload["meta"]
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _write_cache_with_meta(stock_map: dict[str, dict], meta: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stocks": stock_map, "meta": meta}
    CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")


def _symbols_to_refresh(cursor: int) -> tuple[list[str], int]:
    priority = TOP_100_STOCKS[:PRIORITY_SYMBOL_COUNT]
    rotating = TOP_100_STOCKS[PRIORITY_SYMBOL_COUNT:]
    if not rotating:
        return priority, 0

    batch_start = max(0, cursor) % len(rotating)
    batch = rotating[batch_start:batch_start + ROTATION_BATCH_SIZE]
    if len(batch) < ROTATION_BATCH_SIZE:
        batch.extend(rotating[:ROTATION_BATCH_SIZE - len(batch)])
    next_cursor = (batch_start + ROTATION_BATCH_SIZE) % len(rotating)
    # Keep priority quotes fresh on every refresh; rotate the rest over time.
    return priority + batch, next_cursor


def _sorted_stock_list(stock_map: dict[str, dict]) -> list[dict]:
    return [stock_map[symbol] for symbol in TOP_100_STOCKS if symbol in stock_map]


def get_market_last_refresh() -> int:
    meta = _read_cache_meta()
    return int(meta.get("last_refresh") or 0)


def get_market_status() -> dict:
    meta = _read_cache_meta()
    return {
        "last_refresh": int(meta.get("last_refresh") or 0),
        "last_attempt": int(meta.get("last_attempt") or 0),
        "source": (meta.get("source") or "cache"),
        "error": (meta.get("error") or "").strip(),
    }


def _interpolate_series(anchor_values: list[float], point_count: int) -> list[float]:
    if not anchor_values:
        return []
    if len(anchor_values) == 1:
        return [round(anchor_values[0], 2)] * max(1, point_count)

    steps = max(2, point_count)
    output = []
    segment_count = len(anchor_values) - 1
    for index in range(steps):
        position = index / (steps - 1)
        segment_position = position * segment_count
        segment_index = min(int(segment_position), segment_count - 1)
        local_progress = segment_position - segment_index
        start_value = anchor_values[segment_index]
        end_value = anchor_values[segment_index + 1]
        value = start_value + (end_value - start_value) * local_progress
        output.append(round(value, 2))
    return output


def _synthetic_history_points(quote: dict, range_key: str, now: int) -> list[dict]:
    config = CHART_RANGES.get(range_key.upper(), CHART_RANGES["1M"])
    current_price = float(quote.get("price") or 0)
    previous_close = float(quote.get("previous_close") or 0) or current_price
    open_price = float(quote.get("open") or 0) or previous_close
    high_price = float(quote.get("high") or 0) or max(previous_close, current_price, open_price)
    low_price = float(quote.get("low") or 0) or min(previous_close, current_price, open_price)
    delta = current_price - previous_close
    amplitude = max(abs(delta) * 0.7, max(current_price, previous_close, 1) * 0.004, 0.35)

    if high_price == low_price:
        high_price = max(high_price, current_price, previous_close) + amplitude
        low_price = min(low_price, current_price, previous_close) - amplitude
    if open_price == current_price == previous_close:
        open_price = previous_close + (amplitude * 0.2)

    mid_one = max(open_price, previous_close) + (amplitude * 0.4)
    mid_two = min(current_price, previous_close) - (amplitude * 0.35)

    if delta >= 0:
        anchors = [previous_close, open_price, low_price, mid_one, high_price, current_price]
    else:
        anchors = [previous_close, open_price, high_price, mid_two, low_price, current_price]

    point_count = 12 if range_key.upper() == "1D" else 9 if range_key.upper() == "1W" else 10
    interpolated = _interpolate_series(anchors, point_count)
    start_time = now - int(config["seconds"])
    time_step = int(config["seconds"] / max(point_count - 1, 1))
    return [
        {"time": start_time + (time_step * index), "close": round(max(value, 0.01), 2)}
        for index, value in enumerate(interpolated)
    ]


def _fallback_history(symbol: str, range_key: str) -> dict:
    quote = get_stock_quote(symbol)
    if not quote:
        return {"range": range_key.upper(), "points": [], "source": "unavailable", "error": "Chart unavailable"}

    now = int(time.time())
    points = _synthetic_history_points(quote, range_key, now)
    if len(points) < 2:
        return {"range": range_key.upper(), "points": [], "source": "unavailable", "error": "Chart unavailable"}
    return {"range": range_key.upper(), "points": points, "source": "synthetic", "error": ""}


def _finnhub_get(path: str, params: dict) -> dict:
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is not set.")

    query = urlencode({**params, "token": api_key})
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(f"{FINNHUB_BASE_URL}{path}?{query}", timeout=10, context=ssl_context) as response:
        return json.loads(response.read().decode("utf-8"))


def get_top_100_stocks() -> list[dict] | None:
    stock_map = _read_cache()
    meta = _read_cache_meta()
    now = int(time.time())
    last_refresh = int(meta.get("last_refresh") or 0)
    meta["last_attempt"] = now

    has_cached = any(symbol in stock_map for symbol in TOP_100_STOCKS)
    if has_cached and (now - last_refresh) < QUOTE_REFRESH_SECONDS:
        meta["source"] = "cache"
        meta["error"] = ""
        _write_cache_with_meta(stock_map, meta)
        return _sorted_stock_list(stock_map)

    cursor = int(meta.get("cursor") or 0)
    symbols, next_cursor = _symbols_to_refresh(cursor)
    refreshed = False

    try:
        for symbol in symbols:
            quote = _finnhub_get("/quote", {"symbol": symbol})
            current_price = float(quote.get("c") or 0)
            previous_close = float(quote.get("pc") or 0)
            change = round(current_price - previous_close, 2)
            percent_change = round((change / previous_close) * 100, 2) if previous_close else 0.0
            stock_map[symbol] = {
                "symbol": symbol,
                "price": round(current_price, 2),
                "change": change,
                "percent_change": percent_change,
            }
            refreshed = True

        meta["cursor"] = next_cursor
        if refreshed:
            meta["last_refresh"] = now
            meta["source"] = "live"
            meta["error"] = ""
        _write_cache_with_meta(stock_map, meta)
        return _sorted_stock_list(stock_map)
    except HTTPError as error:
        if refreshed:
            meta["cursor"] = next_cursor
            meta["last_refresh"] = now
        meta["source"] = "cache"
        if error.code in (401, 403):
            meta["error"] = "API key rejected"
            # Clear stale market cache so invalid credentials do not look like live data.
            _write_cache_with_meta({}, meta)
            return None
        if error.code == 429:
            meta["error"] = "Rate limited"
        else:
            meta["error"] = f"HTTP {error.code}"
        _write_cache_with_meta(stock_map, meta)
        if error.code == 429 and stock_map:
            return _sorted_stock_list(stock_map)
        return _sorted_stock_list(stock_map) or None
    except (RuntimeError, URLError, ValueError, TypeError):
        if refreshed:
            meta["cursor"] = next_cursor
            meta["last_refresh"] = now
        meta["source"] = "cache"
        meta["error"] = "Network unavailable"
        _write_cache_with_meta(stock_map, meta)
        return _sorted_stock_list(stock_map) or None


def get_stock_quote(symbol: str) -> dict | None:
    try:
        quote = _finnhub_get("/quote", {"symbol": symbol})
        current_price = float(quote.get("c") or 0)
        previous_close = float(quote.get("pc") or 0)
        change = round(current_price - previous_close, 2)
        percent_change = round((change / previous_close) * 100, 2) if previous_close else 0.0
        return {
            "symbol": symbol,
            "price": round(current_price, 2),
            "change": change,
            "percent_change": percent_change,
            "high": round(float(quote.get("h") or 0), 2),
            "low": round(float(quote.get("l") or 0), 2),
            "open": round(float(quote.get("o") or 0), 2),
            "previous_close": round(previous_close, 2),
        }
    except HTTPError as error:
        if error.code in (401, 403):
            return None
        cached = _read_cache().get(symbol)
        if not cached:
            return None
        return {
            "symbol": symbol,
            "price": round(float(cached.get("price") or 0), 2),
            "change": round(float(cached.get("change") or 0), 2),
            "percent_change": round(float(cached.get("percent_change") or 0), 2),
            "high": round(float(cached.get("price") or 0), 2),
            "low": round(float(cached.get("price") or 0), 2),
            "open": round(float(cached.get("price") or 0), 2),
            "previous_close": round(float(cached.get("price") or 0) - float(cached.get("change") or 0), 2),
        }
    except (RuntimeError, URLError, ValueError, TypeError):
        cached = _read_cache().get(symbol)
        if not cached:
            return None
        return {
            "symbol": symbol,
            "price": round(float(cached.get("price") or 0), 2),
            "change": round(float(cached.get("change") or 0), 2),
            "percent_change": round(float(cached.get("percent_change") or 0), 2),
            "high": round(float(cached.get("price") or 0), 2),
            "low": round(float(cached.get("price") or 0), 2),
            "open": round(float(cached.get("price") or 0), 2),
            "previous_close": round(float(cached.get("price") or 0) - float(cached.get("change") or 0), 2),
        }


def get_stock_profile(symbol: str) -> dict | None:
    try:
        profile = _finnhub_get("/stock/profile2", {"symbol": symbol})
        return {
            "name": profile.get("name") or symbol,
            "exchange": profile.get("exchange") or "Unknown",
            "industry": profile.get("finnhubIndustry") or "Unknown",
            "country": profile.get("country") or "Unknown",
            "weburl": profile.get("weburl") or "",
        }
    except (RuntimeError, HTTPError, URLError, ValueError, TypeError):
        return None


def get_stock_history(symbol: str, range_key: str) -> dict:
    config = CHART_RANGES.get(range_key.upper(), CHART_RANGES["1M"])
    to_timestamp = int(time.time())
    from_timestamp = to_timestamp - int(config["seconds"])

    try:
        response = _finnhub_get(
            "/stock/candle",
            {
                "symbol": symbol,
                "resolution": config["resolution"],
                "from": from_timestamp,
                "to": to_timestamp,
            },
        )
        if response.get("s") != "ok":
            return _fallback_history(symbol, range_key)

        closes = response.get("c") or []
        timestamps = response.get("t") or []
        points = []
        for timestamp, close in zip(timestamps, closes):
            try:
                price = round(float(close), 2)
                point_time = int(timestamp)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            points.append({"time": point_time, "close": price})

        if len(points) < 2:
            return _fallback_history(symbol, range_key)

        return {"range": range_key.upper(), "points": points, "source": "history", "error": ""}
    except (RuntimeError, HTTPError, URLError, ValueError, TypeError):
        return _fallback_history(symbol, range_key)


def search_stocks(query: str) -> list[dict]:
    cleaned = query.strip()
    if not cleaned:
        return []

    try:
        response = _finnhub_get("/search", {"q": cleaned})
        results = []
        for item in response.get("result", [])[:30]:
            symbol = (item.get("symbol") or "").strip()
            description = (item.get("description") or symbol).strip()
            if not symbol:
                continue
            results.append(
                {
                    "symbol": symbol,
                    "description": description,
                    "type": (item.get("type") or "").strip(),
                }
            )
        return results
    except (RuntimeError, HTTPError, URLError, ValueError, TypeError):
        lowered = cleaned.lower()
        return [
            {"symbol": symbol, "description": symbol, "type": "cached"}
            for symbol in TOP_100_STOCKS
            if lowered in symbol.lower()
        ][:30]
