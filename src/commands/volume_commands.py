import asyncio
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from src.scoring.scoring_engine import (
    clean_symbol,
    fetch_volume_signal_from_yahoo,
)
from src.utils.telegram_messages import edit_or_reply_long_message


def format_number(value: Any) -> str:
    try:
        if value is None:
            return "N/A"

        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return "N/A"


def format_ratio(value: Any) -> str:
    try:
        if value is None:
            return "N/A"

        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "N/A"


def build_volume_report(symbol: str, volume_data: dict) -> str:
    label = volume_data.get("volume_label", "Volume Unavailable")
    note = volume_data.get("volume_note", "Volume data was unavailable.")
    latest_volume = format_number(volume_data.get("latest_volume"))
    average_volume = format_number(volume_data.get("average_volume"))
    volume_ratio = format_ratio(volume_data.get("volume_ratio"))

    if label == "Unusual Demand":
        readout = "Market attention is unusually high. This can confirm interest, but it can also mean volatility is elevated."
    elif label == "Active Interest":
        readout = "Market attention is above normal. This supports confirmation, especially if the thesis is already strong."
    elif label == "Normal Volume":
        readout = "Market attention is normal. Volume is not adding a major bullish or bearish signal."
    elif label == "Quiet Volume":
        readout = "Market attention is quiet. This does not kill the thesis, but confirmation is weaker."
    else:
        readout = "Live volume could not be confirmed. Treat volume as neutral for now."

    return f"""
📊 Volume Signal: {symbol}

Volume Signal: {label}
Latest Volume: {latest_volume}
Recent Average: {average_volume}
Volume Ratio: {volume_ratio}

What It Means:
{readout}

Data Note:
{note}

Smart Money Use:
Volume should confirm a thesis, not replace it. Use /analyst {symbol}, /scorecard {symbol}, and /risk {symbol} to compare volume against the full setup.
""".strip()


async def volume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /volume SYMBOL\n\nExample: /volume INTC"
        )
        return

    symbol = clean_symbol(context.args[0])

    if not symbol or symbol == "UNKNOWN":
        await update.message.reply_text(
            "Please provide a valid ticker.\n\nExample: /volume NVDA"
        )
        return

    loading_message = await update.message.reply_text(
        f"📊 Checking live volume for {symbol}..."
    )

    try:
        volume_data = await asyncio.to_thread(
            fetch_volume_signal_from_yahoo,
            symbol,
            True,
        )

        report = build_volume_report(symbol, volume_data)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report,
            title=f"📊 Volume {symbol}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            f"Unable to check live volume for {symbol} right now.\n\n"
            f"Error: {type(error).__name__}"
        )