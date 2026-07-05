import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
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
    if not ENV_FILE.exists():
        return ""

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _get_api_key() -> str:
    return os.getenv("FINNHUB_API_KEY", "").strip() or _read_env_file_value("FINNHUB_API_KEY")


def _finnhub_get(path: str, params: dict) -> dict:
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is not set.")

    query = urlencode({**params, "token": api_key})
    with urlopen(f"{FINNHUB_BASE_URL}{path}?{query}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get_top_100_stocks() -> list[dict] | None:
    try:
        stocks = []
        for symbol in TOP_100_STOCKS:
            quote = _finnhub_get("/quote", {"symbol": symbol})
            current_price = float(quote.get("c") or 0)
            previous_close = float(quote.get("pc") or 0)
            change = round(current_price - previous_close, 2)
            percent_change = round((change / previous_close) * 100, 2) if previous_close else 0.0
            stocks.append(
                {
                    "symbol": symbol,
                    "price": round(current_price, 2),
                    "change": change,
                    "percent_change": percent_change,
                }
            )
        return stocks
    except (RuntimeError, URLError, ValueError, TypeError):
        return None
