import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.allocation_report import build_allocation_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def allocation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📊 Building portfolio allocation snapshot...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_allocation_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="📊 Portfolio Allocation Snapshot",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Portfolio Allocation Snapshot\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def allocation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await allocation_command(update, context)
