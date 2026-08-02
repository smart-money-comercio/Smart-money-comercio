import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.top10_report import build_top10_report
from src.scoring.scoring_engine import get_stock_scores


MAX_TOP_RESULTS = 20
MAX_TELEGRAM_CHARS = 3900


def split_telegram_text(text: str, max_chars: int = MAX_TELEGRAM_CHARS) -> list[str]:
    text = str(text or "").strip()

    if not text:
        return ["Top 20 Smart Money Ideas\nStatus: empty report."]

    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""

    blocks = text.split("\n\n")

    for block in blocks:
        block = block.strip()

        if not block:
            continue

        candidate = f"{current}\n\n{block}".strip() if current else block

        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) <= max_chars:
            current = block
            continue

        # Last-resort split for an unusually long block.
        for start in range(0, len(block), max_chars):
            chunks.append(block[start:start + max_chars])

    if current:
        chunks.append(current)

    return chunks


async def send_chunked_report(update: Update, loading_message, report: str) -> None:
    chunks = split_telegram_text(report)

    try:
        await loading_message.edit_text(chunks[0])
    except Exception:
        if update.message:
            await update.message.reply_text(chunks[0])

    if not update.message:
        return

    for chunk in chunks[1:]:
        await update.message.reply_text(chunk)


async def top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🏆 Building Top 20 Smart Money ideas..."
    )

    try:
        scores = await asyncio.to_thread(get_stock_scores)
        report = await asyncio.to_thread(
            build_top10_report,
            scores,
            MAX_TOP_RESULTS,
        )

        await send_chunked_report(update, loading_message, report)

    except Exception as error:
        await loading_message.edit_text(
            "Top 20 Smart Money Ideas\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )