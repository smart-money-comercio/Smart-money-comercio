import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.headlines_report import build_headlines_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def headlines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📰 Checking market headline themes..."
    )

    try:
        report = await asyncio.to_thread(build_headlines_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report,
            title="📰 Headlines",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build headline report right now.\n\n"
            f"Error: {type(error).__name__}"
        )