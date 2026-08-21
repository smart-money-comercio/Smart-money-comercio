import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.alert_settings_report import (
    build_alertpreset_report,
    build_alertsettings_report,
)
from src.utils.telegram_messages import edit_or_reply_long_message


async def alertsettings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "⚙️ Loading alert settings...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_alertsettings_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="⚙️ Alert Settings",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Alert Settings\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def alertpreset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    preset_name = str(context.args[0] or "").strip() if context.args else ""

    loading_message = await update.message.reply_text(
        "⚙️ Loading alert preset...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(
            build_alertpreset_report,
            preset_name,
        )

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="⚙️ Alert Preset",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Alert Preset\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility aliases.
async def alertsettings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await alertsettings_command(update, context)


async def alertpreset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await alertpreset_command(update, context)