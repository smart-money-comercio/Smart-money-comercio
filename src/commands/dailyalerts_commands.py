import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_alert_digest_report import build_daily_alert_digest_report
from src.utils.telegram_messages import edit_or_reply_long_message


def should_force_daily_alerts_refresh(args) -> bool:
    args = [str(arg or "").lower().strip() for arg in args or []]

    return any(arg in {"refresh", "live", "force"} for arg in args)


async def dailyalerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    force_refresh = should_force_daily_alerts_refresh(context.args)

    loading_message = await update.message.reply_text(
        "🚨 Building live daily alert digest..."
        if force_refresh
        else "🚨 Building daily alert digest...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_daily_alert_digest_report,
            force_refresh,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🚨 Daily Alert Digest",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Daily Alert Digest\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility alias.
async def dailyalerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dailyalerts_command(update, context)