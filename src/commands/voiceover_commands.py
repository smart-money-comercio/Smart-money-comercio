"""Read the latest recorded spoken companion; never refresh or render on request."""

import asyncio
from datetime import datetime, timezone
from io import BytesIO

from src.intelligence.news_editor_store import read_editions
from src.reports.daily_voiceover import checked


def latest():
    records = read_editions(limit=1)
    if not records:
        raise ValueError("No recorded news edition; run /rundailyagent first")
    record = records[0]
    return record, checked(record, datetime.now(timezone.utc))


async def voiceover_command(update, context):
    if not update.message:
        return
    if getattr(context, "args", None):
        await update.message.reply_text("Use /voiceover for the latest spoken script.", parse_mode=None)
        return
    try:
        record, profile = await asyncio.to_thread(latest)
    except (ValueError, OSError, RuntimeError) as exc:
        await update.message.reply_text("Voiceover unavailable: " + str(exc), parse_mode=None)
        return
    quality = profile["quality"]
    caption = (f"Smart Money voiceover · edition {record['id']}\n{quality['words']} words · about {quality['estimated_seconds']:.0f} seconds. "
               "Plain narration for ElevenLabs. The text brief retains the evidence links.")
    script = BytesIO((profile["script"]+"\n").encode("utf-8"))
    await update.message.reply_document(document=script, filename="smart_money_voiceover.txt", caption=caption, parse_mode=None)
