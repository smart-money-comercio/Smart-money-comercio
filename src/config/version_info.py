import os
from datetime import datetime
from zoneinfo import ZoneInfo


APP_VERSION = os.getenv("SMART_MONEY_VERSION", "v1.4")
RELEASE_NAME = os.getenv("SMART_MONEY_RELEASE_NAME", "Automation, Alerts, and Monitoring")
RELEASE_STATUS = os.getenv("SMART_MONEY_RELEASE_STATUS", "In Progress")
RELEASE_CHANNEL = os.getenv("SMART_MONEY_RELEASE_CHANNEL", "Production")
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")


V13_COMMAND_STACK = [
    "/alertstatus",
    "/alertrules",
    "/smartmoney",
    "/alerts",
    "/dailyalerts",
    "/conviction",
    "/global",
    "/portfolio",
    "/defense",
    "/snapshot",
    "/top10",
    "/brief",
    "/stock SYMBOL",
    "/scorecard SYMBOL",
    "/risk SYMBOL",
    "/volume SYMBOL",
    "/earnings SYMBOL",
    "/analyst SYMBOL",
    "/sec SYMBOL",
    "/filing SYMBOL",
]


RELEASE_NOTES = [
    "/alertstatus — added current alert monitor state and queue visibility",
    "/alertrules — added visible alert thresholds and environment override documentation",
    "Alert thresholds moved into src/config/alert_rules.py for safer v1.4 monitoring control",
    "/dailyalerts — added compressed Daily Alert Digest for quick review",
    "Daily alert digest reuses the /alerts engine and summarizes critical changes, warnings, macro/theme alerts, and first action",
    "/alerts — added Alert Monitor for conviction, risk, macro, filing, catalyst, and validation changes",
    "Alert memory tracks priority symbols, deteriorating names, validation queue, risk queue, and alert regime",
    "/smartmoney — upgraded into the Smart Money Command Center",
    "/conviction — upgraded into the Conviction Command Center",
    "/global — upgraded into live-source-aware Global Macro Intelligence",
    "/portfolio — upgraded into evolving portfolio-level intelligence",
    "/defense — upgraded into live-source-aware Defense / AI Warfare Intelligence",
    "/top10 — upgraded into Top 20 Smart Money opportunity ranking",
    "/snapshot — upgraded to use Top 20 intelligence",
    "/brief — upgraded with v1.3 Top Opportunities logic",
    "/stock — upgraded into evolving single-name intelligence",
    "/scorecard — upgraded into score-driver intelligence",
    "/risk — upgraded into risk intelligence",
    "/volume — upgraded into evolving money-flow intelligence",
    "/earnings — upgraded into evolving catalyst intelligence",
    "/analyst — upgraded into evolving Wall Street consensus intelligence",
    "/sec and /filing — upgraded into SEC filing and portfolio-impact intelligence",
    "Command catalog and daily report quality guardrails remain active",
    "Intelligence quality guardrail now validates the v1.3 report stack",
]


REPORT_INTELLIGENCE = [
    "Configurable alert rules for priority scores, validation ranges, score moves, and warning terms",
    "Daily alert digest for short-form monitoring and review",
    "Evolving alert monitor for priority changes, risk deterioration, validation needs, and macro/theme alerts",
    "Executive Smart Money command center",
    "Strict conviction overlap engine",
    "Global macro regime and policy analysis",
    "Portfolio stance and exposure intelligence",
    "Defense, AI warfare, procurement, and geopolitical intelligence",
    "Top-ranked opportunity engine",
    "Single-stock evolving memory",
    "Scorecard, risk, volume, catalyst, analyst, and filing validation layers",
    "Deployment and report-quality guardrails",
]


def now_text() -> str:
    try:
        current = datetime.now(ZoneInfo(REPORT_TIMEZONE))
    except Exception:
        current = datetime.now()

    return current.strftime("%Y-%m-%d %H:%M:%S")


def build_version_header() -> str:
    return (
        f"Smart Money AI Bot {APP_VERSION}\n"
        f"Release: {RELEASE_NAME}\n"
        f"Channel: {RELEASE_CHANNEL}\n"
        f"Status: {RELEASE_STATUS}\n"
        f"Updated: {now_text()}"
    )


def build_version_notes_text() -> str:
    return f"""
🧾 Smart Money AI Version Notes

{build_version_header()}

v1.3 Command Stack
{chr(10).join(f"• {command}" for command in V13_COMMAND_STACK)}

Release Notes
{chr(10).join(f"• {note}" for note in RELEASE_NOTES)}

Intelligence Coverage
{chr(10).join(f"• {item}" for item in REPORT_INTELLIGENCE)}

Production Readiness
• /deploycheck validates deployment health.
• /quality validates the daily report.
• Intelligence guardrails validate the v1.3 report stack.
• Runtime memory/cache files are ignored by git.

Research only. Not financial advice.
""".strip()


def build_version_text() -> str:
    return f"""
🤖 Smart Money AI

{build_version_header()}

Primary Commands
• /smartmoney — command center
• /conviction — strict signal overlap
• /global — macro regime
• /portfolio — exposure/action plan
• /defense — policy/procurement overlay
• /top10 — ranked opportunities
• /brief — daily report

Validation
• /deploycheck
• /quality
• /versionnotes
""".strip()


# Compatibility aliases for older imports.
VERSION = APP_VERSION
VERSION_NAME = RELEASE_NAME
STATUS = RELEASE_STATUS
TIMEZONE = REPORT_TIMEZONE


def get_generated_timestamp() -> str:
    return now_text()


def _run_git_command(args: list[str]) -> str:
    try:
        import subprocess

        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

        output = (result.stdout or "").strip()

        if output:
            return output

    except Exception:
        pass

    return "unknown"


def get_git_branch() -> str:
    return _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])


def get_git_commit() -> str:
    return _run_git_command(["rev-parse", "HEAD"])


def get_git_commit_short() -> str:
    commit = get_git_commit()

    if commit == "unknown":
        return commit

    return commit[:7]


def get_version_metadata() -> dict:
    return {
        "app_version": APP_VERSION,
        "version": APP_VERSION,
        "release_name": RELEASE_NAME,
        "release_channel": RELEASE_CHANNEL,
        "release_status": RELEASE_STATUS,
        "status": RELEASE_STATUS,
        "timezone": REPORT_TIMEZONE,
        "generated_at": get_generated_timestamp(),
        "git_branch": get_git_branch(),
        "git_commit": get_git_commit(),
        "git_commit_short": get_git_commit_short(),
    }


def get_version_notes() -> list[str]:
    return RELEASE_NOTES


def get_release_notes() -> list[str]:
    return RELEASE_NOTES


def get_report_intelligence() -> list[str]:
    return REPORT_INTELLIGENCE