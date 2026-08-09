import os
from typing import Any


ALERT_RULES_VERSION = "v1.4"


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def env_terms(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")

    if not raw.strip():
        return default

    terms = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return terms or default


def get_alert_rules() -> dict[str, Any]:
    return {
        "version": ALERT_RULES_VERSION,

        # Score thresholds
        "priority_score": env_float("ALERT_PRIORITY_SCORE", 82),
        "strong_priority_score": env_float("ALERT_STRONG_PRIORITY_SCORE", 88),
        "validation_min_score": env_float("ALERT_VALIDATION_MIN_SCORE", 65),
        "validation_max_score": env_float("ALERT_VALIDATION_MAX_SCORE", 82),

        # Score movement thresholds
        "score_jump_threshold": env_float("ALERT_SCORE_JUMP_THRESHOLD", 5),
        "score_drop_threshold": env_float("ALERT_SCORE_DROP_THRESHOLD", 5),

        # Regime thresholds
        "critical_alert_count_threshold": env_int("ALERT_CRITICAL_COUNT_THRESHOLD", 3),
        "warning_alert_count_threshold": env_int("ALERT_WARNING_COUNT_THRESHOLD", 5),

        # Term-based rules
        "risk_terms": env_terms(
            "ALERT_RISK_TERMS",
            ["high", "elevated", "speculative", "volatile"],
        ),
        "action_caution_terms": env_terms(
            "ALERT_ACTION_CAUTION_TERMS",
            ["avoid", "reduce", "caution"],
        ),
        "validation_volume_terms": env_terms(
            "ALERT_VALIDATION_VOLUME_TERMS",
            ["weak", "unconfirmed", "thin", "low", "needs"],
        ),
        "validation_signal_terms": env_terms(
            "ALERT_VALIDATION_SIGNAL_TERMS",
            ["developing", "early", "weak"],
        ),
        "filing_warning_terms": env_terms(
            "ALERT_FILING_WARNING_TERMS",
            [
                "going concern",
                "dilution",
                "offering",
                "restatement",
                "material weakness",
                "investigation",
            ],
        ),
        "catalyst_warning_terms": env_terms(
            "ALERT_CATALYST_WARNING_TERMS",
            ["miss", "cut", "lowered", "weak", "delay", "negative"],
        ),
        "analyst_warning_terms": env_terms(
            "ALERT_ANALYST_WARNING_TERMS",
            ["downgrade", "sell", "underperform", "negative"],
        ),
    }


def get_alert_rule_env_map() -> list[tuple[str, str, str]]:
    return [
        ("ALERT_PRIORITY_SCORE", "82", "Minimum score for high-priority alert consideration"),
        ("ALERT_STRONG_PRIORITY_SCORE", "88", "Score that can trigger stronger priority classification"),
        ("ALERT_VALIDATION_MIN_SCORE", "65", "Minimum score for validation queue"),
        ("ALERT_VALIDATION_MAX_SCORE", "82", "Upper score boundary for validation queue"),
        ("ALERT_SCORE_JUMP_THRESHOLD", "5", "Positive score change needed for improvement alert"),
        ("ALERT_SCORE_DROP_THRESHOLD", "5", "Negative score change needed for deterioration alert"),
        ("ALERT_CRITICAL_COUNT_THRESHOLD", "3", "Critical alert count that marks action-required regime"),
        ("ALERT_WARNING_COUNT_THRESHOLD", "5", "Warning alert count that marks risk-control watch"),
        ("ALERT_RISK_TERMS", "high,elevated,speculative,volatile", "Risk labels that trigger risk alerts"),
        ("ALERT_ACTION_CAUTION_TERMS", "avoid,reduce,caution", "Action labels that trigger risk alerts"),
        ("ALERT_VALIDATION_VOLUME_TERMS", "weak,unconfirmed,thin,low,needs", "Volume terms that trigger validation"),
        ("ALERT_VALIDATION_SIGNAL_TERMS", "developing,early,weak", "Signal terms that trigger validation"),
        ("ALERT_FILING_WARNING_TERMS", "going concern,dilution,offering,restatement,material weakness,investigation", "Filing warning terms"),
        ("ALERT_CATALYST_WARNING_TERMS", "miss,cut,lowered,weak,delay,negative", "Catalyst warning terms"),
        ("ALERT_ANALYST_WARNING_TERMS", "downgrade,sell,underperform,negative", "Analyst warning terms"),
    ]


def format_terms(terms: Any, max_items: int = 8) -> str:
    if not isinstance(terms, list):
        return str(terms)

    selected = [str(item) for item in terms[:max_items]]

    if len(terms) > max_items:
        selected.append("...")

    return ", ".join(selected)


def build_alert_rules_summary() -> str:
    rules = get_alert_rules()

    return f"""
Alert Rules Summary
Version: {rules["version"]}

Score Rules
Priority Score: {rules["priority_score"]}
Strong Priority Score: {rules["strong_priority_score"]}
Validation Range: {rules["validation_min_score"]} to {rules["validation_max_score"]}

Movement Rules
Score Jump Alert: +{rules["score_jump_threshold"]}
Score Drop Alert: -{rules["score_drop_threshold"]}

Regime Rules
Action Required: {rules["critical_alert_count_threshold"]}+ critical alerts
Risk-Control Watch: {rules["warning_alert_count_threshold"]}+ warning alerts

Term Rules
Risk Terms: {format_terms(rules["risk_terms"])}
Action Caution Terms: {format_terms(rules["action_caution_terms"])}
Validation Volume Terms: {format_terms(rules["validation_volume_terms"])}
Validation Signal Terms: {format_terms(rules["validation_signal_terms"])}
""".strip()


def build_alert_env_settings_text() -> str:
    lines = ["Environment Overrides"]

    for name, default, description in get_alert_rule_env_map():
        current = os.getenv(name, default)
        lines.append(f"• {name}={current} — {description}")

    return "\n".join(lines)