from telegram import Update
from telegram.ext import ContextTypes


HELP_TEXT = """
🤖 Smart Money AI Help

Start here:
/brief - Daily market brief
/stock SYMBOL - Stock snapshot
/top10 - Top 20 Smart Money ideas
/watch - Watchlist
/macro - Global market context
/calendar - Weekly macro and earnings calendar
/quality - Daily report quality check
/versionnotes - What changed in v1.1

Useful examples:
/brief
/stock NVDA
/scorecard PLTR
/volume AMD
/calendar
/quality

For the full command menu:
/commands

Research only. Not financial advice.
""".strip()


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(HELP_TEXT)