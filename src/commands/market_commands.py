import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.agents.analyst_agent import analyze_stock
from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.reports.ticker_report import build_ticker_report
from src.market.earnings_data import get_earnings_data, summarize_earnings
from src.reports.earnings_intelligence_report import build_earnings_intelligence_report
from src.market.market_data import get_market_data, format_number, format_percent
from src.reports.market_report import build_market_report
from src.reports.stock_intelligence_report import build_stock_intelligence_report
from src.reports.quote_report import build_quote_report
from src.reports.earnings_report import build_earnings_report
from src.reports.risk_intelligence_report import build_risk_intelligence_report
from src.reports.risk_report import build_risk_report
from src.reports.scorecard import (
    build_scorecard,
    clean_symbol,
    find_score_for_symbol,
    get_quote_for_symbol,
    normalize_scores,
)
from src.scoring.risk_engine import get_risk_profile
from src.scoring.scoring_engine import get_stock_scores
from src.scoring.stock_lookup import get_stock

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /quote SYMBOL\n\nExample: /quote NVDA")
        return

    symbol = context.args[0].upper().replace("$", "")
    data = get_market_data(symbol)

    if not data["found"]:
        await update.message.reply_text(
            f"Quote not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    message = build_quote_report(symbol, data)
    await update.message.reply_text(message)


async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /market SYMBOL\n\nExample: /market NVDA")
        return

    symbol = context.args[0].upper().replace("$", "")
    data = get_market_data(symbol)

    if not data["found"]:
        await update.message.reply_text(
            f"Market data not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    message = build_market_report(symbol, data)
    await update.message.reply_text(message)


async def earnings(update, context):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /earnings SYMBOL")
        return

    symbol = context.args[0].upper().replace("$", "").strip()

    loading_message = await update.message.reply_text(
        f"🗓️ Building {symbol} earnings catalyst read..."
    )

    try:
        message = await asyncio.to_thread(
            build_earnings_intelligence_report,
            symbol,
        )

        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            f"{symbol} Earnings / Catalyst Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )


async def ticker(update, context):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /stock SYMBOL")
        return

    symbol = context.args[0].upper().replace("$", "").strip()

    loading_message = await update.message.reply_text(
        f"📈 Building {symbol} intelligence read..."
    )

    try:
        message = await asyncio.to_thread(build_stock_intelligence_report, symbol)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            f"{symbol} Stock Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )

async def scorecard(update, context):
    if not context.args:
        await update.message.reply_text(
            "Usage: /scorecard SYMBOL\n\nExample: /scorecard NVDA"
        )
        return

    symbol = clean_symbol(context.args[0])

    await update.message.reply_text(
        f"Building Smart Money AI scorecard for {symbol}..."
    )

    try:
        raw_scores = await asyncio.to_thread(get_stock_scores)
        scores = normalize_scores(raw_scores)
        score_item = find_score_for_symbol(scores, symbol)
    except Exception:
        score_item = None

    try:
        quotes = await asyncio.to_thread(fetch_quotes_for_symbols, [symbol])
        quote_data = get_quote_for_symbol(quotes, symbol)
    except Exception:
        quote_data = None

    message = build_scorecard(symbol, score_item, quote_data)
    await update.message.reply_text(message)

async def risk(update, context):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /risk SYMBOL")
        return

    symbol = context.args[0].upper().replace("$", "").strip()

    loading_message = await update.message.reply_text(
        f"⚠️ Building {symbol} risk read..."
    )

    try:
        message = await asyncio.to_thread(
            build_risk_intelligence_report,
            symbol,
        )
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            f"{symbol} Risk Intelligence\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )

    message = build_risk_report(
        symbol=symbol,
        stock=stock,
        risk_profile=risk_profile,
        market_data=market_data,
    )

    await update.message.reply_text(message)
