"""Cached company follow-up and the detailed research edition."""

import asyncio

from src.intelligence.company_catalyst_context import build_company_catalyst_report
from src.intelligence.special_alert_universe import SYMBOL
from src.reports.daily_report import build_research_report
from src.reports.morning_brief_intro import ensure_morning_brief_cache_is_fresh
from src.utils.telegram_messages import reply_long_message


async def catalysts_command(update, context) -> None:
    if not update.message:
        return
    args = getattr(context, "args", []) or []
    symbol = str(args[0]).strip().lstrip("$").upper() if args else ""
    if len(args) > 1 or (symbol and not SYMBOL.fullmatch(symbol)):
        await update.message.reply_text("Use /catalysts [SYMBOL]", parse_mode=None)
        return
    text = await asyncio.to_thread(build_company_catalyst_report, symbol)
    await reply_long_message(update, text, title="Company Catalyst Brief", parse_mode=None)


async def fullreport_command(update, context) -> None:
    if not update.message:
        return
    await asyncio.to_thread(ensure_morning_brief_cache_is_fresh)
    text = await asyncio.to_thread(build_research_report)
    from src.intelligence import news_editor_store, subscriber_brief
    from sqlite3 import Error as StorageError
    try:
        from datetime import datetime, timezone
        confirmed = await asyncio.to_thread(news_editor_store.confirmed_watchlist_ids, datetime.now(timezone.utc))
        editions = await asyncio.to_thread(news_editor_store.read_editions, news_editor_store.MAX_EDITIONS)
    except (OSError, StorageError):
        editions, confirmed = [], []
    text = subscriber_brief.full_report(text, editions, confirmed)
    await reply_long_message(update, text, title="Detailed Research Report", parse_mode=None)
