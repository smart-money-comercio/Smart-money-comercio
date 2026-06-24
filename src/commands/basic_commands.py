from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_report import build_daily_report
from src.scoring.scoring_engine import get_stock_scores


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "/help - Command list"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_daily_report())


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()
    text = "🔥 TOP 10 SMART MONEY PICKS\n\n"

    for i, stock in enumerate(scores[:10], start=1):
        text += f"{i}. {stock['ticker']} - {stock['final_score']} ({stock['category']})\n"

    await update.message.reply_text(text)


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()
    text = "📋 SMART MONEY WATCHLIST\n\n"

    for stock in scores:
        text += f"- {stock['ticker']} | {stock['category']}\n"

    await update.message.reply_text(text)


async def defense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = sorted(
        get_stock_scores(),
        key=lambda x: x["defense_score"],
        reverse=True
    )

    text = "🛡️ DEFENSE INTELLIGENCE RANKINGS\n\n"

    for i, stock in enumerate(scores[:10], start=1):
        text += (
            f"{i}. {stock['ticker']} - "
            f"Defense Score: {stock['defense_score']} "
            f"({stock['category']})\n"
        )

    await update.message.reply_text(text)