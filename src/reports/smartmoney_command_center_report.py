from collections import Counter
from typing import Any

from src.intelligence.defense_live_sources import (
    fetch_defense_live_context,
    format_theme_snapshot as format_defense_theme_snapshot,
)
from src.intelligence.global_live_sources import (
    fetch_global_live_context,
    format_theme_snapshot as format_global_theme_snapshot,
)
from src.intelligence.smartmoney_evolution import (
    build_smartmoney_evolution_notes,
    build_smartmoney_memory_summary,
    build_smartmoney_record,
    record_smartmoney_read,
    safe_float,
)
from src.reports.global_intelligence_report import (
    MACRO_SYMBOLS,
    build_macro_regime,
    build_portfolio_impact as build_macro_portfolio_impact,
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


MAX_NAMES = 8
MAX_RANKED = 25


DEFENSE_SYMBOL_HINTS = {
    "LMT",
    "RTX",
    "NOC",
    "GD",
    "BA",
    "HII",
    "LHX",
    "LDOS",
    "KTOS",
    "AVAV",
    "PLTR",
    "MRCY",
    "BWXT",
    "TDY",
    "TXT",
    "CW",
    "HEI",
    "RKLB",
}


DEFENSE_TERMS = [
    "defense",
    "warfare",
    "aerospace",
    "military",
    "missile",
    "munition",
    "munitions",
    "drone",
    "uav",
    "cyber",
    "isr",
    "surveillance",
    "radar",
    "sensor",
    "space",
    "shipbuilding",
    "naval",
    "intelligence",
]


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


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear Smart Money detail available."

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
        ranked = rank_candidates(scores, limit=MAX_RANKED)
    except Exception:
        ranked = sorted(
            [enrich_item(item) for item in scores],
            key=lambda item: item.get("score") if item.get("score") is not None else -999,
            reverse=True,
        )[:MAX_RANKED]

    return [enrich_item(item) for item in ranked]


def is_elevated_risk(item: dict) -> bool:
    risk = str(item.get("risk") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()

    return (
        any(term in risk for term in ["high", "elevated", "speculative", "volatile"])
        or "high risk" in bucket
        or any(term in action for term in ["avoid", "reduce", "caution"])
    )


def needs_confirmation(item: dict) -> bool:
    score = item.get("score")
    signal = str(item.get("signal") or "").lower()
    volume = str(item.get("volume") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()

    if score is not None and score < 75:
        return True

    return (
        "confirmation" in bucket
        or "watch" in action
        or any(term in signal for term in ["developing", "early", "weak"])
        or any(term in volume for term in ["weak", "unconfirmed", "thin", "low", "needs"])
    )


def is_high_conviction(item: dict) -> bool:
    score = item.get("score")
    label = str(item.get("label") or "").lower()
    bucket = str(item.get("bucket") or "").lower()

    return (
        score is not None
        and score >= 80
        and not is_elevated_risk(item)
        and (
            score >= 85
            or "high" in label
            or "prime" in label
            or "best setup" in bucket
        )
    )


def is_defense_candidate(item: dict) -> bool:
    symbol = clean_symbol(item.get("symbol") or item.get("ticker"))

    if symbol in DEFENSE_SYMBOL_HINTS:
        return True

    text = " ".join(
        [
            str(item.get("category") or ""),
            str(item.get("portfolio_fit") or ""),
            str(item.get("label") or ""),
            str(item.get("signal") or ""),
            str(item.get("sector") or ""),
            str(item.get("industry") or ""),
            str(item.get("theme") or ""),
            str(item.get("description") or ""),
            str(item.get("business_summary") or ""),
        ]
    ).lower()

    return any(term in text for term in DEFENSE_TERMS)


def average_score(items: list[dict]) -> float | None:
    values = [
        safe_float(item.get("score"))
        for item in items
        if safe_float(item.get("score")) is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def top_category(ranked: list[dict]) -> str:
    categories = [
        str(item.get("category") or "").strip()
        for item in ranked
        if str(item.get("category") or "").strip()
        and str(item.get("category") or "").lower() not in {"unknown", "n/a", "uncategorized"}
    ]

    if not categories:
        return "Mixed / developing"

    return Counter(categories).most_common(1)[0][0]


def defense_top_theme(defense_context: dict) -> str:
    themes = defense_context.get("themes", []) or []

    if themes:
        return str(themes[0].get("theme") or "Defense / AI warfare")

    return "Defense / AI warfare developing"


def build_command_stance(
    risk_regime: str,
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
) -> str:
    risk_lower = str(risk_regime or "").lower()

    if "risk-off" in risk_lower:
        return "Defense-first / validate everything"

    if len(elevated_risk) >= max(4, len(high_conviction)):
        return "Risk-control command"

    if "risk-on" in risk_lower and len(high_conviction) >= 3:
        return "Selective offense"

    if len(high_conviction) >= 3 and len(confirmation) <= 5:
        return "Opportunity-led / controlled risk"

    if len(confirmation) >= 6:
        return "Watchlist-heavy / confirmation required"

    return "Balanced / selective"


def build_smartmoney_action(command_stance: str, ranked: list[dict], elevated_risk: list[dict], confirmation: list[dict]) -> str:
    if command_stance == "Selective offense" and ranked:
        symbol = ranked[0]["symbol"]
        return f"Start with {symbol}; validate with /volume {symbol}, /risk {symbol}, /earnings {symbol}, /analyst {symbol}, and /filing {symbol}."

    if command_stance == "Opportunity-led / controlled risk" and ranked:
        symbol = ranked[0]["symbol"]
        return f"Prioritize {symbol}, but require confirmation before sizing."

    if command_stance == "Risk-control command" and elevated_risk:
        symbol = elevated_risk[0]["symbol"]
        return f"Risk is the first task. Review /risk {symbol} and /filing {symbol} before chasing any setup."

    if command_stance == "Defense-first / validate everything":
        return "Use /global and /portfolio first. Only act on names with confirmed volume, clean risk, and clear catalyst support."

    if confirmation:
        symbol = confirmation[0]["symbol"]
        return f"Most ideas need confirmation. Start with /volume {symbol} and /filing {symbol}."

    return "Stay selective. Use /top10 for ideas and single-stock commands for validation."


def format_name_line(index: int, item: dict) -> str:
    return (
        f"{index}. {item['symbol']} — {format_score(item.get('score'))} | "
        f"{item.get('label')} | {item.get('bucket')}"
    )


def format_ranked_names(items: list[dict], limit: int = 6) -> str:
    if not items:
        return "• No names available in this bucket."

    lines = []

    for index, item in enumerate(items[:limit], start=1):
        lines.append(format_name_line(index, item))

    return "\n".join(lines)


def format_risk_names(items: list[dict]) -> str:
    if not items:
        return "• No major elevated-risk names detected."

    lines = []

    for item in items[:6]:
        lines.append(
            f"• {item['symbol']}: {item.get('risk')} | {item.get('action')} | {item.get('bucket')}"
        )

    return "\n".join(lines)


def format_confirmation_queue(items: list[dict]) -> str:
    if not items:
        return "• No major confirmation queue detected."

    lines = []

    for item in items[:6]:
        symbol = item["symbol"]
        lines.append(
            f"• {symbol}: /volume {symbol} → /earnings {symbol} → /analyst {symbol} → /filing {symbol}"
        )

    return "\n".join(lines)


def build_signal_summary(
    macro_regime: str,
    risk_regime: str,
    command_stance: str,
    top_theme_name: str,
    defense_theme_name: str,
    avg_score: float | None,
    ranked: list[dict],
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
) -> list[str]:
    return [
        f"Command stance: {command_stance}.",
        f"Macro regime: {macro_regime}.",
        f"Risk regime: {risk_regime}.",
        f"Top stock theme: {top_theme_name}.",
        f"Defense/policy theme: {defense_theme_name}.",
        f"Average ranked score: {format_score(avg_score)}.",
        f"High-conviction names: {len(high_conviction)}; elevated-risk names: {len(elevated_risk)}; confirmation queue: {len(confirmation)}.",
        f"Top idea: {ranked[0]['symbol'] if ranked else 'Unavailable'}.",
    ]


def build_validation_plan(ranked: list[dict], confirmation: list[dict], elevated_risk: list[dict]) -> list[str]:
    plan = []

    if ranked:
        symbol = ranked[0]["symbol"]
        plan.append(f"Top idea validation: /stock {symbol}, /scorecard {symbol}, /volume {symbol}.")

    if confirmation:
        symbol = confirmation[0]["symbol"]
        plan.append(f"First confirmation check: /volume {symbol}, /earnings {symbol}, /analyst {symbol}, /filing {symbol}.")

    if elevated_risk:
        symbol = elevated_risk[0]["symbol"]
        plan.append(f"First risk check: /risk {symbol}, /filing {symbol}.")

    plan.append("Use /global before aggressive sizing and /portfolio before changing exposure.")
    plan.append("Use /top10 for ranked opportunity flow.")

    return plan[:6]


def build_defense_overlay(defense_context: dict, defense_names: list[dict]) -> str:
    lines = []

    lines.append("Official defense themes:")
    lines.append(format_defense_theme_snapshot(defense_context))

    if defense_names:
        names = ", ".join(item["symbol"] for item in defense_names[:6])
        lines.append(f"Scored defense/policy names: {names}.")
    else:
        lines.append("Scored defense/policy names: none detected in the current ranked set.")

    return "\n".join(lines)


def build_next_commands(ranked: list[dict], elevated_risk: list[dict], confirmation: list[dict]) -> str:
    commands = [
        "/global",
        "/portfolio",
        "/defense",
        "/top10",
    ]

    if ranked:
        symbol = ranked[0]["symbol"]
        commands.extend(
            [
                f"/stock {symbol}",
                f"/scorecard {symbol}",
            ]
        )

    if confirmation:
        commands.append(f"/volume {confirmation[0]['symbol']}")

    if elevated_risk:
        commands.append(f"/risk {elevated_risk[0]['symbol']}")

    commands.append("/brief")

    return "\n".join(f"• {command}" for command in commands[:9])


def build_smartmoney_command_center_report(force_refresh: bool = False) -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    ranked = get_ranked_items(scores)

    symbols = list(MACRO_SYMBOLS.keys())
    quotes = get_quote_data(symbols)

    global_context = fetch_global_live_context(force_refresh=force_refresh)
    defense_context = fetch_defense_live_context(force_refresh=force_refresh)

    macro_notes = pressure_notes(quotes, global_context)
    risk_regime = build_risk_regime(quotes, global_context)
    macro_regime = build_macro_regime(quotes, global_context)
    macro_theme_name = global_top_theme(global_context)
    macro_portfolio_impact = build_macro_portfolio_impact(risk_regime, macro_notes)

    avg_score = average_score(ranked)
    high_conviction = [item for item in ranked if is_high_conviction(item)]
    elevated_risk = [item for item in ranked if is_elevated_risk(item)]
    confirmation = [item for item in ranked if needs_confirmation(item)]
    defense_names = [item for item in ranked if is_defense_candidate(item)]

    stock_theme_name = top_category(ranked)
    defense_theme_name = defense_top_theme(defense_context)

    command_stance = build_command_stance(
        risk_regime=risk_regime,
        high_conviction=high_conviction,
        elevated_risk=elevated_risk,
        confirmation=confirmation,
    )

    smartmoney_action = build_smartmoney_action(
        command_stance=command_stance,
        ranked=ranked,
        elevated_risk=elevated_risk,
        confirmation=confirmation,
    )

    top_symbols = [item["symbol"] for item in ranked[:MAX_NAMES]]
    high_risk_symbols = [item["symbol"] for item in elevated_risk[:MAX_NAMES]]
    confirmation_symbols = [item["symbol"] for item in confirmation[:MAX_NAMES]]

    record = build_smartmoney_record(
        command_stance=command_stance,
        macro_regime=macro_regime,
        risk_regime=risk_regime,
        top_theme=stock_theme_name,
        defense_theme=defense_theme_name,
        top_symbols=top_symbols,
        high_risk_symbols=high_risk_symbols,
        confirmation_symbols=confirmation_symbols,
        average_score=avg_score,
        smartmoney_action=smartmoney_action,
    )

    evolution = record_smartmoney_read(record)

    evolution_notes = build_smartmoney_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    return f"""
🧠 Smart Money Command Center

Executive Read
Command Stance: {command_stance}
Macro Regime: {macro_regime}
Risk Regime: {risk_regime}
Macro Portfolio Impact: {macro_portfolio_impact}
Top Stock Theme: {stock_theme_name}
Defense / Policy Theme: {defense_theme_name}
Average Ranked Score: {format_score(avg_score)}

Signal Summary
{bullet_lines(build_signal_summary(
    macro_regime=macro_regime,
    risk_regime=risk_regime,
    command_stance=command_stance,
    top_theme_name=stock_theme_name,
    defense_theme_name=defense_theme_name,
    avg_score=avg_score,
    ranked=ranked,
    high_conviction=high_conviction,
    elevated_risk=elevated_risk,
    confirmation=confirmation,
))}

Global Macro Overlay
{format_global_theme_snapshot(global_context)}

Macro Pressure
{bullet_lines(macro_notes)}

Strongest Smart Money Signals
{format_ranked_names(ranked, limit=6)}

Highest-Risk Names
{format_risk_names(elevated_risk)}

Validation Queue
{format_confirmation_queue(confirmation)}

Defense / Policy Overlay
{build_defense_overlay(defense_context, defense_names)}

Catalyst / Filing / Analyst / Volume Plan
{bullet_lines(build_validation_plan(ranked, confirmation, elevated_risk))}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_smartmoney_memory_summary()}

Smart Money Action
{smartmoney_action}

Next Commands
{build_next_commands(ranked, elevated_risk, confirmation)}

Research only. Not financial advice.
""".strip()