import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.congress.congress_scoring import get_congress_score, get_congress_trades
from src.insiders.insider_data import get_insider_trades
from src.insiders.insider_scoring import get_insider_score
from src.reports.congress_report import build_congress_report
from src.reports.insider_report import build_insider_report
from src.scoring.risk_engine import get_risk_profile
from src.scoring.scoring_engine import get_stock_scores


TELEGRAM_MESSAGE_LIMIT = 3900


def split_long_message(message: str) -> list[str]:
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return [message]

    chunks = []
    current_chunk = ""

    for line in message.splitlines():
        candidate = f"{current_chunk}\n{line}" if current_chunk else line

        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk = candidate

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def send_split_message(update: Update, message: str, loading_message=None) -> None:
    chunks = split_long_message(message)

    if loading_message:
        await loading_message.edit_text(chunks[0])
    else:
        await update.message.reply_text(chunks[0])

    for chunk in chunks[1:]:
        await update.message.reply_text(chunk)


async def congress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    symbol = None

    if context.args:
        symbol = context.args[0].upper().replace("$", "")

    loading_message = await update.message.reply_text(
        "🏛️ Building Congress intelligence report..."
        if not symbol
        else f"🏛️ Building Congress intelligence report for {symbol}..."
    )

    try:
        trades = await asyncio.to_thread(get_congress_trades)

        tickers = sorted(
            {
                str(trade.get("ticker", "")).upper().replace("$", "")
                for trade in trades
                if trade.get("ticker")
            }
        )

        if symbol and symbol not in tickers:
            tickers.append(symbol)

        score_map = {}

        for ticker in tickers:
            score_map[ticker] = await asyncio.to_thread(get_congress_score, ticker)

        message = build_congress_report(
            trades=trades,
            score_map=score_map,
            symbol=symbol,
        )

        await send_split_message(update, message, loading_message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build Congress intelligence report right now.\n\n"
            f"Error:\n{type(error).__name__}"
        )


async def insiders(update, context):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /insiders SYMBOL\n\nExample: /insiders AAPL"
        )
        return

    symbol = context.args[0].upper().replace("$", "")

    loading_message = await update.message.reply_text(
        f"🧾 Building insider report for {symbol}..."
    )

    try:
        insider_score = await asyncio.to_thread(get_insider_score, symbol)
        trades = await asyncio.to_thread(get_insider_trades)

        message = build_insider_report(
            symbol=symbol,
            insider_score=insider_score,
            all_trades=trades,
            limit=5,
        )

        await send_split_message(update, message, loading_message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build insider report right now.\n\n"
            f"Error:\n{type(error).__name__}"
        )


async def smartmoney(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    scores = sorted(
        await asyncio.to_thread(get_stock_scores),
        key=lambda x: (
            x.get("congress_score", 0)
            + x.get("insider_score", 0)
        ),
        reverse=True,
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
        "Smart Money signals combine congressional activity and insider activity. "
        "These are research inputs, not standalone buy recommendations."
    )

    await update.message.reply_text(text)


async def conviction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    scores = sorted(
        await asyncio.to_thread(get_stock_scores),
        key=lambda x: (
            x.get("congress_score", 0)
            + x.get("insider_score", 0)
            + x.get("defense_score", 0)
        ),
        reverse=True,
    )

    text = "🔥 HIGH CONVICTION IDEAS\n\n"

    for stock in scores[:5]:
        congress_score = stock.get("congress_score", 0)
        insider_score = stock.get("insider_score", 0)
        defense_score = stock.get("defense_score", 0)

        risk_profile = get_risk_profile(stock)

        overlap_count = 0

        if congress_score >= 65:
            overlap_count += 1

        if insider_score >= 65:
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