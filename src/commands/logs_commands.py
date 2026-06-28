import os
import subprocess

from telegram import Update
from telegram.ext import ContextTypes

from src.commands.admin_commands import is_admin


DEFAULT_SERVICE_NAME = "smart-money-ai-bot"
DEFAULT_LOG_LINES = 40
MAX_LOG_LINES = 120


def parse_line_count(args: list[str]) -> int:
    if not args:
        return DEFAULT_LOG_LINES

    try:
        requested_lines = int(args[0])
    except ValueError:
        return DEFAULT_LOG_LINES

    if requested_lines <= 0:
        return DEFAULT_LOG_LINES

    return min(requested_lines, MAX_LOG_LINES)


def sanitize_logs(text: str) -> str:
    blocked_terms = [
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "SEC_API_USER_AGENT",
        "SEC_USER_AGENT",
    ]

    sanitized = text

    for term in blocked_terms:
        sanitized = sanitized.replace(term, "[REDACTED]")

    return sanitized


def trim_message(text: str, max_length: int = 3500) -> str:
    if len(text) <= max_length:
        return text

    return text[-max_length:]


def get_recent_logs(line_count: int) -> tuple[bool, str]:
    service_name = os.getenv("SYSTEMD_SERVICE_NAME", DEFAULT_SERVICE_NAME)

    try:
        result = subprocess.run(
            [
                "sudo",
                "-n",
                "/usr/bin/journalctl",
                "-u",
                service_name,
                "-n",
                str(line_count),
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()

        combined_output = "\n".join(
            part for part in [output, error] if part
        ).strip()

        if result.returncode == 0:
            return True, combined_output or "No logs returned."

        return False, combined_output or f"journalctl failed with exit code {result.returncode}."

    except subprocess.TimeoutExpired:
        return False, "Log request timed out after 15 seconds."
    except Exception as exc:
        return False, f"Log request failed: {exc}"


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized: admin only")
        return

    line_count = parse_line_count(context.args)

    success, output = get_recent_logs(line_count)
    output = sanitize_logs(output)
    output = trim_message(output)

    if success:
        await update.message.reply_text(
            f"📋 Smart Money AI Recent Logs\n\n"
            f"Last {line_count} lines:\n\n"
            f"{output}"
        )
        return

    await update.message.reply_text(
        f"❌ Failed to read logs\n\n{output}"
    )