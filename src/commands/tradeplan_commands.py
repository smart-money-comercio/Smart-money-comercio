import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.tradeplan_report import build_tradeplan_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def tradeplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    symbol = ""

    if context.args:
        symbol = str(context.args[0] or "").upper().strip().replace("$", "")

    if not symbol:
        await update.message.reply_text(
            "🎯 Smart Money Trade Plan\n\n"
            "Usage:\n"
            "/tradeplan SYMBOL\n\n"
            "Examples:\n"
            "/tradeplan NVDA\n"
            "/tradeplan PLTR\n"
            "/tradeplan AVAV\n\n"
            "Research only. Not financial advice.",
            parse_mode=None,
        )
        return

    loading_message = await update.message.reply_text(
        f"🎯 Building Smart Money Trade Plan for {symbol}...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_tradeplan_report, symbol)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title=f"🎯 Trade Plan: {symbol}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Smart Money Trade Plan\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def tradeplan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tradeplan_command(update, context)