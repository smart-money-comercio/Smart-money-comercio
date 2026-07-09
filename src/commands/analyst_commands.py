import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.agents.analyst_agent import analyze_ticker, build_analyst_summary
from src.scoring.scoring_engine import get_stock_scores
from src.utils.telegram_messages import edit_or_reply_long_message


def clean_symbol(value: str) -> str:
    return str(value or "").strip().upper().replace("$", "")


async def analyst_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    symbol = None

    if context.args:
        symbol = clean_symbol(context.args[0])

    loading_message = await update.message.reply_text(
        "🧠 Building Smart Money AI analyst summary..."
        if not symbol
        else f"🧠 Building Smart Money AI analyst read for {symbol}...",
        parse_mode=None,
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)

        if symbol:
            message = analyze_ticker(scores=scores, ticker=symbol)
            title = f"🧠 Analyst Read: {symbol}"
        else:
            message = build_analyst_summary(scores=scores, symbol=None, limit=5)
            title = "🧠 Smart Money AI Analyst Summary"

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title=title,
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build analyst summary right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )