import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.tradeplans_report import build_tradeplans_report
from src.utils.telegram_messages import edit_or_reply_long_message


def parse_limit(args) -> int:
    if not args:
        return 10

    try:
        return int(args[0])
    except Exception:
        return 10


async def tradeplans_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    limit = parse_limit(context.args)

    loading_message = await update.message.reply_text(
        f"🎯 Building top {limit} Smart Money trade plans...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_tradeplans_report, limit)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🎯 Top Trade Plans",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money Top Trade Plans\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def tradeplans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tradeplans_command(update, context)