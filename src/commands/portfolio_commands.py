
import asyncio

from src.reports.portfolio_report import build_portfolio_report
from src.scoring.risk_engine import get_risk_profile
from src.scoring.scoring_engine import get_stock_scores
from telegram import Update
from telegram.ext import ContextTypes

from src.scoring.scoring_engine import get_stock_scores


async def growth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()

    growth_stocks = [
        stock for stock in scores
        if "Growth" in stock["category"] or "AI" in stock["category"]
    ]

    growth_stocks = sorted(
        growth_stocks,
        key=lambda x: x["final_score"],
        reverse=True
    )

    text = "🚀 GROWTH & AI STOCKS\n\n"

    for i, stock in enumerate(growth_stocks[:10], start=1):
        text += (
            f"{i}. {stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Final Score: {stock['final_score']}\n\n"
        )

    text += (
        "Note: Growth stocks can have higher upside but also higher volatility. "
        "This is research, not financial advice."
    )

    await update.message.reply_text(text)


async def dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()

    dividend_stocks = [
        stock for stock in scores
        if "Dividend" in stock["category"] or "High Dividend" in stock["category"]
    ]

    dividend_stocks = sorted(
        dividend_stocks,
        key=lambda x: x["final_score"],
        reverse=True
    )

    text = "💰 DIVIDEND & HIGH-INCOME STOCKS\n\n"

    for i, stock in enumerate(dividend_stocks[:10], start=1):
        text += (
            f"{i}. {stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Final Score: {stock['final_score']}\n\n"
        )

    text += (
        "Note: Dividend stocks may provide income, but yield and safety should be reviewed separately. "
        "This is research, not financial advice."
    )

    await update.message.reply_text(text)


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    symbol = None

    if context.args:
        symbol = context.args[0].upper().replace("$", "")

    loading_message = await update.message.reply_text(
        "📦 Building portfolio role report..."
        if not symbol
        else f"📦 Building portfolio role report for {symbol}..."
    )

    try:
        stocks = await asyncio.to_thread(get_stock_scores)

        risk_profiles = {}

        for stock in stocks:
            ticker = str(stock.get("ticker", "")).upper().replace("$", "")

            if not ticker:
                continue

            risk_profiles[ticker] = get_risk_profile(stock)

        message = build_portfolio_report(
            stocks=stocks,
            risk_profiles=risk_profiles,
            symbol=symbol,
            per_bucket_limit=4,
        )

        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build portfolio role report right now.\n\n"
            f"Error:\n{type(error).__name__}"
        )

    await update.message.reply_text(text)