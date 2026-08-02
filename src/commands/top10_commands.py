import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.top10_report import build_top10_report
from src.scoring.scoring_engine import get_stock_scores
from src.utils.telegram_messages import edit_or_reply_long_message


MAX_TOP_RESULTS = 20


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🏆 Building Top 20 Smart Money ideas..."
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)
        report = await asyncio.to_thread(
            build_top10_report,
            scores,
            MAX_TOP_RESULTS,
        )

        await edit_or_reply_long_message(loading_message, report)

    except Exception as error:
        await loading_message.edit_text(
            "Top 20 Smart Money Ideas\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )