import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.portfolio_intelligence_report import build_portfolio_intelligence_report
from src.utils.telegram_messages import edit_or_reply_long_message


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧭 Building portfolio intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_portfolio_intelligence_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🧭 Portfolio Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Portfolio Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias in case register_commands.py imports portfolio.
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await portfolio_command(update, context)