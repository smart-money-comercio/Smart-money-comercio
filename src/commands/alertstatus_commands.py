import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.alert_rules_report import (
    build_alertrules_report,
    build_alertstatus_report,
)
from src.utils.telegram_messages import edit_or_reply_long_message


async def alertstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🚨 Checking alert status...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_alertstatus_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="🚨 Alert Status",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Alert Status\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


async def alertrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "⚙️ Loading alert rules...",
        parse_mode=None,
    )

    try:
        message = await asyncio.to_thread(build_alertrules_report)

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=message,
            title="⚙️ Alert Rules",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Alert Rules\n"
            "Status: unavailable right now.\n\n"
            f"Error: {type(error).__name__}: {error}",
            parse_mode=None,
        )


# Compatibility aliases.
async def alertstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await alertstatus_command(update, context)


async def alertrules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await alertrules_command(update, context)