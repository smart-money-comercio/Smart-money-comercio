from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


STATUS_PATH = Path("data/daily_agent_status.json")
CRON_LOG_PATH = Path("data/daily_agent_cron.log")

NY_TZ = ZoneInfo("America/New_York")
EXPECTED_RUN_TIME = time(8, 15)
WATCHDOG_CHECK_TIME = time(8, 45)
MIN_REPORT_CHARACTERS = 3000


def now_ny() -> datetime:
    return datetime.now(NY_TZ)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return {
            "success": False,
            "last_run": None,
            "message": f"Could not read {path}: {type(error).__name__}: {error}",
            "steps": [],
        }


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed
    except Exception:
        return None


def read_recent_log_lines(path: Path, limit: int = 120) -> list[str]:
    if not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    return lines[-limit:]


def compact(value: Any, limit: int = 220) -> str:
    text = str(value or "").replace("\r", "").strip()

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def latest_step_status(status: dict[str, Any], step_name: str) -> str:
    steps = status.get("steps", [])

    if not isinstance(steps, list):
        return "UNKNOWN"

    for step in reversed(steps):
        if step_name.lower() in str(step.get("name") or "").lower():
            return str(step.get("status") or "unknown").upper()

    return "UNKNOWN"


def has_recent_telegram_success(log_lines: list[str]) -> bool:
    joined = "\n".join(log_lines[-80:]).lower()

    return "telegram send complete" in joined or "daily report output" in joined


def has_recent_cron_error(log_lines: list[str]) -> bool:
    joined = "\n".join(log_lines[-80:]).lower()

    error_terms = [
        "traceback",
        "permissionerror",
        "syntaxerror",
        "command not found",
        "telegram send skipped",
        "status: fail",
    ]

    return any(term in joined for term in error_terms)


def build_watchdog_payload() -> dict[str, Any]:
    status = read_json_file(STATUS_PATH)
    log_lines = read_recent_log_lines(CRON_LOG_PATH)

    current_ny = now_ny()
    today_ny = current_ny.date()
    weekday = current_ny.weekday() < 5

    last_run_raw = status.get("last_run")
    last_run_dt = parse_datetime(last_run_raw)
    last_run_ny = last_run_dt.astimezone(NY_TZ) if last_run_dt else None

    ran_today = bool(last_run_ny and last_run_ny.date() == today_ny)
    agent_success = status.get("success") is True
    report_chars = int(status.get("report_characters") or 0)

    telegram_success = has_recent_telegram_success(log_lines)
    cron_error = has_recent_cron_error(log_lines)

    daily_report_step = latest_step_status(status, "Daily Report Build")
    quality_step = latest_step_status(status, "Quality Review")

    if not weekday:
        watchdog_status = "OFF"
        action = "Weekend mode. No weekday daily-agent run is required."
    elif current_ny.time() < WATCHDOG_CHECK_TIME:
        watchdog_status = "WAITING"
        action = "It is not past the watchdog check time yet. Recheck after 8:45 AM New York time."
    elif not ran_today:
        watchdog_status = "FAIL"
        action = "Daily agent has not recorded a successful run today. Run /rundailyagent or check cron."
    elif not agent_success:
        watchdog_status = "FAIL"
        action = "Daily agent ran today but failed. Check /agentlog and server cron logs."
    elif report_chars < MIN_REPORT_CHARACTERS:
        watchdog_status = "WARNING"
        action = "Daily agent passed, but the report may be too short. Review /report and /quality."
    elif cron_error and not telegram_success:
        watchdog_status = "WARNING"
        action = "Agent status passed, but cron log still shows recent errors and no Telegram send evidence."
    else:
        watchdog_status = "PASS"
        action = "No action needed. Daily agent appears healthy."

    return {
        "watchdog_status": watchdog_status,
        "current_time_ny": current_ny.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "expected_run": "Monday-Friday 8:15 AM New York time",
        "watchdog_check": "Monday-Friday 8:45 AM New York time",
        "ran_today": ran_today,
        "agent_success": agent_success,
        "last_run": last_run_raw or "Not available",
        "last_run_ny": last_run_ny.strftime("%Y-%m-%d %H:%M:%S %Z") if last_run_ny else "Not available",
        "completed_at": status.get("completed_at") or "Not available",
        "report_characters": report_chars,
        "daily_report_step": daily_report_step,
        "quality_step": quality_step,
        "telegram_success": telegram_success,
        "cron_error": cron_error,
        "message": compact(status.get("message") or "No saved daily-agent message."),
        "action": action,
        "generated": utc_now(),
    }


def bool_label(value: bool) -> str:
    return "YES" if value else "NO"


def status_label(value: bool) -> str:
    return "PASS" if value else "CHECK"


def build_watchdog_report() -> str:
    payload = build_watchdog_payload()

    return f"""
🐶 Daily Agent Watchdog

Watchdog Status
Status: {payload["watchdog_status"]}
Action Needed: {payload["action"]}

Schedule Check
Current Time NY: {payload["current_time_ny"]}
Expected Daily Agent Run: {payload["expected_run"]}
Watchdog Check Time: {payload["watchdog_check"]}

Daily Agent Health
Ran Today: {bool_label(payload["ran_today"])}
Agent Success: {bool_label(payload["agent_success"])}
Last Run UTC: {payload["last_run"]}
Last Run NY: {payload["last_run_ny"]}
Completed At: {payload["completed_at"]}
Report Characters: {payload["report_characters"]}

Workflow Evidence
Daily Report Build: {payload["daily_report_step"]}
Quality Review: {payload["quality_step"]}
Telegram Send Evidence: {status_label(payload["telegram_success"])}
Recent Cron Error Evidence: {bool_label(payload["cron_error"])}

Latest Message
{payload["message"]}

Next Commands
/agentlog
/agentstatus
/rundailyagent
/quality
/deploycheck

Generated: {payload["generated"]}
""".strip()
