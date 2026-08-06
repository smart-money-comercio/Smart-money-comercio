from typing import Any

from src.intelligence.alert_evolution import (
    build_alert_evolution_notes,
    build_alert_memory_summary,
    build_alert_record,
    get_latest_symbol_state,
    record_alert_scan,
    safe_float,
)
from src.intelligence.defense_live_sources import fetch_defense_live_context
from src.intelligence.global_live_sources import fetch_global_live_context
from src.reports.global_intelligence_report import (
    MACRO_SYMBOLS,
    build_macro_regime,
    build_risk_regime,
    get_quote_data,
    pressure_notes,
    top_theme as global_top_theme,
)
from src.reports.top10_report import classify_action_bucket, rank_candidates
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
)


MAX_REVIEWED = 30
MAX_OUTPUT = 8


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def normalize_score_items(raw_scores: Any) -> list[dict]:
    if isinstance(raw_scores, list):
        return [item for item in raw_scores if isinstance(item, dict)]

    if isinstance(raw_scores, dict):
        if "scores" in raw_scores and isinstance(raw_scores["scores"], list):
            return [item for item in raw_scores["scores"] if isinstance(item, dict)]

        items = []

        for key, value in raw_scores.items():
            if isinstance(value, dict):
                copy = dict(value)
                copy.setdefault("ticker", key)
                copy.setdefault("symbol", key)
                items.append(copy)
            else:
                items.append(
                    {
                        "ticker": key,
                        "symbol": key,
                        "score": value,
                    }
                )

        return items

    return []


def get_score_value(item: dict) -> float | None:
    for key in [
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        value = safe_float(item.get(key))

        if value is not None:
            return value

    return None


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.0f}/100"


def format_delta(value: float | None) -> str:
    if value is None:
        return "N/A"

    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}"


def compact_text(value: Any, max_chars: int = 130) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No alert detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def safe_label(func, item: dict, fallback: str) -> str:
    try:
        value = func(item)
        return str(value or fallback)
    except Exception:
        return fallback


def enrich_item(item: dict) -> dict:
    copy = dict(item)

    symbol = clean_symbol(get_ticker(copy) or copy.get("symbol") or copy.get("ticker"))
    score = get_score_value(copy)

    copy["symbol"] = symbol
    copy["ticker"] = symbol
    copy["score"] = score
    copy["label"] = safe_label(get_smart_money_label, copy, "Signal developing")
    copy["signal"] = safe_label(get_signal_strength, copy, copy["label"])
    copy["risk"] = safe_label(get_risk_label, copy, "Unknown")
    copy["action"] = safe_label(get_action_label, copy, "Watch")
    copy["category"] = safe_label(get_category, copy, "Uncategorized")
    copy["portfolio_fit"] = safe_label(get_portfolio_fit, copy, "Unknown")
    copy["volume"] = safe_label(get_volume_label, copy, "Volume confirmation unavailable")

    try:
        ranked_item = rank_candidates([copy], limit=1)[0]
        copy["bucket"] = classify_action_bucket(ranked_item)
    except Exception:
        copy["bucket"] = "Watch for Confirmation"

    return copy


def get_ranked_items(scores: list[dict]) -> list[dict]:
    try:
        ranked = rank_candidates(scores, limit=MAX_REVIEWED)
    except Exception:
        ranked = sorted(
            [enrich_item(item) for item in scores],
            key=lambda item: item.get("score") if item.get("score") is not None else -999,
            reverse=True,
        )[:MAX_REVIEWED]

    return [enrich_item(item) for item in ranked]


