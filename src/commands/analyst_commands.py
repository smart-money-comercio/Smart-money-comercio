import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.agents.analyst_agent import build_analyst_summary
from src.reports.analyst_intelligence_report import build_analyst_intelligence_report
from src.scoring.scoring_engine import get_stock_scores
from src.utils.telegram_messages import edit_or_reply_long_message


def clean_symbol(value: str) -> str:
    return str(value or "").strip().upper().replace("$", "")


async def analyst_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    symbol = clean_symbol(context.args[0]) if context.args else ""

    loading_message = await update.message.reply_text(
        "🧠 Building Smart Money AI analyst summary..."
        if not symbol
        else f"🧠 Building {symbol} analyst consensus intelligence...",
        parse_mode=None,
    )

    try:
        if symbol:
            message = await asyncio.to_thread(
                build_analyst_intelligence_report,
                symbol,
            )
            title = f"🧠 Analyst Consensus Intelligence: {symbol}"

        else:
            scores = await asyncio.to_thread(get_stock_scores)
            message = await asyncio.to_thread(
                build_analyst_summary,
                scores,
                None,
                5,
            )
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
            f"Error:\n{type(error).__name__}: {error}",
            parse_mode=None,
        )