from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import get_current_chat_id, is_admin
from src.jobs.daily_report_scheduler import (
    get_daily_report_chat_ids,
    send_daily_report_to_chat,
)


async def senddaily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}"
        )
        return

    destinations = get_daily_report_chat_ids()

    if not destinations:
        await update.message.reply_text(
            "No daily report destination configured.\n\n"
            "Add this to .env:\n"
            "TELEGRAM_DAILY_REPORT_CHAT_ID=@YourChannelUsername\n\n"
            "Or use a private channel ID like:\n"
            "TELEGRAM_DAILY_REPORT_CHAT_ID=-1001234567890"
        )
        return

    await update.message.reply_text(
        "🗞 Sending daily report to configured destination(s)...\n\n"
        f"Destination count: {len(destinations)}"
    )

    success_count = 0

    for destination in destinations:
        success = await send_daily_report_to_chat(
            bot=context.bot,
            chat_id=destination,
        )

        if success:
            success_count += 1

    await update.message.reply_text(
        "Daily report send complete.\n\n"
        f"Successful destinations: {success_count}/{len(destinations)}"
    )


async def testdaily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    current_chat_id = get_current_chat_id(update)

    if not is_admin(update):
        await update.message.reply_text(
            "Unauthorized: admin only\n\n"
            f"Current chat ID:\n{current_chat_id}"
        )
        return

    await send_daily_report_to_chat(
        bot=context.bot,
        chat_id=int(current_chat_id),
    )