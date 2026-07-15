from telegram import Update
from telegram.ext import ContextTypes

from src.reports.weekly_calendar_report import build_weekly_calendar_report
from src.utils.telegram_messages import reply_long_message


async def weeklycalendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        report = build_weekly_calendar_report()

        await reply_long_message(
            update=update,
            text=report,
            title="📅 Weekly Calendar",
            parse_mode=None,
        )

    except Exception as error:
        await update.message.reply_text(
            "Weekly calendar unavailable.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )


weekly_calendar_command = weeklycalendar_command
weekahead_command = weeklycalendar_command