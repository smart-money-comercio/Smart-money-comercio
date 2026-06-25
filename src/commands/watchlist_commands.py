import asyncio
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import get_current_chat_id, is_admin
from src.utils.watchlist_store import (
    add_symbols,
    clear_watchlist,
    get_watchlist_file_path,
    load_watchlist,
    remove_symbols,
    reset_watchlist,
)


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-\^=]{0,14}$")
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

TELEGRAM_MESSAGE_LIMIT = 3900
QUOTE_TIMEOUT_SECONDS = 5
MAX_WORKERS = 8


def clean_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def is_valid_symbol(symbol: str) -> bool:
    cleaned = clean_symbol(symbol)
    return bool(SYMBOL_PATTERN.match(cleaned))


def clean_symbol_list(raw_symbols: list[str]) -> tuple[list[str], list[str]]:
    valid_symbols = []
    invalid_symbols = []

    for raw_symbol in raw_symbols:
        symbol = clean_symbol(raw_symbol)

        if not symbol:
            continue

        if is_valid_symbol(symbol):
            if symbol not in valid_symbols:
                valid_symbols.append(symbol)
        else:
            invalid_symbols.append(symbol)

    return valid_symbols, invalid_symbols


def format_watchlist(symbols: list[str]) -> str:
    if not symbols:
        return "Your watchlist is currently empty."

    return "\n".join(
        f"{index}. {symbol}"
        for index, symbol in enumerate(symbols, start=1)
    )


def format_price(value) -> str:
    if isinstance(value, (int, float)):
        return f"${value:,.2f}"

    return "N/A"


def format_change(value) -> str:
    if isinstance(value, (int, float)):
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.2f}"

    return "N/A"


def format_percent(value) -> str:
    if isinstance(value, (int, float)):
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,.2f}%"

    return "N/A"


def format_large_number(value) -> str:
    if not isinstance(value, (int, float)):
        return "N/A"

    abs_value = abs(value)

    if abs_value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"

    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"

    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"

    if abs_value >= 1_000:
        return f"{value / 1_000:.2f}K"

    return f"{value:,.0f}"


def get_signal(change_percent) -> str:
    if not isinstance(change_percent, (int, float)):
        return "⚪ No signal"

    if change_percent >= 2:
        return "🟢 Strong up"

    if change_percent > 0:
        return "🟢 Up"

    if change_percent <= -2:
        return "🔴 Strong down"

    if change_percent < 0:
        return "🔴 Down"

    return "⚪ Flat"


def latest_number(values: list) -> int | float | None:
    for value in reversed(values):
        if isinstance(value, (int, float)):
            return value

    return None


def calculate_change(price, previous_close) -> tuple[float | None, float | None]:
    if not isinstance(price, (int, float)):
        return None, None

    if not isinstance(previous_close, (int, float)):
        return None, None

    if previous_close == 0:
        return None, None

    change = price - previous_close
    change_percent = (change / previous_close) * 100

    return change, change_percent


def fetch_chart_quote(symbol: str) -> dict:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_CHART_URL}/{encoded_symbol}?range=5d&interval=1d"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=QUOTE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))

        chart = payload.get("chart", {})
        error = chart.get("error")

        if error:
            return {
                "symbol": symbol,
                "ok": False,
                "error": error.get("description", "Yahoo chart error"),
            }

        results = chart.get("result", [])

        if not results:
            return {
                "symbol": symbol,
                "ok": False,
                "error": "No chart data returned",
            }

        result = results[0]
        meta = result.get("meta", {})

        indicators = result.get("indicators", {})
        quote_data = indicators.get("quote", [{}])[0]

        close_values = quote_data.get("close", [])
        volume_values = quote_data.get("volume", [])

        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")

        if not isinstance(price, (int, float)):
            price = latest_number(close_values)

        if not isinstance(previous_close, (int, float)):
            valid_closes = [
                value for value in close_values
                if isinstance(value, (int, float))
            ]

            if len(valid_closes) >= 2:
                previous_close = valid_closes[-2]

        volume = latest_number(volume_values)
        change, change_percent = calculate_change(price, previous_close)

        return {
            "symbol": symbol,
            "ok": True,
            "price": price,
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
            "volume": volume,
            "exchange": meta.get("exchangeName") or meta.get("fullExchangeName") or "N/A",
            "currency": meta.get("currency", "USD"),
            "market_state": meta.get("marketState", "N/A"),
            "instrument_type": meta.get("instrumentType", "N/A"),
        }

    except HTTPError as error:
        return {
            "symbol": symbol,
            "ok": False,
            "error": f"HTTPError {error.code}",
        }

    except URLError:
        return {
            "symbol": symbol,
            "ok": False,
            "error": "Network error",
        }

    except TimeoutError:
        return {
            "symbol": symbol,
            "ok": False,
            "error": "Timeout",
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "ok": False,
            "error": type(error).__name__,
        }


