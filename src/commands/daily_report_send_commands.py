from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import get_current_chat_id, is_admin
from src.jobs.daily_report_scheduler import get_daily_report_chat_ids
from src.reports.daily_report import build_daily_report
from src.utils.telegram_messages import (
    edit_or_reply_long_message,
    send_long_message_to_chat,
)


async def senddaily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    destinations = get_daily_report_chat_ids()

    if not destinations:
        await update.message.reply_text(
            "No daily report destination configured.\n\n"
            "Add this to .env:\n"
            "TELEGRAM_DAILY_REPORT_CHAT_ID=@YourChannelUsername\n\n"
            "Or use a private channel ID like:\n"
            "TELEGRAM_DAILY_REPORT_CHAT_ID=-1001234567890",
            parse_mode=None,
        )
        return

    loading_message = await update.message.reply_text(
        "🗞 Building and sending daily report...\n\n"
        f"Destination count: {len(destinations)}",
        parse_mode=None,
    )

    try:
        report = build_daily_report()
        success_count = 0

        for destination in destinations:
            try:
                await send_long_message_to_chat(
                    bot=context.bot,
                    chat_id=destination,
                    text=report,
                    title="📊 Smart Money AI Daily Report",
                    parse_mode=None,
                )
                success_count += 1
            except Exception:
                continue

        await loading_message.edit_text(
            "Daily report send complete.\n\n"
            f"Successful destinations: {success_count}/{len(destinations)}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to send daily report right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def testdaily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}",
            parse_mode=None,
        )
        return

    loading_message = await update.message.reply_text(
        "🧪 Building test daily report...",
        parse_mode=None,
    )

    try:
        report = build_daily_report()

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report,
            title="🧪 Test Daily Report",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build test daily report right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )