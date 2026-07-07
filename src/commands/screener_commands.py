import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.undervalued_report import build_undervalued_report
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


async def edit_or_send_split_message(update: Update, loading_message, message: str) -> None:
    chunks = split_long_message(message)

    await loading_message.edit_text(chunks[0])

    for chunk in chunks[1:]:
        await update.message.reply_text(chunk)


async def undervalued(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    symbol = None

    if context.args:
        symbol = context.args[0].upper().replace("$", "")

    loading_message = await update.message.reply_text(
        "💎 Building valuation watch report..."
        if not symbol
        else f"💎 Building valuation watch report for {symbol}..."
    )

    try:
        stocks = await asyncio.to_thread(get_stock_scores)

        risk_profiles = {}

        for stock in stocks:
            ticker = str(stock.get("ticker", "")).upper().replace("$", "")

            if not ticker:
                continue

            risk_profiles[ticker] = get_risk_profile(stock)

        message = build_undervalued_report(
            stocks=stocks,
            risk_profiles=risk_profiles,
            symbol=symbol,
            limit=8,
        )

        await edit_or_send_split_message(update, loading_message, message)

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build valuation watch report right now.\n\n"
            f"Error:\n{type(error).__name__}"
        )