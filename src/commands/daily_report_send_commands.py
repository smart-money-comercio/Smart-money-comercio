import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import get_current_chat_id, is_admin
from src.intelligence.news_editor_store import confirm_watchlist_delivery
from src.jobs.daily_report_scheduler import (
    TELEGRAM_MESSAGE_LIMIT,
    build_weekend_delivery_report,
    get_daily_report_chat_ids,
    utc_now,
    weekend_outlook_due,
)
from src.reports import weekend_telegram
from src.reports.daily_news_brief import MAX_NEWS_CHARS
from src.reports.daily_report import build_daily_report
from src.reports.morning_brief_intro import ensure_morning_brief_cache_is_fresh
from src.utils.telegram_messages import (
    edit_or_reply_long_message,
    send_long_message_to_chat,
    split_long_message,
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

    now = utc_now()
    weekend = weekend_outlook_due(now)
    edition = weekend_telegram.edition_name(now) if weekend else "Daily report"
    loading_text = (f"🗞 Preparing and sending the {edition}..." if weekend else
                    "🗞 Refreshing market data and sending daily report...")
    loading_message = await update.message.reply_text(
        f"{loading_text}\n\n"
        f"Destination count: {len(destinations)}",
        parse_mode=None,
    )

    try:
        if weekend:
            report = await asyncio.to_thread(build_weekend_delivery_report, now)
            title = f"Smart Money {edition}"
            limit = TELEGRAM_MESSAGE_LIMIT
        else:
            ensure_morning_brief_cache_is_fresh(force_refresh=True)
            report = build_daily_report()
            title = "📊 Smart Money AI Daily Report"
            limit = MAX_NEWS_CHARS
        success_count = 0
        failed_destinations = []

        for destination in destinations:
            try:
                await send_long_message_to_chat(
                    bot=context.bot,
                    chat_id=destination,
                    text=report,
                    title=title,
                    parse_mode=None,
                    limit=limit,
                )
                success_count += 1
            except Exception as exc:
                failed_destinations.append(f"{destination}: {type(exc).__name__}")

        if success_count and not weekend:
            await asyncio.to_thread(confirm_watchlist_delivery, report)
        failure_text = ""

        if failed_destinations:
            failure_text = "\n\nFailed destinations:\n" + "\n".join(
                f"• {item}" for item in failed_destinations[:5]
            )

        await loading_message.edit_text(
            f"{edition} send complete.\n\n"
            f"Successful destinations: {success_count}/{len(destinations)}"
            f"{failure_text}",
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            f"Unable to send the {edition} right now.\n\n"
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
        "🧪 Refreshing data and building test daily report...",
        parse_mode=None,
    )

    try:
        # Force refresh so /testdaily visibly changes when new headlines/data exist.
        ensure_morning_brief_cache_is_fresh(force_refresh=True)

        report = build_daily_report()

        await edit_or_reply_long_message(
            update=update,
            loading_message=loading_message,
            text=report,
            title="🧪 Test Daily Report",
            parse_mode=None,
            limit=MAX_NEWS_CHARS,
        )

    except Exception as error:
        await loading_message.edit_text(
            "Unable to build test daily report right now.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )


async def dailycheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        "🧪 Running daily report system check...",
        parse_mode=None,
    )

    required_sections = [
        "Smart Money Daily News Brief",
        "Market Update",
        "Companies in Focus",
        "What's Ahead",
        "What We're Watching",
        "Research Notes",
    ]

    try:
        # Use max-age refresh, not force refresh, so dailycheck is realistic but not too aggressive.
        ensure_morning_brief_cache_is_fresh(max_age_minutes=360)

        destinations = get_daily_report_chat_ids()
        report = build_daily_report()
        chunks = split_long_message(report, limit=MAX_NEWS_CHARS)

        missing_sections = [
            section
            for section in required_sections
            if section not in report
        ]

        status = "✅ PASS" if not missing_sections else "⚠️ WARNING"

        if missing_sections:
            missing_text = "\n".join(f"• {section}" for section in missing_sections)
        else:
            missing_text = "None"

        destination_text = ", ".join(str(destination) for destination in destinations)
        if not destination_text:
            destination_text = "None configured"

        message = f"""
🧪 Daily Report System Check

Status: {status}

Report Build: ✅ Success
Report Length: {len(report):,} characters
Telegram Parts: {len(chunks)}
Destination Count: {len(destinations)}

Missing Sections:
{missing_text}

Destinations:
{destination_text}

Next Test Commands:
/report
/testdaily
/senddaily
""".strip()

        await loading_message.edit_text(
            message,
            parse_mode=None,
        )

    except Exception as error:
        await loading_message.edit_text(
            "❌ Daily report system check failed.\n\n"
            f"Error:\n{type(error).__name__}",
            parse_mode=None,
        )
