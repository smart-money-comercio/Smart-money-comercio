import yfinance as yf


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
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        history = stock.history(period="1y")

        if history.empty:
            return {
                "found": False,
                "ticker": ticker.upper(),
                "error": "No price history found"
            }

        latest_price = history["Close"].iloc[-1]
        week_52_high = history["High"].max()
        week_52_low = history["Low"].min()

        return {
            "found": True,
            "ticker": ticker.upper(),
            "company_name": info.get("shortName") or info.get("longName") or ticker.upper(),
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

    except Exception as error:
        return {
            "found": False,
            "ticker": ticker.upper(),
            "error": str(error)
        }