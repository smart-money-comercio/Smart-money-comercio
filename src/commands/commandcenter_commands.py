import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.commandcenter_report import build_commandcenter_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def commandcenter_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "Opening Smart Money AI Command Center...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_commandcenter_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="Smart Money AI Command Center",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money AI Command Center\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def commandcenter(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await commandcenter_command(update, context)
