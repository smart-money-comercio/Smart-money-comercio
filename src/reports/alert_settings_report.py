import os
from typing import Any

from src.config.alert_presets import (
    ALERT_PRESETS_VERSION,
    build_available_presets_text,
    build_preset_env_block,
    detect_current_preset,
    get_alert_preset,
    get_alert_preset_names,
    normalize_preset_name,
)
from src.config.alert_rules import (
    build_alert_rules_summary,
    get_alert_rule_env_map,
    get_alert_rules,
)


def format_terms(value: Any, max_items: int = 10) -> str:
    if not isinstance(value, list):
        return str(value)

    items = [str(item) for item in value[:max_items]]

    if len(value) > max_items:
        items.append("...")

    return ", ".join(items)


def build_override_status_lines() -> str:
    lines = []

    for name, default, description in get_alert_rule_env_map():
        current = os.getenv(name)

        if current is None:
            lines.append(f"• {name}: default {default} — {description}")
        else:
            lines.append(f"• {name}: override {current} — {description}")

    return "\n".join(lines)


def build_alertsettings_report() -> str:
    rules = get_alert_rules()
    preset = detect_current_preset()

    return f"""
⚙️ Alert Settings

Current Mode
Detected Preset: {preset}
Rules Version: {rules.get("version", "unknown")}
Presets Version: {ALERT_PRESETS_VERSION}

Active Thresholds
Priority Score: {rules.get("priority_score")}
Strong Priority Score: {rules.get("strong_priority_score")}
Validation Range: {rules.get("validation_min_score")} to {rules.get("validation_max_score")}
Score Jump Alert: +{rules.get("score_jump_threshold")}
Score Drop Alert: -{rules.get("score_drop_threshold")}
Action Required: {rules.get("critical_alert_count_threshold")}+ critical alerts
Risk-Control Watch: {rules.get("warning_alert_count_threshold")}+ warning alerts

Active Terms
Risk Terms: {format_terms(rules.get("risk_terms", []))}
Action Caution Terms: {format_terms(rules.get("action_caution_terms", []))}
Validation Volume Terms: {format_terms(rules.get("validation_volume_terms", []))}
Validation Signal Terms: {format_terms(rules.get("validation_signal_terms", []))}

Environment Status
{build_override_status_lines()}

Use:
/alertpreset conservative
/alertpreset balanced
/alertpreset aggressive
/alertrules
/alertstatus
/alerts

Research only. Not financial advice.
""".strip()


def build_alertpreset_report(preset_name: str = "") -> str:
    preset_name = normalize_preset_name(preset_name)

    if not preset_name:
        return f"""
⚙️ Alert Presets

Usage:
/alertpreset conservative
/alertpreset balanced
/alertpreset aggressive

{build_available_presets_text()}

These commands show the environment overrides to apply. They do not mutate production settings from Telegram.

Research only. Not financial advice.
""".strip()

    preset = get_alert_preset(preset_name)

    if not preset:
        names = ", ".join(get_alert_preset_names())

        return f"""
⚙️ Alert Preset

Unknown preset: {preset_name}

Available presets:
{names}

Usage:
/alertpreset conservative
/alertpreset balanced
/alertpreset aggressive
""".strip()

    env_block = build_preset_env_block(preset_name)

    return f"""
⚙️ Alert Preset: {preset_name}

Description
{preset.get("description", "")}

Environment Overrides
{env_block}

How to Apply
1. Add or update these values in your .env file.
2. Redeploy or restart the bot.
3. Run /alertsettings to confirm the active mode.
4. Run /alerts or /dailyalerts to review the new alert behavior.

Server note
These presets are intentionally read-only from Telegram for now. That prevents accidental production threshold changes.

Research only. Not financial advice.
""".strip()