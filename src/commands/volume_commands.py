import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.volume_intelligence_report import build_volume_intelligence_report


async def volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /volume SYMBOL")
        return

    symbol = context.args[0].upper().replace("$", "").strip()

    loading_message = await update.message.reply_text(
        f"📊 Building {symbol} volume intelligence..."
    )

    try:
        message = await asyncio.to_thread(
            build_volume_intelligence_report,
            symbol,
        )

        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            f"{symbol} Volume Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )