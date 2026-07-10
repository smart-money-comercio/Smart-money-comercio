import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.global_market_report import build_global_market_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def global_market(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🌍 Checking global market shifts and headline risks..."
    )

    try:
        report = await asyncio.to_thread(build_global_market_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report,
            title="🌍 Global Market",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build global market risk report right now.\n\n"
            f"Error: {type(error).__name__}"
        )