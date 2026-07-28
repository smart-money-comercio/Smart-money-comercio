import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_report import (
    build_market_tone,
    collect_watchlist_movers,
    fetch_watchlist_quotes,
    load_global_context,
)
from src.intelligence.market_memory import build_what_changed_today
from src.intelligence.theme_scoring import build_theme_scorecard


def build_themes_report() -> str:
    global_context = load_global_context()

    watchlist_symbols, watchlist_quotes = fetch_watchlist_quotes(global_context)
    movers = collect_watchlist_movers(watchlist_symbols, watchlist_quotes)
    market_tone = build_market_tone(movers)

    what_changed_today = build_what_changed_today(
        context=global_context,
        top_scores=global_context.get("scores", []),
        movers=movers,
        market_tone=market_tone,
        watchlist_symbols=watchlist_symbols,
        record=False,
    )

    theme_read = build_theme_scorecard(
        context=global_context,
        market_tone=market_tone,
        what_changed_today=what_changed_today,
    )

    themes = global_context.get("headline_themes") or []
    theme_text = ", ".join(themes[:5]) if themes else "No active themes detected."

    return f"""
Active Market Themes

Current Themes:
{theme_text}

Theme Read
{theme_read}

What Changed
{what_changed_today}

Market Tone
{market_tone}

Use:
/brief
/stock SYMBOL
/calendar
/quality
""".strip()


async def themes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧠 Reading active market themes..."
    )

    try:
        message = await asyncio.to_thread(build_themes_report)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Active Market Themes\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}"
        )