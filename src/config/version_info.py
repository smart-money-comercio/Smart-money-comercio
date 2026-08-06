import os
from datetime import datetime
from zoneinfo import ZoneInfo


APP_VERSION = os.getenv("SMART_MONEY_VERSION", "v1.3")
RELEASE_NAME = os.getenv("SMART_MONEY_RELEASE_NAME", "Intelligence Quality Upgrade")
RELEASE_CHANNEL = os.getenv("SMART_MONEY_RELEASE_CHANNEL", "Production")
RELEASE_STATUS = "Stable"
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")


V13_COMMAND_STACK = [
    "/smartmoney",
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