import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.filing_intelligence_report import build_filing_intelligence_report
from src.utils.telegram_messages import edit_or_reply_long_message


def clean_symbol(value: str) -> str:
    return str(value or "").strip().upper().replace("$", "")


async def sec_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /sec SYMBOL", parse_mode=None)
        return

    symbol = clean_symbol(context.args[0])

    loading_message = await update.message.reply_text(
        f"📄 Building {symbol} SEC disclosure intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_filing_intelligence_report,
            symbol,
            "sec",
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title=f"📄 SEC Disclosure Intelligence: {symbol}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            f"{symbol} SEC Disclosure Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def filing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /filing SYMBOL", parse_mode=None)
        return

    symbol = clean_symbol(context.args[0])

    loading_message = await update.message.reply_text(
        f"📄 Building {symbol} filing portfolio-impact read...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_filing_intelligence_report,
            symbol,
            "filing",
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title=f"📄 Filing Intelligence: {symbol}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            f"{symbol} Filing Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility aliases in case register_commands.py imports these names.
async def sec(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await sec_command(update, context)


async def filing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await filing_command(update, context)