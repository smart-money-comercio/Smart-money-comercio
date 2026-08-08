from typing import Any

from src.reports.alert_monitor_report import build_alert_monitor_report


SECTION_TITLES = [
    "Executive Read",
    "Critical Alerts",
    "Warning Alerts",
    "Macro / Theme Alerts",
    "Validation Queue",
    "Risk-Control Queue",
    "What Changed",
    "Evolving Analysis",
    "Alert Action",
    "Next Commands",
]


def compact_text(value: Any, max_chars: int = 280) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def extract_section(report: str, title: str) -> str:
    lines = str(report or "").splitlines()
    collecting = False
    collected = []

    for line in lines:
        clean = line.strip()

        if clean == title:
            collecting = True
            continue

        if collecting and clean in SECTION_TITLES:
            break

        if collecting:
            collected.append(line)

    return "\n".join(collected).strip()


def extract_field(section: str, field: str, fallback: str = "Unavailable") -> str:
    prefix = f"{field}:"

    for line in str(section or "").splitlines():
        clean = line.strip()

        if clean.startswith(prefix):
            return clean.split(":", 1)[1].strip() or fallback

    return fallback


def select_digest_lines(section: str, limit: int = 4) -> str:
    lines = []

    for line in str(section or "").splitlines():
        clean = line.strip()

        if not clean:
            continue

        if clean.startswith("•"):
            lines.append(clean)
        elif " — " in clean or clean.upper().startswith(("CRITICAL", "WARNING")):
            lines.append(f"• {clean}")
        elif clean.startswith("/"):
            lines.append(f"• {clean}")

        if len(lines) >= limit:
            break

    if not lines:
        return "• No items in this bucket."

    return "\n".join(lines)


def select_action(section: str) -> str:
    text = compact_text(section, 360)

    if not text:
        return "No immediate action. Review /alerts for the full monitor."

    return text


def build_daily_alert_digest_report(force_refresh: bool = False) -> str:
    full_report = build_alert_monitor_report(force_refresh=force_refresh)

    executive = extract_section(full_report, "Executive Read")
    critical = extract_section(full_report, "Critical Alerts")
    warnings = extract_section(full_report, "Warning Alerts")
    macro = extract_section(full_report, "Macro / Theme Alerts")
    changed = extract_section(full_report, "What Changed")
    action = extract_section(full_report, "Alert Action")
    commands = extract_section(full_report, "Next Commands")

    alert_regime = extract_field(executive, "Alert Regime")
    macro_regime = extract_field(executive, "Macro Regime")
    risk_regime = extract_field(executive, "Risk Regime")
    critical_count = extract_field(executive, "Critical Alerts", "0")
    warning_count = extract_field(executive, "Warning Alerts", "0")
    validation_count = extract_field(executive, "Validation Queue", "0")
    risk_count = extract_field(executive, "Risk-Control Queue", "0")

    return f"""
🚨 Daily Alert Digest

Priority
Alert Regime: {alert_regime}
Macro Regime: {macro_regime}
Risk Regime: {risk_regime}
Critical: {critical_count}
Warnings: {warning_count}
Validation Queue: {validation_count}
Risk-Control Queue: {risk_count}

Critical Changes
{select_digest_lines(critical, limit=4)}

Warnings
{select_digest_lines(warnings, limit=4)}

Macro / Theme
{select_digest_lines(macro, limit=4)}

What Changed
{select_digest_lines(changed, limit=4)}

First Action
{select_action(action)}

Next Commands
{select_digest_lines(commands, limit=6)}

Use /alerts for the full monitor.

Research only. Not financial advice.
""".strip()