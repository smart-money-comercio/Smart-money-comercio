import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.context_status_report import (
    build_contextstatus_report,
    build_summarypreview_report,
)
from src.utils.telegram_messages import edit_or_reply_long_message


async def contextstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧠 Checking Smart Money context providers...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_contextstatus_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🧠 Context Status",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Context Status\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def summarypreview_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧠 Building Smart Money Summary preview...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_summarypreview_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🧠 Smart Money Summary Preview",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money Summary Preview\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility aliases.
async def contextstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await contextstatus_command(update, context)


async def summarypreview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await summarypreview_command(update, context)