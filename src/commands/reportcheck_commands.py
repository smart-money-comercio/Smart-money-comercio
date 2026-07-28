import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_report import build_daily_report
from src.reports.report_quality import validate_daily_report_quality


def format_list(items: list[str]) -> str:
    if not items:
        return "None"

    return ", ".join(str(item) for item in items)


def format_report_quality_status(result: dict) -> str:
    passes = bool(result.get("passes"))
    status = "PASS ✅" if passes else "FAIL ⚠️"

    ai_summary_status = "OK" if result.get("ai_summary_ok") else "Needs fix"

    return f"""
Daily Report Quality
Status: {status}

Chars: {result.get("chars")} / {result.get("max_chars")}
Missing Headers: {format_list(result.get("missing_headers") or [])}
Duplicate Headers: {format_list(result.get("duplicate_headers") or [])}
Removed Headers Present: {format_list(result.get("removed_headers_present") or [])}
What Changed Bullets: {result.get("what_changed_bullets")}
AI Summary Format: {ai_summary_status}
""".strip()


async def reportcheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧪 Checking daily report quality..."
    )

    try:
        report = await asyncio.to_thread(build_daily_report)
        result = validate_daily_report_quality(report)
        message = format_report_quality_status(result)

        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Daily Report Quality\n"
            "Status: FAIL ⚠️\n\n"
            f"Error: {type(error).__name__}"
        )