import asyncio
import os
import time
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from src.scoring.scoring_engine import (
    clean_symbol,
    fetch_volume_signal_from_yahoo,
)
from src.scoring.watchlist import WATCHLIST
from src.utils.telegram_messages import edit_or_reply_long_message


DEFAULT_REFRESH_LIMIT = 40
MAX_REFRESH_LIMIT = 120


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


def parse_refresh_limit(args: list[str]) -> int:
    if len(args) < 2:
        return DEFAULT_REFRESH_LIMIT

    try:
        requested = int(args[1])
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_LIMIT

    return max(1, min(MAX_REFRESH_LIMIT, requested))


def get_watchlist_symbols() -> list[str]:
    symbols = []
    seen = set()

    for item in WATCHLIST:
        if not isinstance(item, dict):
            continue

        symbol = clean_symbol(item.get("ticker") or item.get("symbol"))

        if not symbol or symbol == "UNKNOWN" or symbol in seen:
            continue

        seen.add(symbol)
        symbols.append(symbol)

    return symbols


def build_volume_report(symbol: str, volume_data: dict) -> str:
    label = volume_data.get("volume_label", "Volume Unavailable")
    note = volume_data.get("volume_note", "Volume data was unavailable.")
    latest_volume = format_number(volume_data.get("latest_volume"))
    average_volume = format_number(volume_data.get("average_volume"))
    volume_ratio = format_ratio(volume_data.get("volume_ratio"))

    if label == "Unusual Demand":
        readout = (
            "Market attention is unusually high. This can confirm interest, "
            "but it can also mean volatility is elevated."
        )
    elif label == "Active Interest":
        readout = (
            "Market attention is above normal. This supports confirmation, "
            "especially if the thesis is already strong."
        )
    elif label == "Normal Volume":
        readout = (
            "Market attention is normal. Volume is not adding a major bullish "
            "or bearish signal."
        )
    elif label == "Quiet Volume":
        readout = (
            "Market attention is quiet. This does not kill the thesis, "
            "but confirmation is weaker."
        )
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


def refresh_volume_cache(limit: int = DEFAULT_REFRESH_LIMIT) -> dict:
    symbols = get_watchlist_symbols()[:limit]

    started_at = time.time()
    results = []
    label_counts: dict[str, int] = {}

    for symbol in symbols:
        try:
            volume_data = fetch_volume_signal_from_yahoo(
                symbol,
                force_live=True,
                bypass_cache=True,
            )
        except Exception as error:
            volume_data = {
                "ticker": symbol,
                "volume_label": "Volume Unavailable",
                "volume_note": f"Refresh failed: {type(error).__name__}",
                "volume_ratio": None,
            }

        label = str(volume_data.get("volume_label", "Volume Unavailable"))
        label_counts[label] = label_counts.get(label, 0) + 1

        results.append(
            {
                "ticker": symbol,
                "label": label,
                "ratio": volume_data.get("volume_ratio"),
            }
        )

    elapsed = round(time.time() - started_at, 1)

    return {
        "requested": limit,
        "processed": len(results),
        "elapsed": elapsed,
        "label_counts": label_counts,
        "results": results,
    }


def build_volume_refresh_report(summary: dict) -> str:
    processed = summary.get("processed", 0)
    requested = summary.get("requested", 0)
    elapsed = summary.get("elapsed", 0)
    label_counts = summary.get("label_counts", {})
    results = summary.get("results", [])

    counts_text = "\n".join(
        f"- {label}: {count}"
        for label, count in sorted(label_counts.items())
    )

    if not counts_text:
        counts_text = "- No volume data refreshed."

    top_results = results[:20]
    sample_text = "\n".join(
        f"- {item['ticker']}: {item['label']} ({format_ratio(item.get('ratio'))})"
        for item in top_results
    )

    if not sample_text:
        sample_text = "- No sample results available."

    return f"""
📊 Volume Cache Refresh Complete

Processed: {processed}/{requested}
Elapsed: {elapsed}s

Signal Counts:
{counts_text}

Sample:
{sample_text}

Notes:
- This is admin-only.
- Normal commands still avoid live Yahoo volume lookups.
- Use /volume SYMBOL for a single live check.
""".strip()


async def volume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/volume SYMBOL\n"
            "/volume refresh\n\n"
            "Examples:\n"
            "/volume INTC\n"
            "/volume refresh"
        )
        return

    first_arg = str(context.args[0]).strip().lower()

    if first_arg in {"refresh", "reload", "update"}:
        if not is_admin_update(update):
            await update.message.reply_text("Unauthorized: admin only.")
            return

        limit = parse_refresh_limit(context.args)

        loading_message = await update.message.reply_text(
            f"📊 Refreshing live volume cache for up to {limit} watchlist names..."
        )

        try:
            summary = await asyncio.to_thread(refresh_volume_cache, limit)
            report = build_volume_refresh_report(summary)

            await edit_or_reply_long_message(
                update=update,
                loading_message=loading_message,
                text=report,
                title="📊 Volume Refresh",
                parse_mode=None,
            )

        except Exception as error:
            await loading_message.edit_text(
                "Unable to refresh volume cache right now.\n\n"
                f"Error: {type(error).__name__}"
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