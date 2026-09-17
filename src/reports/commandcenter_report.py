from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\r", "").replace("\n", " ").strip()

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def safe_daily_agent_status() -> dict[str, Any]:
    try:
        from src.jobs.daily_agent_job import load_daily_agent_status
        return load_daily_agent_status()
    except Exception as error:
        return {
            "success": False,
            "last_run": None,
            "report_characters": 0,
            "message": f"{type(error).__name__}: {error}",
        }


def safe_source_refresh_status() -> dict[str, Any]:
    try:
        from src.jobs.source_refresh_job import load_source_refresh_status
        return load_source_refresh_status()
    except Exception as error:
        return {
            "success": False,
            "overall_status": "UNKNOWN",
            "last_run": None,
            "message": f"{type(error).__name__}: {error}",
        }


def safe_source_health() -> tuple[str, list[str]]:
    try:
        from src.reports.sourcehealth_report import compute_overall_health
        return compute_overall_health()
    except Exception as error:
        return "UNKNOWN", [f"{type(error).__name__}: {error}"]


def safe_watchdog_status() -> dict[str, Any]:
    try:
        from src.reports.watchdog_report import build_watchdog_payload
        return build_watchdog_payload()
    except Exception as error:
        return {
            "watchdog_status": "UNKNOWN",
            "ran_today": False,
            "agent_success": False,
            "telegram_success": False,
            "action": f"{type(error).__name__}: {error}",
        }


def yes_no(value: Any) -> str:
    return "YES" if value is True else "NO"


def normalize_status(value: Any, fallback: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or fallback


def determine_system_status(
    agent: dict[str, Any],
    source_health: str,
    watchdog: dict[str, Any],
    refresh: dict[str, Any],
) -> str:
    watchdog_status = normalize_status(watchdog.get("watchdog_status"))
    refresh_status = normalize_status(
        refresh.get("overall_status")
        or ("PASS" if refresh.get("success") else "UNKNOWN")
    )

    if source_health == "FAIL":
        return "FAIL"

    if watchdog_status == "FAIL":
        return "FAIL"

    if agent.get("last_run") and agent.get("success") is False:
        return "FAIL"

    if source_health in {"WARNING", "UNKNOWN"}:
        return "WARNING"

    if watchdog_status in {"WARNING", "UNKNOWN"}:
        return "WARNING"

    if refresh_status in {"WARNING", "FAIL", "UNKNOWN"}:
        return "WARNING"

    if not agent.get("last_run"):
        return "WARNING"

    return "PASS"


def determine_next_action(
    overall: str,
    agent: dict[str, Any],
    source_health: str,
    watchdog: dict[str, Any],
    refresh: dict[str, Any],
) -> str:
    watchdog_status = normalize_status(watchdog.get("watchdog_status"))
    refresh_status = normalize_status(refresh.get("overall_status"))

    if source_health == "FAIL":
        return "Run /sourcehealth, then /refreshsources to repair or refresh failing data sources."

    if watchdog_status == "FAIL":
        return "Run /watchdog and /agentlog. If needed, run /rundailyagent manually."

    if agent.get("last_run") and agent.get("success") is False:
        return "Run /agentlog to identify the failed workflow step, then use /rundailyagent."

    if source_health == "WARNING":
        return "Run /sourcehealth. Use /refreshsources if data is stale or a source is missing."

    if refresh_status == "WARNING":
        return "Review /sourcehealth to identify the source that did not refresh cleanly."

    if watchdog_status == "WARNING":
        return "Review /watchdog and /agentlog before relying on today's automated report."

    if not agent.get("last_run"):
        return "The Daily Agent has no saved run. Use /rundailyagent."

    if overall == "PASS":
        return "System is healthy. No corrective action is required."

    return "Review /sourcehealth, /watchdog, and /agentlog."


def build_commandcenter_report() -> str:
    agent = safe_daily_agent_status()
    source_health, source_notes = safe_source_health()
    watchdog = safe_watchdog_status()
    refresh = safe_source_refresh_status()

    source_health = normalize_status(source_health)

    watchdog_status = normalize_status(watchdog.get("watchdog_status"))

    refresh_status = normalize_status(
        refresh.get("overall_status")
        or ("PASS" if refresh.get("success") else "UNKNOWN")
    )

    overall = determine_system_status(
        agent=agent,
        source_health=source_health,
        watchdog=watchdog,
        refresh=refresh,
    )

    action = determine_next_action(
        overall=overall,
        agent=agent,
        source_health=source_health,
        watchdog=watchdog,
        refresh=refresh,
    )

    source_note = (
        compact(source_notes[0], 160)
        if source_notes
        else "No source-health notes."
    )

    report_chars = int(agent.get("report_characters") or 0)

    return f"""
Smart Money AI Command Center

System Status
Overall: {overall}
Recommended Action: {action}

Daily Agent
Status: {"PASS" if agent.get("success") is True else "FAIL" if agent.get("last_run") else "NOT RUN"}
Last Run: {agent.get("last_run") or "Not available"}
Completed At: {agent.get("completed_at") or "Not available"}
Report Characters: {report_chars}
Message: {compact(agent.get("message") or "No saved Daily Agent message.")}

Source Health
Status: {source_health}
Read: {source_note}

Source Refresh Engine
Status: {refresh_status}
Last Run: {refresh.get("last_run") or "Not available"}
Message: {compact(refresh.get("message") or "No saved source refresh message.")}

Daily Agent Watchdog
Status: {watchdog_status}
Ran Today: {yes_no(watchdog.get("ran_today"))}
Agent Success: {yes_no(watchdog.get("agent_success"))}
Telegram Send Evidence: {yes_no(watchdog.get("telegram_success"))}
Watchdog Action: {compact(watchdog.get("action") or "No watchdog action available.")}

Decision Tools
/brief - Daily market and intelligence report
/allocation - Current portfolio posture
/tradeplans - Highest-ranked trade plans
/contextstatus - Intelligence provider status
/summarypreview - Smart Money Summary preview

Operations
/rundailyagent - Run full daily workflow
/refreshsources - Refresh intelligence sources
/sourcehealth - Inspect data-source health
/watchdog - Check automation health
/agentlog - Inspect recent agent workflow
/agentstatus - Latest Daily Agent status

System
/quality - Report quality checks
/deploycheck - Deployment readiness
/status - Bot status
/diagnostics - System diagnostics
/commandcenter - Return to this dashboard

Generated: {utc_now()}
""".strip()
