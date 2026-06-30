import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.insiders.insider_data import get_insider_trades
from src.insiders.insider_scoring import get_insider_score
from src.reports.insider_report import build_insider_report


async def insiders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /insiders SYMBOL\n\nExample: /insiders AAPL"
        )
        return

    symbol = context.args[0].upper().replace("$", "")

    loading_message = await update.message.reply_text(
        f"🧾 Building insider report for {symbol}..."
    )

    try:
        insider_score = await asyncio.to_thread(get_insider_score, symbol)
        trades = await asyncio.to_thread(get_insider_trades)
        message = build_insider_report(
            symbol=symbol,
            insider_score=insider_score,
            all_trades=trades,
            limit=5,
        )
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build insider report right now.\n\n"
            f"Error:\n{type(error).__name__}"
        )