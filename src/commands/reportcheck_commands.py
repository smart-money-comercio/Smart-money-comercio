import asyncio
import os

from telegram import Update
from telegram.ext import ContextTypes

from src.reports.daily_report import build_daily_report
from src.reports.report_quality import validate_daily_report_quality


try:
    from src.reports.report_quality import MAX_DAILY_REPORT_CHARS
except Exception:
    MAX_DAILY_REPORT_CHARS = int(os.getenv("DAILY_REPORT_MAX_CHARS", "6200"))


def get_validation_value(result: dict, *keys, default=None):
    for key in keys:
        if key in result:
            return result.get(key)

    return default


def status_label(ok: bool) -> str:
    return "PASS" if ok else "CHECK"


def format_items(items) -> str:
    if not items:
        return "None"

    return ", ".join(str(item) for item in items)


def build_daily_report_quality_card() -> str:
    report = build_daily_report()
    result = validate_daily_report_quality(report)

    chars = get_validation_value(
        result,
        "chars",
        "character_count",
        "length",
        default=len(report),
    )

    missing = get_validation_value(
        result,
        "missing_required_headers",
        "missing_headers",
        "missing",
        default=[],
    ) or []

    duplicates = get_validation_value(
        result,
        "duplicate_headers",
        "duplicates",
        default=[],
    ) or []

    removed = get_validation_value(
        result,
        "removed_headers_present",
        "removed_present",
        "removed_headers",
        default=[],
    ) or []

    what_changed_bullets = get_validation_value(
        result,
        "what_changed_bullets",
        "what_changed_today_bullets",
        default="unknown",
    )

    ai_summary_ok = bool(
        get_validation_value(
            result,
            "ai_summary_ok",
            "ai_summary_valid",
            default=False,
        )
    )

    required_ok = not missing
    duplicates_ok = not duplicates
    removed_ok = not removed

    try:
        what_changed_ok = int(what_changed_bullets) <= 3
    except Exception:
        what_changed_ok = what_changed_bullets == "unknown"

    try:
        length_ok = int(chars) <= int(MAX_DAILY_REPORT_CHARS)
    except Exception:
        length_ok = True

    overall_ok = bool(result.get("passes"))

    details = ""

    if not overall_ok:
        details = f"""

Details
Missing Required Sections: {format_items(missing)}
Duplicate Sections: {format_items(duplicates)}
Removed Sections Present: {format_items(removed)}
""".rstrip()

    return f"""
🧪 Daily Report Quality

Status: {status_label(overall_ok)}
Characters: {chars} / {MAX_DAILY_REPORT_CHARS}

Checks
Required Sections: {status_label(required_ok)}
Duplicate Sections: {status_label(duplicates_ok)}
Removed Sections: {status_label(removed_ok)}
AI Summary: {status_label(ai_summary_ok)}
What Changed: {status_label(what_changed_ok)} — {what_changed_bullets} bullets
Length: {status_label(length_ok)}

Use:
/brief
/snapshot
/deploycheck
{details}

Research only. Not financial advice.
""".strip()


async def reportcheck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    loading_message = await update.message.reply_text(
        "🧪 Checking daily report quality..."
    )

    try:
        message = await asyncio.to_thread(build_daily_report_quality_card)
        await loading_message.edit_text(message)

    except Exception as error:
        await loading_message.edit_text(
            "Daily Report Quality\n"
            "Status: CHECK\n\n"
            f"Error: {type(error).__name__}: {error}"
        )