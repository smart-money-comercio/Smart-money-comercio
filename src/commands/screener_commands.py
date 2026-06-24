from telegram import Update
from telegram.ext import ContextTypes

from src.market.market_data import format_percent
from src.screeners.undervalued_screener import get_undervalued_ideas


async def undervalued(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 Scanning watchlist for undervalued ideas..."
    )

    try:
        ideas = get_undervalued_ideas(limit=10)
    except Exception as error:
        await update.message.reply_text(
            f"Undervalued screen error:\n{error}"
        )
        return

    if not ideas:
        await update.message.reply_text(
            "No undervalued ideas found based on the current screen."
        )
        return

    text = "💎 UNDERVALUED SMART MONEY IDEAS\n\n"

    for i, idea in enumerate(ideas, start=1):
        reasons = ", ".join(idea["reasons"][:3])

        price_text = f"${idea['price']:.2f}" if idea["price"] else "N/A"
        pe_text = idea["pe_ratio"] if idea["pe_ratio"] else "N/A"
        forward_pe_text = idea["forward_pe"] if idea["forward_pe"] else "N/A"

        text += (
            f"{i}. {idea['ticker']}\n"
            f"Category: {idea['category']}\n"
            f"Price: {price_text}\n"
            f"Smart Money Score: {idea['final_score']}\n"
            f"Undervalued Score: {idea['undervalued_score']}\n"
            f"Risk: {idea['risk_level']} ({idea['risk_score']}/100)\n"
            f"P/E: {pe_text}\n"
            f"Forward P/E: {forward_pe_text}\n"
            f"Dividend Yield: {format_percent(idea['dividend_yield'])}\n"
            f"Why: {reasons}\n\n"
        )

    text += (
        "Note: This screen looks for strong Smart Money scores, reasonable valuation, "
        "earnings support, dividend support, and manageable risk. "
        "This is research, not financial advice."
    )

    await update.message.reply_text(text)