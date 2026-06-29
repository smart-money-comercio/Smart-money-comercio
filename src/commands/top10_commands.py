import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.top10_report import build_top10_report
from src.scoring.scoring_engine import get_stock_scores


MAX_TOP_RESULTS = 10


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🏆 Building Smart Money AI Top 10..."
    )

    try:
        stocks = await asyncio.to_thread(get_stock_scores)
        message = build_top10_report(stocks, limit=MAX_TOP_RESULTS)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build Smart Money AI Top 10 right now.\n\n"
            f"Error:\n{type(error).__name__}"
        )