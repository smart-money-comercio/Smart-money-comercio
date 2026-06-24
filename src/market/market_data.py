import yfinance as yf

from src.utils.cache import get_cache, set_cache


def format_number(value):
    if value is None:
        return "N/A"

    try:
        value = float(value)

        if value >= 1_000_000_000_000:
            return f"${value / 1_000_000_000_000:.2f}T"

        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"

        if value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"

        return f"${value:,.2f}"

    except Exception:
        return "N/A"


def format_percent(value):
    if value is None:
        return "N/A"

    try:
        value = float(value)

        if value <= 1:
            value = value * 100

        return f"{value:.2f}%"

    except Exception:
        return "N/A"


def get_market_data(ticker):
    symbol = ticker.upper()
    cache_key = f"market:{symbol}"

    cached = get_cache(cache_key)

    if cached:
        return cached

    try:
        stock = yf.Ticker(symbol)
        info = stock.info or {}

        history = stock.history(period="1y")

        if history.empty:
            return {
                "found": False,
                "ticker": symbol,
                "error": "No price history found",
            }

        latest_price = history["Close"].iloc[-1]
        week_52_high = history["High"].max()
        week_52_low = history["Low"].min()

        result = {
            "found": True,
            "ticker": symbol,
            "company_name": info.get("shortName") or info.get("longName") or symbol,
            "price": latest_price,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "week_52_high": week_52_high,
            "week_52_low": week_52_low,
            "sector": info.get("sector") or "N/A",
            "industry": info.get("industry") or "N/A",
        }

        set_cache(cache_key, result, ttl_seconds=900)

        return result

    except Exception as error:
        return {
            "found": False,
            "ticker": symbol,
            "error": str(error),
        }
