import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.command_catalog import (
    get_primary_commands,
    get_version_feature_lines,
)


APP_NAME = "Smart Money AI"
APP_VERSION = os.getenv("SMART_MONEY_VERSION", "v1.3")
RELEASE_NAME = os.getenv("SMART_MONEY_RELEASE_NAME", "Intelligence Quality Upgrade")
RELEASE_STATUS = os.getenv("SMART_MONEY_RELEASE_STATUS", "In Progress")
RELEASE_CHANNEL = os.getenv("SMART_MONEY_RELEASE_CHANNEL", "Production")
RELEASE_DATE = os.getenv("SMART_MONEY_RELEASE_DATE", "2026-08-01")
TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")


PRIMARY_COMMANDS = get_primary_commands()
VERSION_FEATURES = get_version_feature_lines()


RELEASE_NOTES = [
    "/top10 — evolving Top 20 conviction ranking",
    "Top 20 memory tracks new entrants, risers, fallers, and names that fell out",
    "/stock — evolving ticker intelligence card",
    "Ticker memory tracks score, risk, action, and signal changes",
    "/snapshot — fast one-screen market read",
    "/themes — active market theme read",
    "/quality — cleaner daily report health card",
    "/deploycheck — upgraded release health summary",
    "/help — synced with shared command catalog",
    "/commands — synced with shared command catalog",
    "/version — synced with release metadata",
    "Strict command audit enabled in preflight",
    "Daily report quality preflight protection",
    "Preflight now uses the bot virtualenv",
    "Duplicate daily report build removed from preflight",
    "Admin/security command drift cleaned",
]


PROTECTED_GUARDRAILS = [
    "Command catalog audit",
    "Strict command audit mode",
    "Daily report quality check",
    "Virtualenv-based preflight",
    "Required section validation",
    "AI Summary format validation",
    "Removed-section regression check",
    "Telegram command registration drift check",
]


REPORT_INTELLIGENCE = [
    "Evolving Top 20 conviction ranking",
    "Concise daily brief",
    "Fast market snapshot",
    "Theme-specific read",
    "Adaptive AI Summary",
    "What Changed Today memory",
    "Top Opportunities",
    "Risk Notes",
    "Action Checklist",
]


BEST_DAILY_FLOW = [
    "/snapshot",
    "/brief",
    "/themes",
    "/quality",
    "/stock SYMBOL",
    "/calendar",
    "/deploycheck",
]


def run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return "unavailable"

        value = result.stdout.strip()

        return value or "unavailable"

    except Exception:
        return "unavailable"


def get_git_commit() -> str:
    return run_git_command(["rev-parse", "--short", "HEAD"])


def get_git_branch() -> str:
    return run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])


def get_generated_timestamp() -> str:
    try:
        now = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        now = datetime.now()

    return now.strftime("%Y-%m-%d %H:%M:%S")


def format_command_lines(commands: list[tuple[str, str]]) -> str:
    return "\n".join(
        f"{command} - {description}"
        for command, description in commands
    )


def format_bullet_lines(items: list[str]) -> str:
    return "\n".join(
        f"• {item}"
        for item in items
    )


def build_version_text() -> str:
    return f"""
{APP_NAME}
Version: {APP_VERSION}
Release: {RELEASE_NAME}
Channel: {RELEASE_CHANNEL}
Status: {RELEASE_STATUS}
Release Date: {RELEASE_DATE}

Build
Branch: {get_git_branch()}
Commit: {get_git_commit()}
Checked: {get_generated_timestamp()} {TIMEZONE}

Primary Commands
{format_command_lines(PRIMARY_COMMANDS)}

Daily Flow
{format_bullet_lines(BEST_DAILY_FLOW)}

Research only. Not financial advice.
""".strip()


def build_version_notes_text() -> str:
    return f"""
{APP_NAME} Release Notes

Version: {APP_VERSION}
Release: {RELEASE_NAME}
Channel: {RELEASE_CHANNEL}
Status: {RELEASE_STATUS}
Release Date: {RELEASE_DATE}

Added
• /snapshot — fast one-screen market read
• /themes — active market theme read

Improved
• /quality — cleaner daily report health card
• /deploycheck — release health summary
• /help — generated from shared command catalog
• /commands — generated from shared command catalog
• /version — generated from release metadata

Protected
{format_bullet_lines(PROTECTED_GUARDRAILS)}

Report Intelligence
{format_bullet_lines(REPORT_INTELLIGENCE)}

Best Daily Flow
{format_bullet_lines(BEST_DAILY_FLOW)}

Full Change List
{format_bullet_lines(RELEASE_NOTES)}

Build
Branch: {get_git_branch()}
Commit: {get_git_commit()}
Checked: {get_generated_timestamp()} {TIMEZONE}

Use:
/snapshot
/brief
/themes
/quality
/deploycheck

Research only. Not financial advice.
""".strip()