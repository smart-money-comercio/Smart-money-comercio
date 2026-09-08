import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.jobs.source_refresh_job import (
    format_source_refresh_result,
    run_source_refresh,
)
from src.utils.telegram_messages import edit_or_reply_long_message


async def refreshsources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "Refreshing Smart Money AI data sources...",
        parse_mode=None,
    )

    try:
        result = await asyncio.to_thread(run_source_refresh, False)
        message = format_source_refresh_result(result)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="Source Refresh Engine",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Source Refresh Engine\n"
            "Status: FAIL\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def refreshsources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await refreshsources_command(update, context)
