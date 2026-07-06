import asyncio
import os
import time

from telegram import Update
from telegram.ext import ContextTypes

from src.congress.congress_data import get_congress_trades as get_live_congress_trades
from src.congress.congress_scoring import get_congress_score
from src.reports.congress_report import build_congress_report
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

def get_admin_chat_ids() -> set[str]:
    raw_value = (
        os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
        or os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")
    )

    return {
        chat_id.strip()
        for chat_id in raw_value.split(",")
        if chat_id.strip()
    }


def is_admin_update(update: Update) -> bool:
    if not update.effective_chat:
        return False

    admin_chat_ids = get_admin_chat_ids()

    if not admin_chat_ids:
        return False

    return str(update.effective_chat.id) in admin_chat_ids


def summarize_congress_refresh(trades: list[dict], elapsed_seconds: float) -> str:
    tickers = sorted(
        {
            str(trade.get("ticker", "")).upper().replace("$", "")
            for trade in trades
            if trade.get("ticker")
        }
    )

    sources = sorted(
        {
            str(trade.get("source", "Unknown"))
            for trade in trades
            if trade.get("source")
        }
    )

    sample = trades[:5]

    sample_lines = []

    for trade in sample:
        sample_lines.append(
            f"• {trade.get('ticker', 'N/A')} | "
            f"{trade.get('transaction', 'N/A')} | "
            f"{trade.get('politician', 'Unknown')} | "
            f"{trade.get('transaction_date', 'Unknown')}"
        )

    if not sample_lines:
        sample_lines.append("No records loaded.")

    return f"""
✅ Congress Cache Refreshed

Records Loaded: {len(trades)}
Unique Tickers: {len(tickers)}
Sources: {", ".join(sources) if sources else "Unknown"}
Elapsed: {elapsed_seconds:.1f}s

Sample Records
{chr(10).join(sample_lines)}

Next Commands
/congress
/congress NVDA
/congress AAPL
/top10
/report
""".strip()

async def congress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    symbol = None
    refresh_requested = False

    if context.args:
        first_arg = context.args[0].upper().replace("$", "")

        if first_arg in {"REFRESH", "RELOAD", "UPDATE"}:
            refresh_requested = True
        else:
            symbol = first_arg

    if refresh_requested:
        if not is_admin_update(update):
            await update.message.reply_text("Unauthorized: admin only.")
            return

        loading_message = await update.message.reply_text(
            "🔄 Refreshing Congress disclosure cache..."
        )

        try:
            started_at = time.time()

            trades = await asyncio.to_thread(
                get_live_congress_trades,
                True,
            )

            elapsed_seconds = time.time() - started_at

            message = summarize_congress_refresh(
                trades=trades,
                elapsed_seconds=elapsed_seconds,
            )

            await send_split_message(update, message, loading_message)

        except Exception as error:
            await loading_message.edit_text(
                "Unable to refresh Congress cache right now.\n\n"
                f"Error:\n{type(error).__name__}"
            )

        return

    loading_message = await update.message.reply_text(
        "🏛️ Building Congress intelligence report..."
        if not symbol
        else f"🏛️ Building Congress intelligence report for {symbol}..."
    )

    try:
        trades = await asyncio.to_thread(get_live_congress_trades)

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
            score_map[ticker] = await asyncio.to_thread(
                get_congress_score,
                ticker,
            )

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

def summarize_insider_refresh(trades: list[dict], elapsed_seconds: float) -> str:
    tickers = sorted(
        {
            str(trade.get("ticker", "")).upper().replace("$", "")
            for trade in trades
            if trade.get("ticker")
        }
    )

    sources = sorted(
        {
            str(trade.get("signal", "SEC Form 4"))
            for trade in trades
            if trade.get("signal")
        }
    )

    purchases = [
        trade for trade in trades
        if "purchase" in str(trade.get("transaction", "")).lower()
    ]

    sales = [
        trade for trade in trades
        if "sale" in str(trade.get("transaction", "")).lower()
    ]

    sample_lines = []

    for trade in trades[:5]:
        sample_lines.append(
            f"• {trade.get('ticker', 'N/A')} | "
            f"{trade.get('transaction', 'N/A')} | "
            f"{trade.get('insider_name', trade.get('insider', 'Unknown'))} | "
            f"{trade.get('date', trade.get('filing_date', 'Unknown'))}"
        )

    if not sample_lines:
        sample_lines.append("No Form 4 purchase/sale records loaded.")

    return f"""
✅ Insider Cache Refreshed

Records Loaded: {len(trades)}
Unique Tickers: {len(tickers)}
Purchases: {len(purchases)}
Sales: {len(sales)}
Sources: {", ".join(sources) if sources else "SEC Form 4"}
Elapsed: {elapsed_seconds:.1f}s

Sample Records
{chr(10).join(sample_lines)}

Next Commands
/insiders AAPL
/insiders NVDA
/insiders PLTR
/top10
/report
""".strip()

async def insiders(update, context):
    if not update.message:
        return

    refresh_requested = False
    symbol = None

    if context.args:
        first_arg = context.args[0].strip().upper().replace("$", "")

        if first_arg in {"REFRESH", "RELOAD", "UPDATE"}:
            refresh_requested = True
        else:
            symbol = first_arg

    if refresh_requested:
        if not is_admin_update(update):
            await update.message.reply_text("Unauthorized: admin only.")
            return

        loading_message = await update.message.reply_text(
            "🔄 Refreshing SEC Form 4 insider cache..."
        )

        try:
            started_at = time.time()

            trades = await asyncio.to_thread(
                lambda: get_insider_trades(force_refresh=True)
            )

            elapsed_seconds = time.time() - started_at

            message = summarize_insider_refresh(
                trades=trades,
                elapsed_seconds=elapsed_seconds,
            )

            await send_split_message(update, message, loading_message)

        except Exception as error:
            await loading_message.edit_text(
                "Unable to refresh insider cache right now.\n\n"
                f"Error:\n{type(error).__name__}"
            )

        return

    if not symbol:
        await update.message.reply_text(
            "Usage: /insiders SYMBOL\n\n"
            "Example: /insiders AAPL\n"
            "Admin: /insiders refresh"
        )
        return

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