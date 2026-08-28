from src.config.alert_rules import (
    build_alert_env_settings_text,
    build_alert_rules_summary,
    get_alert_rules,
)
from src.intelligence.alert_evolution import load_alert_memory
from src.reports.alert_news_bridge import build_alertstatus_news_summary


def latest_record() -> dict:
    memory = load_alert_memory()
    records = memory.get("records", [])

    if isinstance(records, list) and records:
        latest = records[-1]
        if isinstance(latest, dict):
            return latest

    return {}


def format_symbol_list(items, fallback: str = "None") -> str:
    if not items:
        return fallback

    return ", ".join(str(item).upper() for item in items[:10])


def build_alertstatus_report() -> str:
    record = latest_record()
    news_summary = build_alertstatus_news_summary()
    rules = get_alert_rules()

    if not record:
        return f"""
🚨 Alert Status

Status: No alert scan recorded yet.
Rules Version: {rules.get("version", "unknown")}

News Intelligence
{news_summary}

Run:
/alerts
/dailyalerts

Then use /alertstatus again.

Research only. Not financial advice.
""".strip()

    return f"""
🚨 Alert Status

Current State
Last Scan: {record.get("checked_at", "unknown")}
Alert Regime: {record.get("alert_regime", "unknown")}
Macro Regime: {record.get("macro_regime", "unknown")}
Risk Regime: {record.get("risk_regime", "unknown")}

News Intelligence
{news_summary}

Alert Counts
Total Alerts: {record.get("alert_count", 0)}
Critical Alerts: {record.get("critical_count", 0)}
Warning Alerts: {record.get("warning_count", 0)}

Queues
Highest Priority: {format_symbol_list(record.get("highest_priority_symbols", []))}
New Priority: {format_symbol_list(record.get("new_priority_symbols", []))}
Deteriorating: {format_symbol_list(record.get("deteriorating_symbols", []))}
Validation: {format_symbol_list(record.get("validation_symbols", []))}
Risk-Control: {format_symbol_list(record.get("risk_symbols", []))}

Rules Snapshot
Priority Score: {rules.get("priority_score")}
Strong Priority Score: {rules.get("strong_priority_score")}
Validation Range: {rules.get("validation_min_score")} to {rules.get("validation_max_score")}
Score Jump Alert: +{rules.get("score_jump_threshold")}
Score Drop Alert: -{rules.get("score_drop_threshold")}

Use:
/alerts
/dailyalerts
/alertrules

Research only. Not financial advice.
""".strip()


def build_alertrules_report() -> str:
    news_summary = build_alertstatus_news_summary()

    return f"""
⚙️ Alert Rules

News Intelligence
{news_summary}

{build_alert_rules_summary()}

{build_alert_env_settings_text()}

How to use
• /alerts uses these thresholds for full monitoring.
• /dailyalerts uses the same engine in compressed form.
• /alertstatus shows the latest recorded alert state.
• Environment overrides require bot restart/redeploy.

Research only. Not financial advice.
""".strip()