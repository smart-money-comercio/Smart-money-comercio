import re
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


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")


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

    lines = []

    for index, symbol in enumerate(symbols, start=1):
        lines.append(f"{index}. {symbol}")

    return "\n".join(lines)


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
            "/watchlist add AAPL\n"
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

        response = (
            "✅ Watchlist updated.\n\n"
        )

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
        "/watchlist add AAPL\n"
        "/watchlist remove AAPL\n"
        "/watchlist clear\n"
        "/watchlist reset"
    )