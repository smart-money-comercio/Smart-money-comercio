import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.watchdog_report import build_watchdog_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def watchdog_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "Checking Daily Agent Watchdog...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_watchdog_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="Daily Agent Watchdog",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Daily Agent Watchdog\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def watchdog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await watchdog_command(update, context)
