from telegram import Update
from telegram.ext import ContextTypes

from src.congress.congress_scoring import get_congress_trades
from src.insiders.insider_scoring import get_insider_trades
from src.scoring.scoring_engine import get_stock_scores
from src.scoring.risk_engine import get_risk_profile


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

        risk_profile = get_risk_profile(stock)

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
            f"Signal Overlap: {overlap_count}/3\n"
            f"Risk Level: {risk_profile['risk_level']}\n"
            f"Risk Score: {risk_profile['risk_score']}/100\n\n"
        )

    text += (
        "Note: High conviction means multiple research signals overlap. "
        "Risk level is shown to prevent confusing high conviction with low risk. "
        "This is not financial advice."
    )

    await update.message.reply_text(text)