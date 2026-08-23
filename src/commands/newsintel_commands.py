import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.news_intelligence_report import (
    build_macro_news_report,
    build_news_intelligence_report,
    build_newsmemory_report,
    build_ticker_news_report,
)
from src.utils.telegram_messages import edit_or_reply_long_message


def should_force_news_refresh(args) -> bool:
    args = [str(arg or "").lower().strip() for arg in args or []]

    return any(arg in {"refresh", "live", "force"} for arg in args)


def clean_symbol(value: str) -> str:
    return str(value or "").upper().replace("$", "").strip()


async def newsintel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    force_refresh = should_force_news_refresh(context.args)

    loading_message = await update.message.reply_text(
        "🧠 Building live market news intelligence..."
        if force_refresh
        else "🧠 Building market news intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_news_intelligence_report,
            force_refresh,
            "all",
            "",
            True,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🧠 Market News Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Market News Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def macronews_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    force_refresh = should_force_news_refresh(context.args)

    loading_message = await update.message.reply_text(
        "🌎 Building live macro news intelligence..."
        if force_refresh
        else "🌎 Building macro news intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_macro_news_report,
            force_refresh,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🌎 Macro News Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Macro News Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def tickernews_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /tickernews SYMBOL")
        return

    symbol = clean_symbol(context.args[0])
    force_refresh = should_force_news_refresh(context.args[1:])

    loading_message = await update.message.reply_text(
        f"🧠 Building live {symbol} ticker news intelligence..."
        if force_refresh
        else f"🧠 Building {symbol} ticker news intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_ticker_news_report,
            symbol,
            force_refresh,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title=f"🧠 Ticker News Intelligence: {symbol}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            f"Ticker News Intelligence: {symbol}\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def newsmemory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧠 Loading news memory...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_newsmemory_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🧠 News Memory",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "News Memory\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility aliases.
async def newsintel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await newsintel_command(update, context)


async def macronews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await macronews_command(update, context)


async def tickernews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tickernews_command(update, context)


async def newsmemory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await newsmemory_command(update, context)