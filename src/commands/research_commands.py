import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.intelligence.research_context import build_research_report
from src.utils.telegram_messages import reply_long_message


async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    symbol = str(context.args[0]).strip().upper().replace("$", "") if context.args else ""
    report = await asyncio.to_thread(build_research_report, symbol)
    await reply_long_message(update, report, title="Document Research", parse_mode=None)
