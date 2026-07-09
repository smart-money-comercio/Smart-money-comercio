import asyncio
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.portfolio_report import build_portfolio_report
from src.scoring.risk_engine import get_risk_profile
from src.scoring.scoring_engine import get_stock_scores
from src.utils.telegram_messages import edit_or_reply_long_message


def safe_score(stock: dict[str, Any]) -> float:
    try:
        return float(stock.get("final_score") or stock.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def clean_symbol(stock: dict[str, Any]) -> str:
    return str(stock.get("ticker") or stock.get("symbol") or "UNKNOWN").upper().replace("$", "")


def clean_category(stock: dict[str, Any]) -> str:
    return str(stock.get("category") or "Uncategorized")


async def growth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🚀 Building Growth & AI stock list...",
        parse_mode=None,
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)

        growth_stocks = [
            stock for stock in scores
            if "Growth" in clean_category(stock) or "AI" in clean_category(stock)
        ]

        growth_stocks = sorted(
            growth_stocks,
            key=safe_score,
            reverse=True,
        )

        if not growth_stocks:
            await loading_message.edit_text(
                "No Growth or AI stocks found in the current scoring list.",
                parse_mode=None,
            )
            return

        text = "🚀 GROWTH & AI STOCKS\n\n"

        for index, stock in enumerate(growth_stocks[:10], start=1):
            text += (
                f"{index}. {clean_symbol(stock)}\n"
                f"Category: {clean_category(stock)}\n"
                f"Final Score: {safe_score(stock):.0f}\n\n"
            )

        text += (
            "Note: Growth stocks can have higher upside but also higher volatility. "
            "This is research, not financial advice."
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=text,
            title="🚀 Growth & AI Stocks",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build Growth & AI stock list right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "💰 Building Dividend & High-Income stock list...",
        parse_mode=None,
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)

        dividend_stocks = [
            stock for stock in scores
            if "Dividend" in clean_category(stock)
            or "High Dividend" in clean_category(stock)
            or "Income" in clean_category(stock)
        ]

        dividend_stocks = sorted(
            dividend_stocks,
            key=safe_score,
            reverse=True,
        )

        if not dividend_stocks:
            await loading_message.edit_text(
                "No Dividend or High-Income stocks found in the current scoring list.",
                parse_mode=None,
            )
            return

        text = "💰 DIVIDEND & HIGH-INCOME STOCKS\n\n"

        for index, stock in enumerate(dividend_stocks[:10], start=1):
            text += (
                f"{index}. {clean_symbol(stock)}\n"
                f"Category: {clean_category(stock)}\n"
                f"Final Score: {safe_score(stock):.0f}\n\n"
            )

        text += (
            "Note: Dividend stocks may provide income, but yield and safety should be reviewed separately. "
            "This is research, not financial advice."
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=text,
            title="💰 Dividend & High-Income Stocks",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build Dividend & High-Income stock list right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    symbol = None

    if context.args:
        symbol = context.args[0].upper().replace("$", "")

    loading_message = await update.message.reply_text(
        "📦 Building portfolio role report..."
        if not symbol
        else f"📦 Building portfolio role report for {symbol}...",
        parse_mode=None,
    )

    try:
        stocks = await asyncio.to_thread(get_stock_scores)

        risk_profiles = {}

        for stock in stocks:
            ticker = clean_symbol(stock)

            if not ticker or ticker == "UNKNOWN":
                continue

            risk_profiles[ticker] = get_risk_profile(stock)

        message = build_portfolio_report(
            stocks=stocks,
            risk_profiles=risk_profiles,
            symbol=symbol,
            per_bucket_limit=2,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="📦 Portfolio Report",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build portfolio role report right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )