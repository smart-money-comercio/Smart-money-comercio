import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.stockanalysis_data_report import build_stockanalysis_data_report
from src.utils.telegram_messages import edit_or_reply_long_message


def should_force_stockanalysis_refresh(args) -> bool:
    args = [str(arg or "").lower().strip() for arg in args or []]

    return any(arg in {"refresh", "live", "force"} for arg in args)


async def stockdata_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage: /stockdata SYMBOL")
        return

    symbol = str(context.args[0] or "").upper().replace("$", "").strip()
    force_refresh = should_force_stockanalysis_refresh(context.args[1:])

    loading_message = await update.message.reply_text(
        f"📊 Fetching StockAnalysis data for {symbol}..."
        if force_refresh
        else f"📊 Loading StockAnalysis data for {symbol}...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_stockanalysis_data_report,
            symbol,
            force_refresh,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title=f"📊 StockAnalysis Data: {symbol}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            f"StockAnalysis Data: {symbol}\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias.
async def stockdata(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await stockdata_command(update, context)