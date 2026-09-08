import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.sourcehealth_report import build_sourcehealth_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def sourcehealth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "Checking data source health...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_sourcehealth_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="Data Source Health Dashboard",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Data Source Health Dashboard\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def sourcehealth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await sourcehealth_command(update, context)
