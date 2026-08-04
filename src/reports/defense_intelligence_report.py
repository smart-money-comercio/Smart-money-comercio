from collections import Counter
from typing import Any

from src.intelligence.defense_evolution import (
    build_defense_evolution_notes,
    build_defense_memory_summary,
    build_defense_record,
    record_defense_read,
    safe_float,
)
from src.intelligence.defense_live_sources import (
    build_live_context_summary,
    fetch_defense_live_context,
    format_source_snapshot,
    format_theme_snapshot,
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


MAX_DEFENSE_NAMES = 10
MAX_REPORT_CANDIDATES = 30


DEFENSE_CATEGORY_TERMS = [
    "defense",
    "warfare",
    "aerospace",
    "military",
    "munition",
    "munitions",
    "missile",
    "missiles",
    "air defense",
    "security",
    "cyber",
    "drone",
    "drones",
    "uav",
    "counter-drone",
    "autonomous",
    "isr",
    "surveillance",
    "radar",
    "sensor",
    "sensors",
    "space",
    "shipbuilding",
    "naval",
    "intelligence",
]


DEFENSE_COMPANY_HINTS = [
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
    "AI",
    "SOUN",
    "MRCY",
    "BWXT",
    "TDY",
    "TXT",
    "CW",
    "HEI",
    "RKLB",
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
        return "• No clear defense detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def safe_label(func, item: dict, fallback: str) -> str:
    try:
        value = func(item)
        return str(value or fallback)
    except Exception:
        return fallback


def defense_text(item: dict) -> str:
    fields = [
        get_ticker(item),
        item.get("symbol"),
        item.get("ticker"),
        get_category(item),
        get_portfolio_fit(item),
        get_smart_money_label(item),
        item.get("sector"),
        item.get("industry"),
        item.get("theme"),
        item.get("themes"),
        item.get("description"),
        item.get("business_summary"),
        item.get("summary"),
    ]

    return " ".join(str(value or "") for value in fields).lower()


def is_defense_candidate(item: dict) -> bool:
    symbol = clean_symbol(get_ticker(item) or item.get("symbol") or item.get("ticker"))

    if symbol in DEFENSE_COMPANY_HINTS:
        return True

    text = defense_text(item)

    return any(term in text for term in DEFENSE_CATEGORY_TERMS)


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


def get_ranked_defense_items(scores: list[dict]) -> list[dict]:
    candidates = [item for item in scores if is_defense_candidate(item)]

    if not candidates:
        candidates = [
            item
            for item in scores
            if clean_symbol(get_ticker(item) or item.get("symbol") or item.get("ticker")) in DEFENSE_COMPANY_HINTS
        ]

    try:
        ranked = rank_candidates(candidates, limit=MAX_REPORT_CANDIDATES)
    except Exception:
        ranked = sorted(
            [enrich_item(item) for item in candidates],
            key=lambda item: item.get("score") if item.get("score") is not None else -999,
            reverse=True,
        )[:MAX_REPORT_CANDIDATES]

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
    volume = str(item.get("volume") or "").lower()
    signal = str(item.get("signal") or "").lower()
    bucket = str(item.get("bucket") or "").lower()
    action = str(item.get("action") or "").lower()

    if score is not None and score < 75:
        return True

    return (
        any(term in volume for term in ["weak", "unconfirmed", "low", "thin", "needs"])
        or any(term in signal for term in ["developing", "early", "weak"])
        or "confirmation" in bucket
        or "watch" in action
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
            "high" in label
            or "prime" in label
            or "best setup" in bucket
            or score >= 85
        )
    )


def average_score(items: list[dict]) -> float | None:
    values = [
        safe_float(item.get("score"))
        for item in items
        if safe_float(item.get("score")) is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def top_defense_theme(live_context: dict, ranked: list[dict]) -> str:
    themes = live_context.get("themes", []) or []

    if themes:
        return str(themes[0].get("theme") or "Defense / AI warfare")

    categories = [
        str(item.get("category") or "").strip()
        for item in ranked
        if str(item.get("category") or "").strip()
        and str(item.get("category") or "").lower() not in {"unknown", "n/a", "uncategorized"}
    ]

    if categories:
        return Counter(categories).most_common(1)[0][0]

    return "Defense / AI warfare"


def build_defense_stance(
    ranked: list[dict],
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
    live_context: dict,
) -> str:
    item_count = int(live_context.get("item_count", 0) or 0)

    if not ranked and item_count <= 0:
        return "Low visibility / source fallback"

    if item_count >= 8 and high_conviction and len(elevated_risk) <= 2:
        return "Constructive / policy-supported watch"

    if item_count >= 8 and len(elevated_risk) >= 3:
        return "Active theme / risk-controlled"

    if high_conviction:
        return "Selective defense opportunity"

    if confirmation:
        return "Theme active / confirmation needed"

    return "Defense watchlist developing"


def build_portfolio_impact(
    stance: str,
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
    live_context: dict,
) -> str:
    if stance == "Constructive / policy-supported watch":
        return "Can support selective portfolio conviction"

    if stance == "Active theme / risk-controlled":
        return "Use as hedge/theme exposure with sizing discipline"

    if stance == "Selective defense opportunity":
        return "Portfolio ballast plus upside watch"

    if stance == "Theme active / confirmation needed":
        return "Watchlist exposure only until confirmation improves"

    if elevated_risk:
        return "Smaller sizing / risk-first"

    return "Monitor only"


def format_name_line(index: int, item: dict) -> str:
    return (
        f"{index}. {item['symbol']} — {format_score(item.get('score'))} | "
        f"{item.get('label')} | {item.get('bucket')}"
    )


def build_best_defense_names(ranked: list[dict]) -> str:
    if not ranked:
        return "• No defense-specific scored names detected. Add defense names to watchlist/scoring universe."

    lines = []

    for index, item in enumerate(ranked[:MAX_DEFENSE_NAMES], start=1):
        lines.append(format_name_line(index, item))

    return "\n".join(lines)


def build_risk_names(elevated_risk: list[dict]) -> str:
    if not elevated_risk:
        return "• No major elevated-risk defense names detected."

    lines = []

    for item in elevated_risk[:6]:
        lines.append(
            f"• {item['symbol']}: {item.get('risk')} | {item.get('action')} | {item.get('bucket')}"
        )

    return "\n".join(lines)


def build_confirmation_queue(confirmation: list[dict]) -> str:
    if not confirmation:
        return "• No major defense confirmation queue detected."

    lines = []

    for item in confirmation[:6]:
        symbol = item["symbol"]
        lines.append(
            f"• {symbol}: check /volume {symbol}, /earnings {symbol}, /analyst {symbol}, /filing {symbol}"
        )

    return "\n".join(lines)


def build_portfolio_read(
    stance: str,
    top_theme_name: str,
    portfolio_impact: str,
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
    live_context: dict,
) -> list[str]:
    notes = [
        f"Defense stance: {stance}.",
        f"Top official-source theme: {top_theme_name}.",
        f"Portfolio impact: {portfolio_impact}.",
        build_live_context_summary(live_context),
    ]

    if high_conviction:
        names = ", ".join(item["symbol"] for item in high_conviction[:4])
        notes.append(f"Cleanest defense candidates: {names}.")

    if elevated_risk:
        names = ", ".join(item["symbol"] for item in elevated_risk[:4])
        notes.append(f"Risk-control names: {names}.")

    if confirmation:
        names = ", ".join(item["symbol"] for item in confirmation[:4])
        notes.append(f"Needs confirmation before sizing: {names}.")

    return notes[:7]


def build_source_impact_read(top_theme_name: str, live_context: dict) -> str:
    item_count = int(live_context.get("item_count", 0) or 0)

    if item_count <= 0:
        return (
            "Official-source signal is unavailable or quiet. Use scored defense names as a watchlist, "
            "but do not upgrade conviction without policy, contract, budget, volume, or filing confirmation."
        )

    if top_theme_name in {"Defense Procurement", "Munitions / Missiles"}:
        return (
            "Policy/procurement signal matters because budget-backed demand can support primes, suppliers, "
            "missiles, interceptors, sensors, and production-scale defense names."
        )

    if top_theme_name == "Drones / Autonomy":
        return (
            "Drone/autonomy signal matters because low-cost, scalable systems can shift attention toward UAV, "
            "counter-drone, software, sensor, and battlefield autonomy exposure."
        )

    if top_theme_name == "Cyber / Electronic Warfare":
        return (
            "Cyber/electronic warfare signal matters because modern conflict raises demand for software, secure networks, "
            "signals intelligence, and mission systems."
        )

    if top_theme_name == "Geopolitical Risk":
        return (
            "Geopolitical signal matters because escalation can support defense demand while also increasing broad-market risk."
        )

    return (
        "Official-source defense signal is active. Treat it as theme context, then validate with score, volume, filings, "
        "earnings, and analyst alignment before sizing."
    )


def build_confirming_signals(top_theme_name: str) -> list[str]:
    signals = [
        "Defense.gov contract awards or procurement releases connect directly to scored names.",
        "White House or federal policy language supports funded defense, cyber, AI, munitions, or industrial-base demand.",
        "Congress/NDAA language supports multi-year procurement, modernization, shipbuilding, missiles, drones, or cyber priorities.",
        "Company filings show backlog, funded contracts, production scale, or margin durability.",
        "Volume confirms the stock move instead of just reacting to headlines.",
    ]

    if top_theme_name == "Drones / Autonomy":
        signals.append("Drone/counter-drone headlines translate into real awards, revenue, backlog, or guidance.")

    if top_theme_name == "Munitions / Missiles":
        signals.append("Missile/munition demand is tied to actual funded procurement or replenishment language.")

    return signals[:6]


def build_breaking_signals() -> list[str]:
    return [
        "Defense headlines do not translate into contracts, backlog, funded demand, or revenue.",
        "Filing risk shows dilution, budget uncertainty, supply constraints, investigation, or margin pressure.",
        "Stock price runs ahead of volume confirmation.",
        "Analyst optimism rises while Smart Money score weakens.",
        "Geopolitical headlines fade without procurement follow-through.",
    ]


def build_defense_action(
    stance: str,
    portfolio_impact: str,
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
) -> str:
    if stance == "Constructive / policy-supported watch" and high_conviction:
        symbol = high_conviction[0]["symbol"]
        return f"Start with {symbol}; validate with /volume {symbol}, /filing {symbol}, and /earnings {symbol} before increasing conviction."

    if stance == "Active theme / risk-controlled":
        return "Theme is active, but risk control comes first. Avoid chasing defense headlines without confirmation."

    if elevated_risk:
        symbol = elevated_risk[0]["symbol"]
        return f"Risk is elevated. Review /risk {symbol} and /filing {symbol} before sizing any defense exposure."

    if confirmation:
        symbol = confirmation[0]["symbol"]
        return f"Defense watchlist needs confirmation. Start with /volume {symbol} and /filing {symbol}."

    return "Monitor defense exposure, but wait for stronger score, policy, contract, volume, or filing confirmation."


def build_next_commands(ranked: list[dict], elevated_risk: list[dict], confirmation: list[dict]) -> str:
    commands = []

    if ranked:
        symbol = ranked[0]["symbol"]
        commands.append(f"/stock {symbol}")
        commands.append(f"/scorecard {symbol}")
        commands.append(f"/filing {symbol}")

    if elevated_risk:
        commands.append(f"/risk {elevated_risk[0]['symbol']}")

    if confirmation:
        commands.append(f"/volume {confirmation[0]['symbol']}")

    commands.append("/portfolio")
    commands.append("/top10")

    return "\n".join(f"• {command}" for command in commands[:8])


def build_defense_intelligence_report(force_refresh: bool = False) -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    ranked = get_ranked_defense_items(scores)

    live_context = fetch_defense_live_context(force_refresh=force_refresh)

    avg_score = average_score(ranked)
    high_conviction = [item for item in ranked if is_high_conviction(item)]
    elevated_risk = [item for item in ranked if is_elevated_risk(item)]
    confirmation = [item for item in ranked if needs_confirmation(item)]

    top_symbols = [item["symbol"] for item in ranked[:8]]
    high_risk_symbols = [item["symbol"] for item in elevated_risk[:8]]
    confirmation_symbols = [item["symbol"] for item in confirmation[:8]]

    top_theme_name = top_defense_theme(live_context, ranked)
    stance = build_defense_stance(
        ranked=ranked,
        high_conviction=high_conviction,
        elevated_risk=elevated_risk,
        confirmation=confirmation,
        live_context=live_context,
    )

    portfolio_impact = build_portfolio_impact(
        stance=stance,
        high_conviction=high_conviction,
        elevated_risk=elevated_risk,
        confirmation=confirmation,
        live_context=live_context,
    )

    record = build_defense_record(
        top_symbols=top_symbols,
        high_risk_symbols=high_risk_symbols,
        confirmation_symbols=confirmation_symbols,
        top_theme=top_theme_name,
        defense_stance=stance,
        average_score=avg_score,
        source_item_count=int(live_context.get("item_count", 0) or 0),
        source_error_count=len(live_context.get("source_errors", []) or []),
        portfolio_impact=portfolio_impact,
    )

    evolution = record_defense_read(record)

    evolution_notes = build_defense_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    portfolio_notes = build_portfolio_read(
        stance=stance,
        top_theme_name=top_theme_name,
        portfolio_impact=portfolio_impact,
        high_conviction=high_conviction,
        elevated_risk=elevated_risk,
        confirmation=confirmation,
        live_context=live_context,
    )

    return f"""
🛡️ Defense / AI Warfare Intelligence

Headline
Defense Stance: {stance}
Portfolio Impact: {portfolio_impact}
Top Official-Source Theme: {top_theme_name}
Average Defense Score: {format_score(avg_score)}
Defense Candidates: {len(ranked)}
High-Conviction Candidates: {len(high_conviction)}
Elevated-Risk Names: {len(elevated_risk)}
Confirmation Queue: {len(confirmation)}

Portfolio Read
{bullet_lines(portfolio_notes)}

Official-Source Themes
{format_theme_snapshot(live_context)}

Official-Source Data Points
{format_source_snapshot(live_context)}

Why This Matters
{build_source_impact_read(top_theme_name, live_context)}

Best Defense / AI Warfare Names
{build_best_defense_names(ranked)}

Highest-Risk Defense Names
{build_risk_names(elevated_risk)}

Confirmation Queue
{build_confirmation_queue(confirmation)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_defense_memory_summary()}

What Would Confirm The Defense Thesis
{bullet_lines(build_confirming_signals(top_theme_name))}

What Would Break The Defense Thesis
{bullet_lines(build_breaking_signals())}

Defense Action
{build_defense_action(stance, portfolio_impact, high_conviction, elevated_risk, confirmation)}

Next Commands
{build_next_commands(ranked, elevated_risk, confirmation)}

Research only. Not financial advice.
""".strip()