import asyncio
from datetime import datetime
from statistics import mean
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.watchlist_commands import fetch_quotes_for_symbols


MARKET_TIMEZONE = "America/New_York"

MARKET_SYMBOLS = [
    {"symbol": "SPY", "name": "S&P 500 ETF"},
    {"symbol": "QQQ", "name": "Nasdaq 100 ETF"},
    {"symbol": "DIA", "name": "Dow ETF"},
    {"symbol": "IWM", "name": "Russell 2000 ETF"},
    {"symbol": "^VIX", "name": "VIX Volatility Index"},
    {"symbol": "TLT", "name": "Long-Term Treasury ETF"},
    {"symbol": "GLD", "name": "Gold ETF"},
    {"symbol": "USO", "name": "Oil ETF"},
]


def get_quote_for_symbol(quotes: dict, symbol: str) -> dict | None:
    if not isinstance(quotes, dict):
        return None

    direct_quote = quotes.get(symbol)

    if isinstance(direct_quote, dict):
        return direct_quote

    upper_quote = quotes.get(symbol.upper())

    if isinstance(upper_quote, dict):
        return upper_quote

    for quote in quotes.values():
        if not isinstance(quote, dict):
            continue

        quote_symbol = str(
            quote.get("symbol")
            or quote.get("ticker")
            or ""
        ).upper()

        if quote_symbol == symbol.upper():
            return quote

    return None


def get_quote_value(quote: dict, keys: list[str]):
    for key in keys:
        value = quote.get(key)

        if value is not None:
            return value

    return None


def get_price(quote: dict | None) -> float | None:
    if not quote:
        return None

    value = get_quote_value(
        quote,
        [
            "price",
            "regularMarketPrice",
            "regular_market_price",
            "current_price",
            "last_price",
        ],
    )

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_change_percent(quote: dict | None) -> float | None:
    if not quote:
        return None

    value = get_quote_value(
        quote,
        [
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "regular_market_change_percent",
            "changePercent",
        ],
    )

    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_price(symbol: str, price: float | None) -> str:
    if price is None:
        return "Unavailable"

    if symbol == "^VIX":
        return f"{price:.2f}"

    return f"${price:,.2f}"


def format_change(change_percent: float | None) -> str:
    if change_percent is None:
        return "N/A"

    sign = "+" if change_percent >= 0 else ""
    return f"{sign}{change_percent:.2f}%"


def format_market_line(symbol: str, name: str, quote: dict | None) -> str:
    price = get_price(quote)
    change_percent = get_change_percent(quote)

    return (
        f"• {symbol} — {name}: "
        f"{format_price(symbol, price)} "
        f"({format_change(change_percent)})"
    )


def classify_vix(vix_level: float | None) -> str:
    if vix_level is None:
        return "Volatility data unavailable"

    if vix_level >= 30:
        return "Very high volatility"
    if vix_level >= 25:
        return "High volatility"
    if vix_level >= 20:
        return "Elevated volatility"
    if vix_level >= 15:
        return "Normal volatility"

    return "Calm volatility"


def classify_market_tone(quotes: dict) -> str:
    equity_symbols = ["SPY", "QQQ", "DIA", "IWM"]

    equity_changes = []

    for symbol in equity_symbols:
        quote = get_quote_for_symbol(quotes, symbol)
        change_percent = get_change_percent(quote)

        if change_percent is not None:
            equity_changes.append(change_percent)

    vix_quote = get_quote_for_symbol(quotes, "^VIX")
    vix_level = get_price(vix_quote)

    if not equity_changes:
        return "Data unavailable"

    average_equity_change = mean(equity_changes)
    positive_count = sum(1 for item in equity_changes if item > 0)
    negative_count = sum(1 for item in equity_changes if item < 0)

    if average_equity_change >= 0.75 and positive_count >= 3:
        tone = "Risk-on / bullish"
    elif average_equity_change <= -0.75 and negative_count >= 3:
        tone = "Risk-off / bearish"
    elif positive_count >= 3:
        tone = "Constructive / mildly bullish"
    elif negative_count >= 3:
        tone = "Defensive / mildly bearish"
    else:
        tone = "Mixed / neutral"

    if vix_level is not None and vix_level >= 25 and average_equity_change < 0:
        tone = "High-volatility risk-off"

    return tone


def build_readout(quotes: dict) -> str:
    spy = get_change_percent(get_quote_for_symbol(quotes, "SPY"))
    qqq = get_change_percent(get_quote_for_symbol(quotes, "QQQ"))
    iwm = get_change_percent(get_quote_for_symbol(quotes, "IWM"))
    tlt = get_change_percent(get_quote_for_symbol(quotes, "TLT"))
    gld = get_change_percent(get_quote_for_symbol(quotes, "GLD"))
    uso = get_change_percent(get_quote_for_symbol(quotes, "USO"))

    vix_level = get_price(get_quote_for_symbol(quotes, "^VIX"))
    vix_status = classify_vix(vix_level)

    readout_lines = []

    if spy is not None and qqq is not None:
        if qqq > spy:
            readout_lines.append("Tech/growth is leading the broader market.")
        elif spy > qqq:
            readout_lines.append("The broader market is leading tech/growth.")
        else:
            readout_lines.append("Tech and the broader market are moving together.")

    if iwm is not None and spy is not None:
        if iwm > spy:
            readout_lines.append("Small caps are showing relative strength.")
        elif iwm < spy:
            readout_lines.append("Small caps are lagging large caps.")

    readout_lines.append(f"Volatility: {vix_status}.")

    if tlt is not None:
        if tlt > 0:
            readout_lines.append("Bonds are higher, suggesting some defensive demand or rate relief.")
        elif tlt < 0:
            readout_lines.append("Bonds are lower, which may signal rate pressure.")

    if gld is not None:
        if gld > 0:
            readout_lines.append("Gold is bid, showing demand for safety or inflation hedges.")
        elif gld < 0:
            readout_lines.append("Gold is lower, suggesting less defensive demand.")

    if uso is not None:
        if uso > 0:
            readout_lines.append("Oil is higher, which can support energy names but pressure inflation-sensitive areas.")
        elif uso < 0:
            readout_lines.append("Oil is lower, which may ease inflation pressure.")

    if not readout_lines:
        return "Market readout unavailable."

    return "\n".join(f"• {line}" for line in readout_lines)


def build_marketbrief_message(quotes: dict) -> str:
    now = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    market_tone = classify_market_tone(quotes)

    lines = []

    for item in MARKET_SYMBOLS:
        symbol = item["symbol"]
        name = item["name"]
        quote = get_quote_for_symbol(quotes, symbol)
        lines.append(format_market_line(symbol, name, quote))

    readout = build_readout(quotes)

    return f"""
📊 Smart Money AI Market Brief

Time: {now.strftime("%Y-%m-%d %H:%M:%S")} {MARKET_TIMEZONE}
Market Tone: {market_tone}

Major Markets
{chr(10).join(lines)}

Readout
{readout}

Use /watchlist report for your custom stock list.
""".strip()


async def marketbrief_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Building Smart Money AI market brief...")

    symbols = [item["symbol"] for item in MARKET_SYMBOLS]

    try:
        quotes = await asyncio.to_thread(fetch_quotes_for_symbols, symbols)
    except Exception as exc:
        await update.message.reply_text(f"❌ Market brief failed: {exc}")
        return

    message = build_marketbrief_message(quotes)
    await update.message.reply_text(message)