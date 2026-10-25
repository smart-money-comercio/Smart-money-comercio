"""Read-only inspection of built news editions and their source decisions."""

import asyncio
from src.intelligence.news_editor import build_editor_status
from src.intelligence.special_alert_universe import SYMBOL
from src.utils.telegram_messages import reply_long_message


async def editorstatus_command(update, context):
    if update.message:
        text = await asyncio.to_thread(build_editor_status)
        await reply_long_message(update, text, title="News Editor", parse_mode=None)


async def storylog_command(update, context):
    if not update.message:
        return
    args = getattr(context, "args", []) or []
    symbol = str(args[0]).strip().lstrip("$").upper() if args else ""
    if len(args) > 1 or (symbol and not SYMBOL.fullmatch(symbol)):
        await update.message.reply_text("Use /storylog [SYMBOL]", parse_mode=None)
        return
    text = await asyncio.to_thread(build_editor_status, symbol, True)
    await reply_long_message(update, text, title="Story Decision Log", parse_mode=None)
