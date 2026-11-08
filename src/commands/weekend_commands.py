"""On-demand weekly research; replies only to the requesting chat."""

import asyncio
from datetime import datetime, timezone
from io import BytesIO
import json

from src.intelligence import weekend_store
from src.reports import weekend_outlook
from src.utils.telegram_messages import split_long_message


def latest(*,publishable=False):
    record=weekend_store.latest()
    if record is None:raise ValueError("No recorded Weekend Outlook; run /weekend on Saturday or Sunday, New York time")
    return weekend_outlook.checked(record,datetime.now(timezone.utc),require_publishable=publishable)


async def weekend_command(update,context):
    if not update.message:return
    args=getattr(context,"args",[]) or []
    if args not in ([],["refresh"]):
        await update.message.reply_text("Use /weekend [refresh] on Saturday or Sunday, New York time.",parse_mode=None);return
    await update.message.reply_text("Building the Weekend Outlook from weekly prices and current cached publisher leads. Original article reads are bounded; source cooldowns remain in effect.",parse_mode=None)
    try:
        record=await asyncio.to_thread(weekend_outlook.build,force=bool(args))
        text=f"Weekend Outlook: {record['quality']['status']} · edition {record['id']}\n\n"+record["report_text"]
        for chunk in split_long_message(text):await update.message.reply_text(chunk,parse_mode=None)
        await update.message.reply_text("/weekendstatus · /weekendvoiceover · /weekendexport\nIf original leads are stale or missing, run /rundailyagent, then /weekend refresh.",parse_mode=None)
    except (ValueError,OSError,RuntimeError) as error:
        await update.message.reply_text("Weekend Outlook unavailable: "+str(error),parse_mode=None)


async def weekendstatus_command(update,context):
    if not update.message:return
    if getattr(context,"args",None):
        await update.message.reply_text("Use /weekendstatus for the latest recorded review.",parse_mode=None);return
    try:
        record=await asyncio.to_thread(latest)
        text=await asyncio.to_thread(weekend_outlook.status,record)
        for chunk in split_long_message(text):await update.message.reply_text(chunk,parse_mode=None)
    except (ValueError,OSError,RuntimeError) as error:
        await update.message.reply_text("Weekend review unavailable: "+str(error),parse_mode=None)


async def document(update,context,*,export):
    if not update.message:return
    command="/weekendexport" if export else "/weekendvoiceover"
    if getattr(context,"args",None):
        await update.message.reply_text("Use "+command+" for the latest current PASS edition.",parse_mode=None);return
    try:
        record=await asyncio.to_thread(latest,publishable=True)
        if export:
            packet=await asyncio.to_thread(weekend_outlook.episode,record,datetime.now(timezone.utc))
            payload=json.dumps(packet,ensure_ascii=False,indent=2)+"\n"
            filename="weekend_outlook_"+packet["date"]+".json"
            caption="Weekend Outlook JSON · draft review required. Review adapter support for edition_type weekend_outlook before media production."
        else:
            payload=record["voiceover"]["script"]+"\n";filename="weekend_voiceover.txt"
            quality=record["voiceover"]["quality"]
            caption=f"Weekend Outlook · edition {record['id']}\n{quality['words']} words · about {quality['estimated_seconds']:.0f} seconds at 160 words/minute. Plain narration for review."
        await update.message.reply_document(document=BytesIO(payload.encode()),filename=filename,caption=caption,parse_mode=None)
    except (ValueError,OSError,RuntimeError) as error:
        await update.message.reply_text("Weekend document unavailable: "+str(error),parse_mode=None)


async def weekendvoiceover_command(update,context):
    await document(update,context,export=False)


async def weekendexport_command(update,context):
    await document(update,context,export=True)
