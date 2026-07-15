from telegram import Update
from telegram.ext import ContextTypes

from src.reports.quarterly_report import build_quarterly_market_review
from src.utils.telegram_messages import reply_long_message


async def quarterly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    try:
        args = context.args or []

        if args and args[0].lower() == "refresh":
            try:
                from src.reports.morning_brief_intro import refresh_morning_brief_cache

                refresh_morning_brief_cache()
            except Exception:
                pass

            quarter_label = " ".join(args[1:]).strip() or None
        else:
            quarter_label = " ".join(args).strip() or None

        report = build_quarterly_market_review(quarter_label=quarter_label)

        await reply_long_message(
            update=update,
            text=report,
            title="📘 Quarterly Review",
            parse_mode=None,
        )

    except Exception as error:
        await update.message.reply_text(
            "Quarterly review unavailable.\n\n"
            f"Error: {type(error).__name__}: {error}"
        )


quarterly_review_command = quarterly_command
quarterlyreport_command = quarterly_command