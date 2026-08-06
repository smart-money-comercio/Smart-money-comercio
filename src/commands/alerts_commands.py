import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.alert_monitor_report import build_alert_monitor_report
from src.utils.telegram_messages import edit_or_reply_long_message


def should_force_alert_refresh(args) -> bool:
    args = [str(arg or "").lower().strip() for arg in args or []]

    return any(arg in {"refresh", "live", "force"} for arg in args)


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    force_refresh = should_force_alert_refresh(context.args)

    loading_message = await update.message.reply_text(
        "🚨 Building live alert monitor..."
        if force_refresh
        else "🚨 Building alert monitor...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_alert_monitor_report,
            force_refresh,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🚨 Alert Monitor",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Alert Monitor\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias.
async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await alerts_command(update, context)