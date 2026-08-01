import os
import subprocess
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
from src.config.command_catalog import (
    get_primary_commands,
    get_version_feature_lines,
)


APP_NAME = "Smart Money AI"
APP_VERSION = os.getenv("SMART_MONEY_VERSION", "v1.2")
RELEASE_NAME = os.getenv("SMART_MONEY_RELEASE_NAME", "Command Consolidation")
RELEASE_CHANNEL = os.getenv("SMART_MONEY_RELEASE_CHANNEL", "Production")
RELEASE_DATE = os.getenv("SMART_MONEY_RELEASE_DATE", "2026-07-28")
TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")


PRIMARY_COMMANDS = get_primary_commands()


VERSION_FEATURES = get_version_feature_lines()


RELEASE_NOTES = [
    "Daily report quality preflight protection",
    "/brief — cleaner daily market brief",
    "What Changed Today — market-memory comparison",
    "Theme Read — stronger/fading/actionable themes",
    "AI Summary — Signal / Implication / Validation",
    "Top Opportunities — edge, trigger, risk/action",
    "Risk Notes — shorter decision-focused risk layer",
    "Action Checklist — next best commands",
    "/quality — report guardrail check",
    "/commands — cleaned product menu",
    "/help — quick-start guide",
    "Friendly aliases: /stock, /watch, /macro, /calendar",
    "/snapshot — fast one-screen market read",
]


REPORT_INTELLIGENCE = [
    "Remembers recent market themes",
    "Tracks theme persistence and leadership shifts",
    "Reduces repeated headline noise",
    "Keeps /brief concise with quality guardrails",
]


BEST_DAILY_FLOW = [
    "/snapshot",
    "/brief",
    "/quality",
    "/stock SYMBOL",
    "/calendar",
]


def clean_text(value: Any, max_length: int = 120) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def get_generated_timestamp() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

        if result.returncode != 0:
            return ""

        return clean_text(result.stdout, 80)
    except Exception:
        return ""


def get_git_commit() -> str:
    return run_git_command(["rev-parse", "--short", "HEAD"]) or "unavailable"


def get_git_branch() -> str:
    return run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]) or "unavailable"


def format_command_lines(commands: list[tuple[str, str]]) -> str:
    return "\n".join(f"{command} - {description}" for command, description in commands)


def format_bullet_lines(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items)


def format_numbered_lines(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def build_version_text() -> str:
    return f"""
🚀 {APP_NAME}
Version: {APP_VERSION}
Release: {RELEASE_NAME}
Channel: {RELEASE_CHANNEL}
Release Date: {RELEASE_DATE}

Status: Active ✅
Branch: {get_git_branch()}
Commit: {get_git_commit()}
Checked: {get_generated_timestamp()} {TIMEZONE}

Primary Commands
{format_command_lines(PRIMARY_COMMANDS)}

{APP_VERSION} Intelligence
{format_bullet_lines(VERSION_FEATURES)}

More:
/versionnotes - Full release notes
/commands - Full command menu
/help - Quick-start guide

Research only. Not financial advice.
""".strip()


def build_version_notes_text() -> str:
    return f"""
🚀 {APP_NAME} {APP_VERSION}
{RELEASE_NAME}

What’s New
{format_bullet_lines(RELEASE_NOTES)}

Report Intelligence
{format_bullet_lines(REPORT_INTELLIGENCE)}

Best Daily Flow
{format_numbered_lines(BEST_DAILY_FLOW)}

Build Info
Channel: {RELEASE_CHANNEL}
Release Date: {RELEASE_DATE}
Branch: {get_git_branch()}
Commit: {get_git_commit()}

Research only. Not financial advice.
""".strip()