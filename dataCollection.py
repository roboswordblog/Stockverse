import json
import os
from pathlib import Path
import ssl
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import certifi

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
BASE_DIR = Path(__file__).resolve().parent
ENV_FILES = [BASE_DIR / "api.env", BASE_DIR / ".env"]
CACHE_FILE = BASE_DIR / "data" / "market_cache.json"
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
    return os.getenv("FINNHUB_API_KEY", "").strip() or _read_env_file_value("FINNHUB_API_KEY")


def _read_cache() -> dict[str, dict]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_cache(stock_map: dict[str, dict]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(stock_map), encoding="utf-8")


def _sorted_stock_list(stock_map: dict[str, dict]) -> list[dict]:
    return [stock_map[symbol] for symbol in TOP_100_STOCKS if symbol in stock_map]


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

    try:
        for symbol in TOP_100_STOCKS:
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
        _write_cache(stock_map)
        return _sorted_stock_list(stock_map)
    except HTTPError as error:
        if error.code == 429 and stock_map:
            _write_cache(stock_map)
            return _sorted_stock_list(stock_map)
        return _sorted_stock_list(stock_map) or None
    except (RuntimeError, URLError, ValueError, TypeError):
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
    except (RuntimeError, HTTPError, URLError, ValueError, TypeError):
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
