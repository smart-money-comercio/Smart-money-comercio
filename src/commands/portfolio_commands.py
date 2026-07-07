import asyncio

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from src.reports.portfolio_report import build_portfolio_report
from src.scoring.risk_engine import get_risk_profile
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


async def edit_or_send_split_message(update: Update, loading_message, message: str) -> None:
    chunks = split_long_message(message)

    await edit_or_send_split_message(update, loading_message, message)

    for chunk in chunks[1:]:
        await update.message.reply_text(chunk)

TELEGRAM_MESSAGE_LIMIT = 3000


def split_long_message(message: str) -> list[str]:
    chunks = []
    current_chunk = ""

    for line in message.splitlines():
        # Hard-split any very long single line.
        while len(line) > TELEGRAM_MESSAGE_LIMIT:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            chunks.append(line[:TELEGRAM_MESSAGE_LIMIT])
            line = line[TELEGRAM_MESSAGE_LIMIT:]

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


async def send_portfolio_report(update: Update, loading_message, message: str) -> None:
    chunks = split_long_message(message)

    # Keep the edit very short to avoid Telegram edit_text limits.
    try:
        await loading_message.edit_text(
            "✅ Portfolio role report ready. Sending below...",
            parse_mode=None,
        )
    except BadRequest:
        pass

    for index, chunk in enumerate(chunks, start=1):
        header = f"📦 Portfolio Report Part {index}/{len(chunks)}\n\n"

        await update.message.reply_text(
            header + chunk,
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
            ticker = str(stock.get("ticker", "")).upper().replace("$", "")

            if not ticker:
                continue

            risk_profiles[ticker] = get_risk_profile(stock)

        message = build_portfolio_report(
            stocks=stocks,
            risk_profiles=risk_profiles,
            symbol=symbol,
            per_bucket_limit=2,
        )

        await send_portfolio_report(update, loading_message, message)

    except Exception as error:
        try:
            await loading_message.edit_text(
                "Unable to build portfolio role report right now.\n\n"
                f"Error:\n{type(error).__name__}",
                parse_mode=None,
            )
        except BadRequest:
            await update.message.reply_text(
                "Unable to build portfolio role report right now.\n\n"
                f"Error:\n{type(error).__name__}",
                parse_mode=None,
            )

    await update.message.reply_text(text)