def is_high_priority(item: dict) -> bool:
    score = safe_float(item.get("score"), 0) or 0
    risk = str(item.get("risk") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    label = str(item.get("label") or "").lower()

    return (
        score >= 82
        and "high risk" not in bucket
        and not any(term in risk for term in ["high", "elevated", "speculative"])
        and (
            score >= 88
            or "high" in label
            or "prime" in label
            or "best setup" in bucket
        )
    )


def is_risk_alert(item: dict) -> bool:
    risk = str(item.get("risk") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()

    return (
        any(term in risk for term in ["high", "elevated", "speculative", "volatile"])
        or "high risk" in bucket
        or any(term in action for term in ["avoid", "reduce", "caution"])
    )


def needs_validation(item: dict) -> bool:
    score = safe_float(item.get("score"), 0) or 0
    volume = str(item.get("volume") or "").lower()
    signal = str(item.get("signal") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()

    return (
        65 <= score < 82
        or "confirmation" in bucket
        or "watch" in action
        or any(term in volume for term in ["weak", "unconfirmed", "thin", "low", "needs"])
        or any(term in signal for term in ["developing", "early", "weak"])
    )


def warning_text(item: dict) -> str:
    text = " ".join(
        [
            str(item.get("filing_context", "")),
            str(item.get("sec_context", "")),
            str(item.get("filing_summary", "")),
            str(item.get("sec_summary", "")),
            str(item.get("risk_factors", "")),
            str(item.get("disclosures", "")),
            str(item.get("earnings_summary", "")),
            str(item.get("catalyst", "")),
            str(item.get("analyst_summary", "")),
            str(item.get("volume", "")),
        ]
    ).lower()

    warnings = []

    if any(term in text for term in ["going concern", "dilution", "offering", "restatement", "material weakness", "investigation"]):
        warnings.append("filing/disclosure warning")

    if any(term in text for term in ["miss", "cut", "lowered", "weak", "delay", "negative"]):
        warnings.append("catalyst warning")

    if any(term in text for term in ["weak", "unconfirmed", "low volume", "thin"]):
        warnings.append("volume warning")

    if any(term in text for term in ["downgrade", "sell", "underperform", "negative"]):
        warnings.append("analyst warning")

    return ", ".join(warnings)


def build_symbol_state(items: list[dict]) -> dict[str, dict]:
    state = {}

    for item in items:
        symbol = item["symbol"]

        state[symbol] = {
            "score": item.get("score"),
            "risk": item.get("risk"),
            "action": item.get("action"),
            "bucket": item.get("bucket"),
            "label": item.get("label"),
            "volume": item.get("volume"),
            "high_priority": is_high_priority(item),
            "risk_alert": is_risk_alert(item),
            "validation": needs_validation(item),
            "warning_text": warning_text(item),
        }

    return state


def score_delta(symbol: str, previous_state: dict[str, dict], current_item: dict) -> float | None:
    previous = previous_state.get(symbol, {})

    if not isinstance(previous, dict):
        return None

    previous_score = safe_float(previous.get("score"))
    current_score = safe_float(current_item.get("score"))

    if previous_score is None or current_score is None:
        return None

    return current_score - previous_score


def detect_alerts(items: list[dict], previous_state: dict[str, dict]) -> list[dict]:
    alerts = []

    for item in items:
        symbol = item["symbol"]
        delta = score_delta(symbol, previous_state, item)
        previous = previous_state.get(symbol, {}) if isinstance(previous_state, dict) else {}
        was_high_priority = bool(previous.get("high_priority")) if isinstance(previous, dict) else False

        reasons = []
        severity = "info"

        if is_high_priority(item) and not was_high_priority:
            severity = "critical"
            reasons.append("new high-priority setup")

        if delta is not None and delta >= 5:
            severity = "critical" if severity != "critical" else severity
            reasons.append(f"score improved {format_delta(delta)}")

        if delta is not None and delta <= -5:
            severity = "warning"
            reasons.append(f"score deteriorated {format_delta(delta)}")

        if is_risk_alert(item):
            severity = "warning" if severity != "critical" else severity
            reasons.append("risk elevated")

        if needs_validation(item):
            reasons.append("needs validation")

        warning = warning_text(item)

        if warning:
            severity = "warning" if severity != "critical" else severity
            reasons.append(warning)

        if not reasons:
            continue

        alerts.append(
            {
                "symbol": symbol,
                "severity": severity,
                "score": item.get("score"),
                "risk": item.get("risk"),
                "bucket": item.get("bucket"),
                "action": item.get("action"),
                "reasons": reasons[:4],
                "delta": delta,
            }
        )

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(
        key=lambda alert: (
            severity_rank.get(alert["severity"], 9),
            -(safe_float(alert.get("score"), 0) or 0),
        )
    )

    return alerts


def build_macro_alerts(risk_regime: str, macro_regime: str, macro_notes: list[str], global_context: dict, defense_context: dict) -> list[str]:
    alerts = []

    risk_lower = str(risk_regime or "").lower()

    if "risk-off" in risk_lower:
        alerts.append("Macro alert: risk-off regime active; reduce chase behavior and require confirmation.")

    elif "cautious" in risk_lower:
        alerts.append("Macro alert: cautious regime active; validation matters more than ranking.")

    themes = " ".join(
        [
            str(item.get("theme") or "")
            for item in (global_context.get("themes", []) or []) + (defense_context.get("themes", []) or [])
        ]
    ).lower()

    if "geopolitical" in themes:
        alerts.append("Theme alert: geopolitical pressure is active.")

    if "defense" in themes:
        alerts.append("Theme alert: defense/policy context is active.")

    if "fed" in themes or "rates" in themes:
        alerts.append("Theme alert: Fed/rates pressure is active.")

    if "inflation" in themes or "energy" in themes:
        alerts.append("Theme alert: inflation/energy pressure is active.")

    for note in macro_notes[:3]:
        if "No major" not in note:
            alerts.append(f"Macro pressure: {note}")

    if not alerts:
        alerts.append(f"Macro regime: {macro_regime}. No critical macro alert detected.")

    return alerts[:7]


def build_alert_regime(critical_count: int, warning_count: int, risk_regime: str) -> str:
    if critical_count >= 3:
        return "Action required / multiple critical alerts"

    if critical_count >= 1:
        return "Priority review"

    if warning_count >= 5:
        return "Risk-control watch"

    if "risk-off" in str(risk_regime or "").lower():
        return "Macro defensive watch"

    if warning_count >= 1:
        return "Monitor closely"

    return "Quiet / normal monitoring"


def format_alert_line(alert: dict) -> str:
    reasons = "; ".join(alert.get("reasons", [])[:4])

    return (
        f"• {alert['symbol']} — {alert['severity'].upper()} | "
        f"{format_score(alert.get('score'))} | {alert.get('bucket')} | "
        f"{compact_text(reasons, 170)}"
    )


def format_alerts(alerts: list[dict], severity: str | None = None, limit: int = MAX_OUTPUT) -> str:
    selected = [
        alert
        for alert in alerts
        if severity is None or alert.get("severity") == severity
    ]

    if not selected:
        return "• No alerts in this bucket."

    return "\n".join(format_alert_line(alert) for alert in selected[:limit])


def format_validation_queue(items: list[dict]) -> str:
    validation = [item for item in items if needs_validation(item)]

    if not validation:
        return "• No major validation queue."

    lines = []

    for item in validation[:MAX_OUTPUT]:
        symbol = item["symbol"]
        lines.append(
            f"• {symbol}: /volume {symbol} → /earnings {symbol} → /analyst {symbol} → /filing {symbol}"
        )

    return "\n".join(lines)


def format_risk_queue(items: list[dict]) -> str:
    risk_items = [item for item in items if is_risk_alert(item)]

    if not risk_items:
        return "• No major risk-control queue."

    lines = []

    for item in risk_items[:MAX_OUTPUT]:
        symbol = item["symbol"]
        lines.append(
            f"• {symbol}: {item.get('risk')} | {item.get('action')} | /risk {symbol} → /filing {symbol}"
        )

    return "\n".join(lines)


def build_alert_action(alert_regime: str, alerts: list[dict], items: list[dict]) -> str:
    critical = [alert for alert in alerts if alert.get("severity") == "critical"]
    warning = [alert for alert in alerts if alert.get("severity") == "warning"]

    if critical:
        symbol = critical[0]["symbol"]
        return f"Start with {symbol}. Run /stock {symbol}, /volume {symbol}, /risk {symbol}, and /filing {symbol}."

    if warning:
        symbol = warning[0]["symbol"]
        return f"Review warning first: /risk {symbol} and /filing {symbol}."

    if items:
        symbol = items[0]["symbol"]
        return f"No urgent alert. Monitor top-ranked name {symbol} with /stock {symbol} and /scorecard {symbol}."

    return "No actionable alert. Use /smartmoney and /portfolio for broader review."


def build_next_commands(alerts: list[dict], items: list[dict]) -> str:
    commands = [
        "/smartmoney",
        "/conviction",
        "/portfolio",
        "/global",
    ]

    target = alerts[0]["symbol"] if alerts else items[0]["symbol"] if items else ""

    if target:
        commands.extend(
            [
                f"/stock {target}",
                f"/volume {target}",
                f"/risk {target}",
                f"/filing {target}",
            ]
        )

    commands.append("/brief")

    return "\n".join(f"• {command}" for command in commands[:9])


def build_alert_monitor_report(force_refresh: bool = False) -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    ranked = get_ranked_items(scores)

    global_context = fetch_global_live_context(force_refresh=force_refresh)
    defense_context = fetch_defense_live_context(force_refresh=force_refresh)

    quotes = get_quote_data(list(MACRO_SYMBOLS.keys()))
    risk_regime = build_risk_regime(quotes, global_context)
    macro_regime = build_macro_regime(quotes, global_context)
    macro_theme = global_top_theme(global_context)
    macro_notes = pressure_notes(quotes, global_context)

    previous_state = get_latest_symbol_state()
    current_state = build_symbol_state(ranked)
    alerts = detect_alerts(ranked, previous_state)

    critical_alerts = [alert for alert in alerts if alert.get("severity") == "critical"]
    warning_alerts = [alert for alert in alerts if alert.get("severity") == "warning"]

    high_priority = [item for item in ranked if is_high_priority(item)]
    validation = [item for item in ranked if needs_validation(item)]
    risk_items = [item for item in ranked if is_risk_alert(item)]

    new_priority_symbols = [
        alert["symbol"]
        for alert in critical_alerts
        if "new high-priority setup" in " ".join(alert.get("reasons", []))
    ]

    deteriorating_symbols = [
        alert["symbol"]
        for alert in warning_alerts
        if "score deteriorated" in " ".join(alert.get("reasons", []))
    ]

    alert_regime = build_alert_regime(
        critical_count=len(critical_alerts),
        warning_count=len(warning_alerts),
        risk_regime=risk_regime,
    )

    record = build_alert_record(
        alert_regime=alert_regime,
        macro_regime=macro_regime,
        risk_regime=risk_regime,
        highest_priority_symbols=[item["symbol"] for item in high_priority[:MAX_OUTPUT]],
        new_priority_symbols=new_priority_symbols[:MAX_OUTPUT],
        deteriorating_symbols=deteriorating_symbols[:MAX_OUTPUT],
        validation_symbols=[item["symbol"] for item in validation[:MAX_OUTPUT]],
        risk_symbols=[item["symbol"] for item in risk_items[:MAX_OUTPUT]],
        alert_count=len(alerts),
        critical_count=len(critical_alerts),
        warning_count=len(warning_alerts),
    )

    evolution = record_alert_scan(record, current_state)

    evolution_notes = build_alert_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    macro_alerts = build_macro_alerts(
        risk_regime=risk_regime,
        macro_regime=macro_regime,
        macro_notes=macro_notes,
        global_context=global_context,
        defense_context=defense_context,
    )

    return f"""
🚨 Alert Monitor

Executive Read
Alert Regime: {alert_regime}
Macro Regime: {macro_regime}
Risk Regime: {risk_regime}
Macro Theme: {macro_theme}
Total Alerts: {len(alerts)}
Critical Alerts: {len(critical_alerts)}
Warning Alerts: {len(warning_alerts)}
Validation Queue: {len(validation)}
Risk-Control Queue: {len(risk_items)}

Critical Alerts
{format_alerts(alerts, severity="critical")}

Warning Alerts
{format_alerts(alerts, severity="warning")}

Macro / Theme Alerts
{bullet_lines(macro_alerts)}

Validation Queue
{format_validation_queue(ranked)}

Risk-Control Queue
{format_risk_queue(ranked)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_alert_memory_summary()}

Alert Action
{build_alert_action(alert_regime, alerts, ranked)}

Next Commands
{build_next_commands(alerts, ranked)}

Research only. Not financial advice.
""".strip()