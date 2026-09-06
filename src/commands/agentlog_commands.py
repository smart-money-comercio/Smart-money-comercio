import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.agentlog_report import build_agentlog_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def agentlog_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "Reading Smart Money Daily Agent log...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_agentlog_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="Smart Money Daily Agent Log",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money Daily Agent Log\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def agentlog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await agentlog_command(update, context)
