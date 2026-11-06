"""Read-only status/history/review; private admin preview and pause controls."""

import asyncio
from time import monotonic

from src.commands.admin_commands import is_admin
from src.config.premarket import SYMBOLS
from src.intelligence import premarket_store as store,premarket_risk as risk
from src.intelligence.premarket_review import report as review_report
from src.jobs.premarket_scheduler import active,collect_snapshot,destinations
from src.utils.telegram_messages import reply_long_message

LAST_PREVIEW=0.0
PREVIEW_LOCK=asyncio.Lock()


def status():
    rows=store.history(1)
    lines=["Smart Money Premarket Risk","Monitoring: "+("ON" if active() else "OFF"),
        "Checks: 08:45 and 09:15 America/New_York; outcome review 16:20. Weekdays; fresh session evidence required.",
        f"Destinations: {len(destinations())} · instruments: {len(SYMBOLS)}",
        "Grades: WATCH / ELEVATED / SEVERE. Missing coverage is LIMITED, not a calm signal.",
        "Delivery: one warning per level/day/destination; a higher level can alert again. Failed delivery can retry at the next scheduled slot.",
        "Futures changes use the prior US cash closing bar, not settlement. Continuous-contract roll windows are withheld.",
        "Latest recorded check: "+(rows[0]["observed_at"]+" · "+rows[0]["assessment"]["level"] if rows else "none")]
    if rows:
        receipts=store.receipts(rows[0]["day"])
        lines.append("Today's delivery receipts: "+("; ".join(row["status"]+" at "+row["at"] for row in receipts) or "none recorded"))
    lines.extend(["/premarket history · /premarket review","/premarket preview · /premarket on · /premarket off — private admin only",
                  "Preview does not save a scheduled decision or send channel alerts. Regular-session alerts retain their existing rules."])
    return "\n".join(lines)


async def premarket_command(update,context):
    global LAST_PREVIEW
    if not update.message:return
    action=str(context.args[0]).lower() if context.args else "status"
    private_admin=is_admin(update) and getattr(update.effective_chat,"type","")=="private"
    if action in {"on","off","preview"} and not private_admin:
        await update.message.reply_text("Unauthorized: private admin only",parse_mode=None);return
    try:
        if action in {"on","off"}:
            store.set_enabled(action=="on");text=status()
        elif action=="status":text=status()
        elif action=="history":
            values=store.history(6)
            text="Premarket Decision History\n\n"+"\n\n".join(risk.render(row) for row in values) if values else "No recorded premarket checks yet."
        elif action=="review":text=review_report()
        elif action=="preview":
            async with PREVIEW_LOCK:
                if monotonic()-LAST_PREVIEW<180:
                    await update.message.reply_text("Preview cooldown: wait three minutes between live checks.",parse_mode=None);return
                LAST_PREVIEW=monotonic()
                value=await asyncio.to_thread(collect_snapshot)
                text="Preview only; no scheduled ledger or channel delivery changes.\n\n"+risk.render(value)
        else:text="Use /premarket [status|history|review|preview|on|off]"
        await reply_long_message(update,text,title="Premarket Risk",parse_mode=None)
    except Exception as error:
        await update.message.reply_text("Premarket view unavailable: "+type(error).__name__,parse_mode=None)
