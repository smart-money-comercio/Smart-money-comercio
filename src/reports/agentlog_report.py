from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_PATH = Path("data/daily_agent_status.json")
CRON_LOG_PATH = Path("data/daily_agent_cron.log")


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


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


def compact(value: Any, limit: int = 220) -> str:
    text = str(value or "").replace("\r", "").strip()

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def read_recent_log_lines(path: Path, limit: int = 45) -> list[str]:
    if not path.exists():
        return ["No cron log found yet."]

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as error:
        return [f"Could not read cron log: {type(error).__name__}: {error}"]

    if not lines:
        return ["Cron log exists but is empty."]

    return lines[-limit:]


def format_status_value(status: dict[str, Any]) -> str:
    if not status:
        return "NOT RUN"

    if status.get("success") is True:
        return "PASS"

    if status.get("success") is False and status.get("last_run"):
        return "FAIL"

    return "UNKNOWN"


def format_step_line(step: dict[str, Any]) -> str:
    raw_status = str(step.get("status") or "unknown").lower()

    marker = {
        "pass": "PASS",
        "fail": "FAIL",
        "skip": "SKIP",
    }.get(raw_status, raw_status.upper())

    name = compact(step.get("name"), 60)
    detail = compact(step.get("detail"), 160)

    if detail:
        return f"- {marker}: {name} - {detail}"

    return f"- {marker}: {name}"


def build_recent_log_block(lines: list[str], max_chars: int = 1800) -> str:
    selected: list[str] = []
    total = 0

    for line in reversed(lines):
        clean_line = compact(line, 220)
        projected = total + len(clean_line) + 1

        if projected > max_chars:
            break

        selected.append(clean_line)
        total = projected

    selected.reverse()

    return "\n".join(selected).strip() or "No recent log lines available."


def build_agentlog_report() -> str:
    status = read_json_file(STATUS_PATH)
    steps = status.get("steps", []) if isinstance(status.get("steps"), list) else []
    recent_log = read_recent_log_lines(CRON_LOG_PATH)

    status_value = format_status_value(status)
    last_run = status.get("last_run") or "Not available"
    completed_at = status.get("completed_at") or "Not available"
    report_chars = status.get("report_characters", 0)
    dry_run = status.get("dry_run", "unknown")
    message = compact(status.get("message") or "No saved status message.", 240)

    failed_steps = [
        step for step in steps
        if str(step.get("status") or "").lower() == "fail"
    ]

    workflow_lines = [format_step_line(step) for step in steps[-12:]]
    if not workflow_lines:
        workflow_lines = ["- No saved workflow steps yet."]

    if failed_steps:
        failure_summary = "\n".join(format_step_line(step) for step in failed_steps[-5:])
    else:
        failure_summary = "No failed steps in the latest saved run."

    log_block = build_recent_log_block(recent_log)

    return f"""
🧭 Smart Money Daily Agent Log

Current Status
Status: {status_value}
Last Run: {last_run}
Completed At: {completed_at}
Dry Run: {dry_run}
Report Characters: {report_chars}
Message: {message}

Latest Workflow
{chr(10).join(workflow_lines)}

Failure Summary
{failure_summary}

Recent Cron Log
{log_block}

Troubleshooting Commands
/agentstatus
/rundailyagent
/quality
/deploycheck
/logs

Generated: {utc_now()}
""".strip()