def fetch_quotes_for_symbols(symbols: list[str]) -> dict[str, dict]:
    quote_results = {}

    if not symbols:
        return quote_results

    worker_count = min(MAX_WORKERS, len(symbols))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_symbol = {
            executor.submit(fetch_chart_quote, symbol): symbol
            for symbol in symbols
        }

        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]

            try:
                quote_results[symbol] = future.result()
            except Exception as error:
                quote_results[symbol] = {
                    "symbol": symbol,
                    "ok": False,
                    "error": type(error).__name__,
                }

    return quote_results


def build_watchlist_report(symbols: list[str], quote_results: dict[str, dict]) -> str:
    if not symbols:
        return (
            "📈 Watchlist Report\n\n"
            "Your watchlist is empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )

    lines = [
        "📈 Smart Money AI Watchlist Report",
        "",
    ]

    failed_symbols = []

    for symbol in symbols:
        quote = quote_results.get(symbol)

        if not quote:
            failed_symbols.append((symbol, "No quote result"))
            continue

        if not quote.get("ok"):
            failed_symbols.append((symbol, quote.get("error", "Unknown error")))
            continue

        price = quote.get("price")
        previous_close = quote.get("previous_close")
        change = quote.get("change")
        change_percent = quote.get("change_percent")
        volume = quote.get("volume")
        exchange = quote.get("exchange", "N/A")
        currency = quote.get("currency", "USD")
        market_state = quote.get("market_state", "N/A")
        instrument_type = quote.get("instrument_type", "N/A")
        signal = get_signal(change_percent)

        lines.extend([
            f"{symbol}",
            f"Price: {format_price(price)} {currency}",
            f"Change: {format_change(change)} ({format_percent(change_percent)})",
            f"Previous close: {format_price(previous_close)}",
            f"Signal: {signal}",
            f"Volume: {format_large_number(volume)}",
            f"Exchange: {exchange}",
            f"Type: {instrument_type}",
            f"Market state: {market_state}",
            "",
        ])

    if failed_symbols:
        lines.append("Symbols without report data:")

        for symbol, error in failed_symbols:
            lines.append(f"- {symbol}: {error}")

        lines.append("")

    lines.append("Commands:")
    lines.append("/watchlist movers")
    lines.append("/watchlist add SYMBOL")
    lines.append("/watchlist remove SYMBOL")
    lines.append("/watchlist list")

    return "\n".join(lines)


def build_watchlist_movers(symbols: list[str], quote_results: dict[str, dict]) -> str:
    if not symbols:
        return (
            "📊 Watchlist Movers\n\n"
            "Your watchlist is empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )

    gainers = []
    losers = []
    flat_or_unknown = []
    failed_symbols = []

    for symbol in symbols:
        quote = quote_results.get(symbol)

        if not quote:
            failed_symbols.append((symbol, "No quote result"))
            continue

        if not quote.get("ok"):
            failed_symbols.append((symbol, quote.get("error", "Unknown error")))
            continue

        change_percent = quote.get("change_percent")

        if not isinstance(change_percent, (int, float)):
            flat_or_unknown.append(quote)
            continue

        if change_percent > 0:
            gainers.append(quote)
        elif change_percent < 0:
            losers.append(quote)
        else:
            flat_or_unknown.append(quote)

    gainers.sort(key=lambda item: item.get("change_percent", 0), reverse=True)
    losers.sort(key=lambda item: item.get("change_percent", 0))

    lines = [
        "📊 Smart Money AI Watchlist Movers",
        "",
    ]

    if gainers:
        lines.append("🟢 Top Gainers")
        for quote in gainers:
            lines.append(
                f"{quote['symbol']}: "
                f"{format_price(quote.get('price'))} "
                f"({format_percent(quote.get('change_percent'))}) "
                f"{format_change(quote.get('change'))}"
            )
        lines.append("")
    else:
        lines.append("🟢 Top Gainers")
        lines.append("None")
        lines.append("")

    if losers:
        lines.append("🔴 Top Losers")
        for quote in losers:
            lines.append(
                f"{quote['symbol']}: "
                f"{format_price(quote.get('price'))} "
                f"({format_percent(quote.get('change_percent'))}) "
                f"{format_change(quote.get('change'))}"
            )
        lines.append("")
    else:
        lines.append("🔴 Top Losers")
        lines.append("None")
        lines.append("")

    if flat_or_unknown:
        lines.append("⚪ Flat / No Signal")
        for quote in flat_or_unknown:
            lines.append(
                f"{quote['symbol']}: "
                f"{format_price(quote.get('price'))} "
                f"({format_percent(quote.get('change_percent'))})"
            )
        lines.append("")

    if failed_symbols:
        lines.append("Symbols without mover data:")
        for symbol, error in failed_symbols:
            lines.append(f"- {symbol}: {error}")
        lines.append("")

    lines.append("Commands:")
    lines.append("/watchlist report")
    lines.append("/watchlist add SYMBOL")
    lines.append("/watchlist remove SYMBOL")
    lines.append("/watchlist list")

    return "\n".join(lines)


def split_long_message(message: str) -> list[str]:
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return [message]

    chunks = []
    current_chunk = ""

    for line in message.splitlines():
        candidate = f"{current_chunk}\n{line}" if current_chunk else line

        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = line
        else:
            current_chunk = candidate

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def send_split_message(update: Update, message: str, loading_message=None) -> None:
    if not update.message:
        return

    chunks = split_long_message(message)

    if loading_message:
        await loading_message.edit_text(chunks[0])
    else:
        await update.message.reply_text(chunks[0])

    for chunk in chunks[1:]:
        await update.message.reply_text(chunk)


async def watchlist_report(update: Update) -> None:
    if not update.message:
        return

    symbols = load_watchlist()

    if not symbols:
        await update.message.reply_text(
            "📈 Watchlist Report\n\n"
            "Your watchlist is empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )
        return

    loading_message = await update.message.reply_text(
        f"📈 Building watchlist report for {len(symbols)} symbol(s)..."
    )

    try:
        quote_results = await asyncio.to_thread(fetch_quotes_for_symbols, symbols)
        report = build_watchlist_report(symbols, quote_results)
        await send_split_message(update, report, loading_message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build watchlist report right now.\n\n"
            "The bot is online, but the market quote request failed.\n\n"
            f"Error:\n{type(error).__name__}"
        )


async def watchlist_movers(update: Update) -> None:
    if not update.message:
        return

    symbols = load_watchlist()

    if not symbols:
        await update.message.reply_text(
            "📊 Watchlist Movers\n\n"
            "Your watchlist is empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )
        return

    loading_message = await update.message.reply_text(
        f"📊 Finding watchlist movers for {len(symbols)} symbol(s)..."
    )

    try:
        quote_results = await asyncio.to_thread(fetch_quotes_for_symbols, symbols)
        movers = build_watchlist_movers(symbols, quote_results)
        await send_split_message(update, movers, loading_message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build watchlist movers right now.\n\n"
            "The bot is online, but the market quote request failed.\n\n"
            f"Error:\n{type(error).__name__}"
        )


async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}"
        )
        return

    args = context.args or []

    if not args:
        symbols = load_watchlist()

        await update.message.reply_text(
            "📋 Smart Money AI Watchlist\n\n"
            f"{format_watchlist(symbols)}\n\n"
            "Commands:\n"
            "/watchlist report\n"
            "/watchlist movers\n"
            "/watchlist add AAPL\n"
            "/watchlist add AAPL MSFT NVDA\n"
            "/watchlist remove AAPL\n"
            "/watchlist clear\n"
            "/watchlist reset\n"
            "/watchlist list"
        )
        return

    action = args[0].lower()

    if action in ["list", "show"]:
        symbols = load_watchlist()

        await update.message.reply_text(
            "📋 Smart Money AI Watchlist\n\n"
            f"{format_watchlist(symbols)}"
        )
        return

    if action in ["report", "summary", "prices"]:
        await watchlist_report(update)
        return

    if action in ["movers", "move", "leaders", "leaderboard"]:
        await watchlist_movers(update)
        return

    if action == "add":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage:\n"
                "/watchlist add AAPL\n"
                "/watchlist add AAPL MSFT NVDA"
            )
            return

        valid_symbols, invalid_symbols = clean_symbol_list(args[1:])

        if not valid_symbols:
            await update.message.reply_text(
                "No valid symbols were provided.\n\n"
                "Example:\n"
                "/watchlist add AAPL MSFT NVDA"
            )
            return

        symbols, added = add_symbols(valid_symbols)

        response = "✅ Watchlist updated.\n\n"

        if added:
            response += "Added:\n"
            response += "\n".join(f"- {symbol}" for symbol in added)
            response += "\n\n"
        else:
            response += "No new symbols added. They may already be on the watchlist.\n\n"

        if invalid_symbols:
            response += "Skipped invalid symbols:\n"
            response += "\n".join(f"- {symbol}" for symbol in invalid_symbols)
            response += "\n\n"

        response += "Current watchlist:\n"
        response += format_watchlist(symbols)

        await update.message.reply_text(response)
        return

    if action in ["remove", "delete", "del"]:
        if len(args) < 2:
            await update.message.reply_text(
                "Usage:\n"
                "/watchlist remove AAPL\n"
                "/watchlist remove AAPL MSFT NVDA"
            )
            return

        valid_symbols, invalid_symbols = clean_symbol_list(args[1:])

        if not valid_symbols:
            await update.message.reply_text(
                "No valid symbols were provided.\n\n"
                "Example:\n"
                "/watchlist remove AAPL MSFT NVDA"
            )
            return

        symbols, removed = remove_symbols(valid_symbols)

        response = "✅ Watchlist updated.\n\n"

        if removed:
            response += "Removed:\n"
            response += "\n".join(f"- {symbol}" for symbol in removed)
            response += "\n\n"
        else:
            response += "No matching symbols were found on the watchlist.\n\n"

        if invalid_symbols:
            response += "Skipped invalid symbols:\n"
            response += "\n".join(f"- {symbol}" for symbol in invalid_symbols)
            response += "\n\n"

        response += "Current watchlist:\n"
        response += format_watchlist(symbols)

        await update.message.reply_text(response)
        return

    if action == "clear":
        clear_watchlist()

        await update.message.reply_text(
            "🧹 Watchlist cleared.\n\n"
            "Your watchlist is now empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )
        return

    if action == "reset":
        symbols = reset_watchlist()

        await update.message.reply_text(
            "🔄 Watchlist reset to default symbols.\n\n"
            f"{format_watchlist(symbols)}"
        )
        return

    if action in ["file", "path"]:
        await update.message.reply_text(
            "📁 Watchlist storage file:\n\n"
            f"{get_watchlist_file_path()}"
        )
        return

    await update.message.reply_text(
        "Unknown watchlist command.\n\n"
        "Available commands:\n"
        "/watchlist\n"
        "/watchlist list\n"
        "/watchlist report\n"
        "/watchlist movers\n"
        "/watchlist add AAPL\n"
        "/watchlist remove AAPL\n"
        "/watchlist clear\n"
        "/watchlist reset"
    )