import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(ROOT_DIR)

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from src.agents.analyst_agent import analyze_stock
from src.congress.congress_scoring import get_congress_trades
from src.insiders.insider_scoring import get_insider_trades
from src.reports.daily_report import build_daily_report
from src.scoring.scoring_engine import get_stock_scores
from src.scoring.stock_lookup import get_stock
from src.congress.congress_real_data import get_real_congress_trades

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Smart Money AI is online.\n\n"
        "Commands:\n"
        "/report - Latest full report\n"
        "/top10 - Top ranked stocks\n"
        "/growth - Growth and AI stocks\n"
        "/dividends - Dividend and high-income stocks\n"
        "/congress - Congressional trading intelligence\n"
        "/defense - Defense rankings\n"
        "/watchlist - Tracked companies\n"
        "/ticker SYMBOL - Stock summary\n"
        "/smartmoney - Smart money signals\n"
        "/conviction - Highest signal-overlap ideas\n"
        "/insiders - Insider buying intelligence\n"
        "/realcongress - Real congressional disclosures\n"
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


async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = get_stock_scores()
    text = "📋 SMART MONEY WATCHLIST\n\n"

    for stock in scores:
        text += f"- {stock['ticker']} | {stock['category']}\n"

    await update.message.reply_text(text)


async def congress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_congress_trades()
    text = "🏛️ CONGRESSIONAL TRADING INTELLIGENCE\n\n"

    for trade in trades:
        text += (
            f"{trade['politician']}\n"
            f"{trade['transaction']}: {trade['ticker']}\n"
            f"Sector: {trade['sector']}\n"
            f"Amount: {trade['amount_range']}\n\n"
        )

    await update.message.reply_text(text)


async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = sorted(
        get_stock_scores(),
        key=lambda x: (
            x.get("congress_score", 0)
            + x.get("insider_score", 0)
        ),
        reverse=True
    )

    text = "🧠 SMART MONEY SIGNALS\n\n"

    for stock in scores[:5]:
        text += (
            f"{stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Congress Score: {stock.get('congress_score', 0)}\n"
            f"Insider Score: {stock.get('insider_score', 0)}\n"
            f"Final Score: {stock['final_score']}\n\n"
        )

    text += (
        "🧠 Insight:\n"
        "Smart Money signals combine congressional activity and insider buying. "
        "These are research inputs, not standalone buy recommendations."
    )

    await update.message.reply_text(text)


async def insiders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_insider_trades()
    text = "🏢 INSIDER BUYING INTELLIGENCE\n\n"

    for trade in trades:
        text += (
            f"{trade['insider']}\n"
            f"{trade['transaction']}: {trade['ticker']}\n"
            f"Sector: {trade['sector']}\n"
            f"Amount: {trade['amount_range']}\n"
            f"Date: {trade['date']}\n\n"
        )

    await update.message.reply_text(text)


async def conviction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scores = sorted(
        get_stock_scores(),
        key=lambda x: (
            x.get("congress_score", 0)
            + x.get("insider_score", 0)
            + x.get("defense_score", 0)
        ),
        reverse=True
    )

    text = "🔥 HIGH CONVICTION IDEAS\n\n"

    for stock in scores[:5]:
        congress_score = stock.get("congress_score", 0)
        insider_score = stock.get("insider_score", 0)
        defense_score = stock.get("defense_score", 0)

        overlap_count = 0
        if congress_score > 0:
            overlap_count += 1
        if insider_score > 0:
            overlap_count += 1
        if defense_score >= 85:
            overlap_count += 1

        text += (
            f"{stock['ticker']}\n"
            f"Category: {stock['category']}\n"
            f"Defense Score: {defense_score}\n"
            f"Congress Score: {congress_score}\n"
            f"Insider Score: {insider_score}\n"
            f"Final Score: {stock['final_score']}\n"
            f"Signal Overlap: {overlap_count}/3\n\n"
        )

    text += (
        "Note: High conviction means multiple research signals overlap. "
        "This is not financial advice."
    )

    await update.message.reply_text(text)

async def realcongress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = get_real_congress_trades(limit=10)

    if not trades:
        await update.message.reply_text("No congressional trades found.")
        return

    text = "🏛️ REAL CONGRESSIONAL DISCLOSURES\n\n"

    for trade in trades:
        text += (
            f"{trade['politician']} ({trade['source']})\n"
            f"{trade['transaction']}: {trade['ticker']}\n"
            f"Amount: {trade['amount_range']}\n"
            f"Disclosure: {trade['disclosure_date']}\n\n"
        )

    await update.message.reply_text(text)

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


async def ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ticker PLTR")
        return

    symbol = context.args[0].upper()
    stock = get_stock(symbol)

    if not stock:
        await update.message.reply_text(f"{symbol} not found in watchlist.")
        return

    analysis = analyze_stock(stock)

    message = f"""
📈 {stock['ticker']}

Category:
{stock['category']}

Smart Score:
{stock['smart_score']}

Defense Score:
{stock['defense_score']}

Congress Score:
{stock.get('congress_score', 0)}

Insider Score:
{stock.get('insider_score', 0)}

Final Score:
{stock['final_score']}

🧠 AI ANALYSIS

{analysis}
"""

    await update.message.reply_text(message)


def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing from .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("top10", top10))
    app.add_handler(CommandHandler("defense", defense))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("ticker", ticker))
    app.add_handler(CommandHandler("congress", congress))
    app.add_handler(CommandHandler("smartmoney", smartmoney))
    app.add_handler(CommandHandler("insiders", insiders))
    app.add_handler(CommandHandler("conviction", conviction))
    app.add_handler(CommandHandler("realcongress", realcongress))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("dividends", dividends))

    print("Smart Money AI bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()