import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.agents.analyst_agent import analyze_stock
from src.commands.watchlist_commands import fetch_quotes_for_symbols
from src.reports.ticker_report import build_ticker_report
from src.market.earnings_data import get_earnings_data, summarize_earnings
from src.market.market_data import get_market_data, format_number, format_percent
from src.reports.market_report import build_market_report
from src.reports.quote_report import build_quote_report
from src.reports.earnings_report import build_earnings_report
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


async def earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /earnings SYMBOL\n\nExample: /earnings NVDA")
        return

    symbol = context.args[0].upper().replace("$", "")

    await update.message.reply_text(
        f"Building Smart Money AI earnings snapshot for {symbol}..."
    )

    data = get_earnings_data(symbol)

    if not data["found"]:
        await update.message.reply_text(
            f"Earnings data not found for {symbol}.\n"
            f"Error: {data.get('error', 'Unknown error')}"
        )
        return

    try:
        ai_summary = summarize_earnings(data)
    except Exception as error:
        ai_summary = f"AI summary unavailable: {error}"

    message = build_earnings_report(
        symbol=symbol,
        data=data,
        ai_summary=ai_summary,
    )

    await update.message.reply_text(message)


async def ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ticker SYMBOL\n\nExample: /ticker NVDA")
        return

    symbol = context.args[0].upper().replace("$", "")

    await update.message.reply_text(
        f"Building Smart Money AI ticker snapshot for {symbol}..."
    )

    stock = get_stock(symbol)

    try:
        market_data = get_market_data(symbol)
    except Exception:
        market_data = {"found": False, "error": "Market data unavailable"}

    if not stock and not market_data.get("found"):
        await update.message.reply_text(
            f"{symbol} was not found in the watchlist and market data is unavailable."
        )
        return

    if stock:
        try:
            risk_profile = get_risk_profile(stock)
        except Exception:
            risk_profile = None

        try:
            analysis = analyze_stock(stock)
        except Exception as error:
            analysis = f"AI analysis unavailable: {error}"
    else:
        risk_profile = None
        analysis = (
            f"{symbol} is not currently in the Smart Money AI watchlist. "
            f"Market data is available, but watchlist score, final score, and custom AI thesis are unavailable. "
            f"Add {symbol} to the watchlist if you want full scoring."
        )

    message = build_ticker_report(
        symbol=symbol,
        stock=stock,
        risk_profile=risk_profile,
        market_data=market_data,
        analysis=analysis,
    )

    await update.message.reply_text(message)


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

async def risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /risk SYMBOL\n\nExample: /risk NVDA")
        return

    symbol = context.args[0].upper().replace("$", "")

    await update.message.reply_text(
        f"Building Smart Money AI risk report for {symbol}..."
    )

    stock = get_stock(symbol)
    market_data = get_market_data(symbol)

    if stock:
        try:
            risk_profile = get_risk_profile(stock)
        except Exception:
            risk_profile = None
    else:
        risk_profile = None

    if not stock and not market_data.get("found"):
        await update.message.reply_text(
            f"Risk data not found for {symbol}.\n"
            f"Error: {market_data.get('error', 'Unknown error')}"
        )
        return

    message = build_risk_report(
        symbol=symbol,
        stock=stock,
        risk_profile=risk_profile,
        market_data=market_data,
    )

    await update.message.reply_text(message)
