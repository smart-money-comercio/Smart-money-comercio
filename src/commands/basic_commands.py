import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_report import build_daily_report
from src.reports.defense_intelligence_report import build_defense_intelligence_report
from src.reports.morning_brief_intro import ensure_morning_brief_cache_is_fresh
from src.scoring.scoring_engine import get_stock_scores
from src.utils.telegram_messages import edit_or_reply_long_message


START_MESSAGE = """
🚀 Smart Money AI is online.

Main Commands
/report - Latest full report
/brief - Short daily market brief
/top10 - Top ranked Smart Money ideas
/smartmoney - Smart Money command center
/conviction - Highest signal-overlap ideas
/watchlist - Tracked companies

Stock Research
/tradeplan SYMBOL - Smart Money trade plan
/stock SYMBOL - Full stock intelligence
/ticker SYMBOL - Stock intelligence legacy alias
/quote SYMBOL - Fast market quote
/stockdata SYMBOL - StockAnalysis fundamentals and analyst rating
/scorecard SYMBOL - Full Smart Money scorecard
/analyst SYMBOL - Analyst consensus intelligence
/risk SYMBOL - Risk profile
/earnings SYMBOL - Earnings catalyst intelligence
/volume SYMBOL - Volume and money-flow intelligence

Market Intelligence
/headlines - Fast market headline tape
/newsintel - Evolving market-news intelligence
/macronews - Macro-only news intelligence
/tickernews SYMBOL - Ticker-specific news intelligence
/newsmemory - What the news engine has learned
/global - Global macro intelligence
/themes - Active market themes
/calendar - Weekly macro and earnings calendar

Alerts
/alerts - Full alert monitor
/dailyalerts - Daily alert digest
/alertstatus - Latest recorded alert state
/alertsettings - Current alert thresholds
/alertpreset balanced - Show alert preset overrides

Smart Money Summary
/contextstatus - Provider status for the Smart Money Summary
/summarypreview - Preview the current Smart Money Summary

Specialty Intelligence
/defense - Defense and AI warfare intelligence
/congress - Congress trading intelligence
/insiders - Insider trading intelligence
/sec SYMBOL - Latest SEC filings
/filing SYMBOL - AI summary of latest SEC filing
/portfolio - Portfolio intelligence
/growth - Growth ideas
/dividends - Dividend ideas
/undervalued - Undervalued screen

System
/help - Help
/commands - Full command list
/quality - Report quality check
/deploycheck - Deployment health check
/status - Bot status
/version - Version
""".strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        START_MESSAGE,
        parse_mode=None,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📊 Refreshing market data and building daily report...",
        parse_mode=None,
    )

    try:
        # Refresh Morning Brief cache before building the real user-facing report.
        # build_daily_report() stays cache-only so deploycheck/preflight remain fast.
        ensure_morning_brief_cache_is_fresh(max_age_minutes=360)

        report_text = await asyncio.to_thread(build_daily_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report_text,
            title="📊 Daily Report",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build daily report right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🔥 Building Top 10 Smart Money picks...",
        parse_mode=None,
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)

        text = "🔥 TOP 10 SMART MONEY PICKS\n\n"

        for index, stock in enumerate(scores[:10], start=1):
            ticker = stock.get("ticker", "UNKNOWN")
            final_score = stock.get("final_score", stock.get("score", "N/A"))
            category = stock.get("category", "N/A")

            text += f"{index}. {ticker} - {final_score} ({category})\n"

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=text,
            title="🔥 Top 10 Smart Money Picks",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build Top 10 right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📋 Building Smart Money watchlist...",
        parse_mode=None,
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)

        text = "📋 SMART MONEY WATCHLIST\n\n"

        for stock in scores:
            ticker = stock.get("ticker", "UNKNOWN")
            category = stock.get("category", "N/A")
            text += f"- {ticker} | {category}\n"

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=text,
            title="📋 Smart Money Watchlist",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build watchlist right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


def should_force_defense_refresh(args) -> bool:
    cleaned_args = [str(arg or "").lower().strip() for arg in args or []]

    return any(arg in {"refresh", "live", "force"} for arg in cleaned_args)


async def defense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    force_refresh = should_force_defense_refresh(context.args)

    loading_message = await update.message.reply_text(
        "🛡️ Building live defense / AI warfare intelligence..."
        if force_refresh
        else "🛡️ Building defense / AI warfare intelligence...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_defense_intelligence_report,
            force_refresh,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🛡️ Defense / AI Warfare Intelligence",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Defense / AI Warfare Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )