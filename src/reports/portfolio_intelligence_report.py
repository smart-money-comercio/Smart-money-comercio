from collections import Counter
from typing import Any

from src.intelligence.portfolio_evolution import (
    build_portfolio_evolution_notes,
    build_portfolio_memory_summary,
    build_portfolio_record,
    record_portfolio_read,
    safe_float,
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


MAX_PORTFOLIO_NAMES = 8
MAX_REPORT_CANDIDATES = 20


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


def compact_text(value: Any, max_chars: int = 150) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear portfolio detail available."

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
        ranked = rank_candidates(scores, limit=MAX_REPORT_CANDIDATES)
    except Exception:
        ranked = sorted(
            [enrich_item(item) for item in scores],
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


def top_theme(ranked: list[dict]) -> str:
    categories = [
        str(item.get("category") or "").strip()
        for item in ranked[:MAX_REPORT_CANDIDATES]
        if str(item.get("category") or "").strip()
        and str(item.get("category") or "").lower() not in {"unknown", "n/a", "uncategorized"}
    ]

    if not categories:
        return "Mixed / developing"

    return Counter(categories).most_common(1)[0][0]


def average_score(items: list[dict]) -> float | None:
    values = [
        safe_float(item.get("score"))
        for item in items
        if safe_float(item.get("score")) is not None
    ]

    if not values:
        return None

    return sum(values) / len(values)


def build_portfolio_stance(
    ranked: list[dict],
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
) -> str:
    if not ranked:
        return "No scored portfolio data"

    if len(elevated_risk) >= max(3, len(high_conviction)):
        return "Defensive / validation-first"

    if len(high_conviction) >= 3 and len(elevated_risk) <= 2:
        return "Constructive / selective offense"

    if len(confirmation) >= 5:
        return "Watchlist-heavy / confirmation needed"

    return "Balanced / selective"


def build_action_bias(stance: str, high_conviction: list[dict], elevated_risk: list[dict]) -> str:
    if stance == "Constructive / selective offense":
        names = ", ".join(item["symbol"] for item in high_conviction[:3])
        return f"Focus on the cleanest setups first: {names or 'top-ranked names'}."

    if stance == "Defensive / validation-first":
        names = ", ".join(item["symbol"] for item in elevated_risk[:3])
        return f"Control risk first; avoid chasing elevated-risk names: {names or 'risk names'}."

    if stance == "Watchlist-heavy / confirmation needed":
        return "Require confirmation from /volume, /earnings, /analyst, and /filing before sizing."

    return "Stay selective: prioritize high score, controlled risk, confirmed volume, and clean catalysts."


def format_name_line(index: int, item: dict) -> str:
    return (
        f"{index}. {item['symbol']} — {format_score(item.get('score'))} | "
        f"{item.get('label')} | {item.get('bucket')}"
    )


def build_best_opportunities(ranked: list[dict]) -> str:
    if not ranked:
        return "• No scored opportunities available."

    lines = []

    for index, item in enumerate(ranked[:5], start=1):
        lines.append(format_name_line(index, item))

    return "\n".join(lines)


def build_risk_names(elevated_risk: list[dict]) -> str:
    if not elevated_risk:
        return "• No major elevated-risk names detected in the current ranked set."

    lines = []

    for item in elevated_risk[:5]:
        lines.append(
            f"• {item['symbol']}: {item.get('risk')} | {item.get('action')} | {item.get('bucket')}"
        )

    return "\n".join(lines)


def build_confirmation_queue(confirmation: list[dict]) -> str:
    if not confirmation:
        return "• No major confirmation queue detected."

    lines = []

    for item in confirmation[:5]:
        lines.append(
            f"• {item['symbol']}: check /volume {item['symbol']}, /earnings {item['symbol']}, /analyst {item['symbol']}, /filing {item['symbol']}"
        )

    return "\n".join(lines)


def build_theme_exposure(ranked: list[dict]) -> str:
    categories = [
        str(item.get("category") or "Uncategorized")
        for item in ranked[:MAX_REPORT_CANDIDATES]
    ]

    counts = Counter(categories)
    common = counts.most_common(5)

    if not common:
        return "• Theme exposure unavailable."

    return "\n".join(f"• {theme}: {count}" for theme, count in common)


def build_portfolio_impact_notes(
    stance: str,
    top_theme_name: str,
    high_conviction: list[dict],
    elevated_risk: list[dict],
    confirmation: list[dict],
) -> list[str]:
    notes = [
        f"Portfolio stance: {stance}.",
        f"Top theme exposure: {top_theme_name}.",
    ]

    if high_conviction:
        names = ", ".join(item["symbol"] for item in high_conviction[:4])
        notes.append(f"High-conviction candidates: {names}.")

    if elevated_risk:
        names = ", ".join(item["symbol"] for item in elevated_risk[:4])
        notes.append(f"Risk control priority: {names}.")

    if confirmation:
        names = ", ".join(item["symbol"] for item in confirmation[:4])
        notes.append(f"Names needing confirmation before sizing: {names}.")

    notes.append("Use /filing for disclosure risk, /earnings for catalysts, /analyst for Street alignment, and /volume for money-flow confirmation.")

    return notes[:6]


def build_positioning_rules(stance: str) -> list[str]:
    if stance == "Constructive / selective offense":
        return [
            "Favor the top-ranked names only when volume and catalyst confirmation support the score.",
            "Do not spread capital across every watchlist idea; concentrate attention on the cleanest setups.",
            "Use /risk before increasing size.",
        ]

    if stance == "Defensive / validation-first":
        return [
            "Protect capital first; avoid adding to elevated-risk or unclear disclosure names.",
            "Treat strong scores as watchlist candidates until risk, filing, and volume reads confirm.",
            "Prefer smaller sizing and post-catalyst clarity.",
        ]

    if stance == "Watchlist-heavy / confirmation needed":
        return [
            "The portfolio has ideas, but many still need proof.",
            "Require volume, catalyst, analyst, and filing confirmation before sizing.",
            "Avoid chasing moves that are not supported by money flow.",
        ]

    return [
        "Stay selective and avoid overtrading.",
        "Prioritize names with high score, controlled risk, clean filings, constructive catalysts, and confirming volume.",
        "Use single-stock commands before acting.",
    ]


def build_next_commands(ranked: list[dict], elevated_risk: list[dict], confirmation: list[dict]) -> str:
    commands = []

    if ranked:
        symbol = ranked[0]["symbol"]
        commands.append(f"/stock {symbol}")
        commands.append(f"/scorecard {symbol}")

    if elevated_risk:
        commands.append(f"/risk {elevated_risk[0]['symbol']}")

    if confirmation:
        symbol = confirmation[0]["symbol"]
        commands.append(f"/volume {symbol}")
        commands.append(f"/filing {symbol}")

    commands.append("/top10")
    commands.append("/brief")

    return "\n".join(f"• {command}" for command in commands[:7])


def build_portfolio_intelligence_report() -> str:
    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    ranked = get_ranked_items(scores)

    avg_score = average_score(ranked)
    high_conviction = [item for item in ranked if is_high_conviction(item)]
    elevated_risk = [item for item in ranked if is_elevated_risk(item)]
    confirmation = [item for item in ranked if needs_confirmation(item)]

    top_symbols = [item["symbol"] for item in ranked[:MAX_PORTFOLIO_NAMES]]
    high_risk_symbols = [item["symbol"] for item in elevated_risk[:MAX_PORTFOLIO_NAMES]]
    confirmation_symbols = [item["symbol"] for item in confirmation[:MAX_PORTFOLIO_NAMES]]

    top_theme_name = top_theme(ranked)
    stance = build_portfolio_stance(ranked, high_conviction, elevated_risk, confirmation)
    action_bias = build_action_bias(stance, high_conviction, elevated_risk)

    record = build_portfolio_record(
        top_symbols=top_symbols,
        high_risk_symbols=high_risk_symbols,
        confirmation_symbols=confirmation_symbols,
        top_theme=top_theme_name,
        portfolio_stance=stance,
        average_score=avg_score,
        high_conviction_count=len(high_conviction),
        elevated_risk_count=len(elevated_risk),
        action_bias=action_bias,
    )

    evolution = record_portfolio_read(record)

    evolution_notes = build_portfolio_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    portfolio_notes = build_portfolio_impact_notes(
        stance=stance,
        top_theme_name=top_theme_name,
        high_conviction=high_conviction,
        elevated_risk=elevated_risk,
        confirmation=confirmation,
    )

    return f"""
🧭 Portfolio Intelligence

Headline
Portfolio Stance: {stance}
Average Score: {format_score(avg_score)}
High-Conviction Candidates: {len(high_conviction)}
Elevated-Risk Names: {len(elevated_risk)}
Confirmation Queue: {len(confirmation)}
Top Theme: {top_theme_name}

Portfolio Read
{bullet_lines(portfolio_notes)}

Best Current Opportunities
{build_best_opportunities(ranked)}

Highest-Risk Names
{build_risk_names(elevated_risk)}

Confirmation Queue
{build_confirmation_queue(confirmation)}

Theme Exposure
{build_theme_exposure(ranked)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_portfolio_memory_summary()}

Positioning Rules
{bullet_lines(build_positioning_rules(stance))}

Portfolio Action
{action_bias}

Next Commands
{build_next_commands(ranked, elevated_risk, confirmation)}

Research only. Not financial advice.
""".strip()