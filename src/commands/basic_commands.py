from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_report import build_daily_report
from src.reports.morning_brief_intro import ensure_morning_brief_cache_is_fresh
from src.scoring.scoring_engine import get_stock_scores
from src.utils.telegram_messages import edit_or_reply_long_message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "🚀 Smart Money AI is online.\n\n"
        "Commands:\n"
        "/report - Latest full report\n"
        "/top10 - Top ranked stocks\n"
        "/congress - Congressional trading intelligence\n"
        "/defense - Defense rankings\n"
        "/watchlist - Tracked companies\n"
        "/ticker SYMBOL - Full stock research\n"
        "/quote SYMBOL - Fast market quote\n"
        "/market SYMBOL - Real market data\n"
        "/earnings SYMBOL - Earnings and profitability summary\n"
        "/scorecard SYMBOL - Full Smart Money research scorecard\n"
        "/analyst SYMBOL - Smart Money AI analyst read\n"
        "/risk SYMBOL - Risk profile\n"
        "/smartmoney - Smart money signals\n"
        "/conviction - Highest signal-overlap ideas\n"
        "/growth - Growth and AI stocks\n"
        "/dividends - Dividend and high-income stocks\n"
        "/portfolio - Smart Money portfolio model\n"
        "/undervalued - Screen for undervalued Smart Money ideas\n"
        "/insiders - Insider buying intelligence\n"
        "/sec SYMBOL - Latest SEC filings\n"
        "/filing SYMBOL - AI summary of latest SEC filing\n"
        "/weeklycalendar - Full macro and earnings calendar\n"
        "/global - Global market context\n"
        "/headlines - Market headlines\n"
        "/help - Command list",
        parse_mode=None,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        report_text = build_daily_report()

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
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🔥 Building Top 10 Smart Money picks...",
        parse_mode=None,
    )

    try:
        scores = get_stock_scores()
        text = "🔥 TOP 10 SMART MONEY PICKS\n\n"

        for i, stock in enumerate(scores[:10], start=1):
            ticker = stock.get("ticker", "UNKNOWN")
            final_score = stock.get("final_score", stock.get("score", "N/A"))
            category = stock.get("category", "N/A")

            text += f"{i}. {ticker} - {final_score} ({category})\n"

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
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "📋 Building Smart Money watchlist...",
        parse_mode=None,
    )

    try:
        scores = get_stock_scores()
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
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🛡️ Building defense intelligence rankings...",
        parse_mode=None,
    )

    try:
        scores = sorted(
            get_stock_scores(),
            key=lambda stock: stock.get("defense_score", 0),
            reverse=True,
        )

        text = "🛡️ DEFENSE INTELLIGENCE RANKINGS\n\n"

        for i, stock in enumerate(scores[:10], start=1):
            ticker = stock.get("ticker", "UNKNOWN")
            defense_score = stock.get("defense_score", "N/A")
            category = stock.get("category", "N/A")

            text += (
                f"{i}. {ticker} - "
                f"Defense Score: {defense_score} "
                f"({category})\n"
            )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=text,
            title="🛡️ Defense Intelligence Rankings",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build defense rankings right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )