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
    scores = get_stock_scores()

    growth = [
        stock for stock in scores
        if "Growth" in stock["category"] or "AI" in stock["category"]
    ]

    defense = [
        stock for stock in scores
        if (
            "Defense" in stock["category"]
            or "Cyber" in stock["category"]
            or "Drones" in stock["category"]
            or "Autonomous" in stock["category"]
            or "Space" in stock["category"]
            or "Missile" in stock["category"]
        )
    ]

    etfs = [
        stock for stock in scores
        if "ETF" in stock["category"]
    ]

    dividends_list = [
        stock for stock in scores
        if "Dividend" in stock["category"] or "High Dividend" in stock["category"]
    ]

    growth = sorted(growth, key=lambda x: x["final_score"], reverse=True)
    defense = sorted(defense, key=lambda x: x["final_score"], reverse=True)
    etfs = sorted(etfs, key=lambda x: x["final_score"], reverse=True)
    dividends_list = sorted(dividends_list, key=lambda x: x["final_score"], reverse=True)

    text = "📊 SMART MONEY PORTFOLIO MODEL\n\n"

    text += "🚀 Growth Allocation: 40%\n"
    for stock in growth[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += "\n🛡️ Defense / Cyber / AI Warfare Allocation: 20%\n"
    for stock in defense[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += "\n📈 ETF Allocation: 25%\n"
    for stock in etfs[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += "\n💰 Dividend / High-Income Allocation: 15%\n"
    for stock in dividends_list[:3]:
        text += f"- {stock['ticker']} | Score: {stock['final_score']} | {stock['category']}\n"

    text += (
        "\nNote: This is a research model based on Smart Money AI scoring. "
        "It is not financial advice. Review risk, valuation, dividend safety, and diversification before investing."
    )

    await update.message.reply_text(text)