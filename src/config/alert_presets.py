from typing import Any

from src.config.alert_rules import get_alert_rules


ALERT_PRESETS_VERSION = "v1.4"


ALERT_PRESETS = {
    "conservative": {
        "description": "Fewer alerts, stricter conviction threshold, faster risk-control posture.",
        "env": {
            "ALERT_PRIORITY_SCORE": "88",
            "ALERT_STRONG_PRIORITY_SCORE": "92",
            "ALERT_VALIDATION_MIN_SCORE": "70",
            "ALERT_VALIDATION_MAX_SCORE": "86",
            "ALERT_SCORE_JUMP_THRESHOLD": "7",
            "ALERT_SCORE_DROP_THRESHOLD": "4",
            "ALERT_CRITICAL_COUNT_THRESHOLD": "2",
            "ALERT_WARNING_COUNT_THRESHOLD": "3",
            "ALERT_RISK_TERMS": "high,elevated,speculative,volatile,unstable",
            "ALERT_ACTION_CAUTION_TERMS": "avoid,reduce,caution,trim,wait",
            "ALERT_VALIDATION_VOLUME_TERMS": "weak,unconfirmed,thin,low,needs,fading",
            "ALERT_VALIDATION_SIGNAL_TERMS": "developing,early,weak,mixed",
        },
    },
    "balanced": {
        "description": "Default v1.4 monitoring posture. Good balance between opportunity and risk alerts.",
        "env": {
            "ALERT_PRIORITY_SCORE": "82",
            "ALERT_STRONG_PRIORITY_SCORE": "88",
            "ALERT_VALIDATION_MIN_SCORE": "65",
            "ALERT_VALIDATION_MAX_SCORE": "82",
            "ALERT_SCORE_JUMP_THRESHOLD": "5",
            "ALERT_SCORE_DROP_THRESHOLD": "5",
            "ALERT_CRITICAL_COUNT_THRESHOLD": "3",
            "ALERT_WARNING_COUNT_THRESHOLD": "5",
            "ALERT_RISK_TERMS": "high,elevated,speculative,volatile",
            "ALERT_ACTION_CAUTION_TERMS": "avoid,reduce,caution",
            "ALERT_VALIDATION_VOLUME_TERMS": "weak,unconfirmed,thin,low,needs",
            "ALERT_VALIDATION_SIGNAL_TERMS": "developing,early,weak",
        },
    },
    "aggressive": {
        "description": "More opportunity alerts, lower priority threshold, wider validation queue.",
        "env": {
            "ALERT_PRIORITY_SCORE": "76",
            "ALERT_STRONG_PRIORITY_SCORE": "84",
            "ALERT_VALIDATION_MIN_SCORE": "55",
            "ALERT_VALIDATION_MAX_SCORE": "80",
            "ALERT_SCORE_JUMP_THRESHOLD": "4",
            "ALERT_SCORE_DROP_THRESHOLD": "7",
            "ALERT_CRITICAL_COUNT_THRESHOLD": "4",
            "ALERT_WARNING_COUNT_THRESHOLD": "7",
            "ALERT_RISK_TERMS": "high,elevated,speculative",
            "ALERT_ACTION_CAUTION_TERMS": "avoid,reduce,caution",
            "ALERT_VALIDATION_VOLUME_TERMS": "weak,unconfirmed,thin,low,needs",
            "ALERT_VALIDATION_SIGNAL_TERMS": "developing,early,weak",
        },
    },
}


RULE_KEY_TO_ENV = {
    "priority_score": "ALERT_PRIORITY_SCORE",
    "strong_priority_score": "ALERT_STRONG_PRIORITY_SCORE",
    "validation_min_score": "ALERT_VALIDATION_MIN_SCORE",
    "validation_max_score": "ALERT_VALIDATION_MAX_SCORE",
    "score_jump_threshold": "ALERT_SCORE_JUMP_THRESHOLD",
    "score_drop_threshold": "ALERT_SCORE_DROP_THRESHOLD",
    "critical_alert_count_threshold": "ALERT_CRITICAL_COUNT_THRESHOLD",
    "warning_alert_count_threshold": "ALERT_WARNING_COUNT_THRESHOLD",
    "risk_terms": "ALERT_RISK_TERMS",
    "action_caution_terms": "ALERT_ACTION_CAUTION_TERMS",
    "validation_volume_terms": "ALERT_VALIDATION_VOLUME_TERMS",
    "validation_signal_terms": "ALERT_VALIDATION_SIGNAL_TERMS",
}


def normalize_preset_name(value: str) -> str:
    return str(value or "").strip().lower()


def get_alert_preset_names() -> list[str]:
    return list(ALERT_PRESETS.keys())


def get_alert_preset(name: str) -> dict[str, Any] | None:
    return ALERT_PRESETS.get(normalize_preset_name(name))


def stringify_rule_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item).strip().lower() for item in value)

    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)

    return str(value)


def detect_current_preset() -> str:
    rules = get_alert_rules()

    current_env_shape = {}

    for rule_key, env_name in RULE_KEY_TO_ENV.items():
        if rule_key not in rules:
            continue

        current_env_shape[env_name] = stringify_rule_value(rules.get(rule_key))

    for preset_name, preset in ALERT_PRESETS.items():
        preset_env = preset.get("env", {})

        matched = True

        for env_name, preset_value in preset_env.items():
            current_value = current_env_shape.get(env_name)

            if current_value != str(preset_value):
                matched = False
                break

        if matched:
            return preset_name

    return "custom"


def build_preset_env_block(name: str) -> str:
    preset = get_alert_preset(name)

    if not preset:
        return ""

    lines = []

    for key, value in preset.get("env", {}).items():
        lines.append(f"{key}={value}")

    return "\n".join(lines)


def build_available_presets_text() -> str:
    lines = ["Available Presets"]

    for name, preset in ALERT_PRESETS.items():
        lines.append(f"• {name}: {preset.get('description', '')}")

    return "\n".join(lines)