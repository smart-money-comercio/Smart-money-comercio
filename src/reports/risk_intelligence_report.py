from typing import Any

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


def clean_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("$", "").strip()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)

    except Exception:
        return default


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

        return items

    return []


def get_score_value(score_data: dict) -> float | None:
    for key in [
        "score",
        "total_score",
        "smart_money_score",
        "overall_score",
        "final_score",
        "composite_score",
    ]:
        value = safe_float(score_data.get(key))

        if value is not None:
            return value

    return None


def find_score_data(symbol: str, scores: list[dict]) -> dict:
    symbol = clean_symbol(symbol)

    for item in scores:
        ticker = clean_symbol(get_ticker(item) or item.get("symbol") or item.get("ticker"))

        if ticker == symbol:
            return item

    return {"symbol": symbol, "ticker": symbol}


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
        return "• No clear risk detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def get_rank_position(symbol: str, scores: list[dict]) -> int | None:
    try:
        ranked = rank_candidates(scores, limit=50)
    except Exception:
        return None

    symbol = clean_symbol(symbol)

    for index, item in enumerate(ranked, start=1):
        if clean_symbol(item.get("symbol")) == symbol:
            return index

    return None


def derive_risk_level(score: float | None, risk_label: str, action: str, bucket: str) -> str:
    risk_lower = str(risk_label or "").lower()
    action_lower = str(action or "").lower()
    bucket_lower = str(bucket or "").lower()

    if any(term in risk_lower for term in ["high", "speculative", "elevated", "volatile"]):
        return "High"

    if "high risk" in bucket_lower:
        return "High"

    if any(term in action_lower for term in ["avoid", "reduce", "sell", "caution"]):
        return "Elevated"

    if score is not None and score < 65:
        return "Elevated"

    if score is not None and score >= 85 and "high" not in risk_lower:
        return "Controlled"

    return "Medium"


def build_main_risks(
    symbol: str,
    score: float | None,
    risk_label: str,
    action: str,
    category: str,
    signal: str,
    volume_label: str,
    bucket: str,
) -> list[str]:
    risks = []

    category_lower = str(category or "").lower()
    action_lower = str(action or "").lower()
    risk_lower = str(risk_label or "").lower()
    signal_lower = str(signal or "").lower()
    bucket_lower = str(bucket or "").lower()
    volume_lower = str(volume_label or "").lower()

    if score is not None and score >= 85:
        risks.append("Chasing risk: high-ranked names can still punish late entries.")

    if score is not None and score < 70:
        risks.append("Conviction risk: score is not yet strong enough for a high-confidence setup.")

    if any(term in risk_lower for term in ["high", "elevated", "speculative", "volatile"]):
        risks.append(f"Risk label is already elevated: {risk_label}.")

    if "high risk" in bucket_lower:
        risks.append("Bucket risk: this sits in the High Risk / Wait group.")

    if any(term in action_lower for term in ["avoid", "reduce", "sell", "caution"]):
        risks.append(f"Action bias is cautious: {action}.")

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        risks.append("Growth/AI rotation risk: rates, Nasdaq weakness, or valuation pressure can hit the setup.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        risks.append("Headline risk: defense themes need contract, backlog, budget, or volume confirmation.")

    if any(term in category_lower for term in ["energy", "oil", "power"]):
        risks.append("Commodity/rate risk: oil, yields, and infrastructure spending can change the thesis quickly.")

    if "weak" in signal_lower or "developing" in signal_lower:
        risks.append("Signal risk: setup is still developing and needs confirmation.")

    if any(term in volume_lower for term in ["weak", "low", "unconfirmed", "needs"]):
        risks.append(f"Volume risk: {volume_label}.")

    if not risks:
        risks.append(f"{symbol} has no obvious severe risk flag, but entry discipline still matters.")

    return risks[:5]


def build_risk_reducers(score: float | None, risk_label: str, action: str, category: str, volume_label: str) -> list[str]:
    reducers = [
        "Pullback into a better entry zone instead of chasing strength.",
        "Volume-backed continuation or support hold.",
        "Clear catalyst confirmation from earnings, guidance, contracts, or sector leadership.",
    ]

    category_lower = str(category or "").lower()

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        reducers.append("Nasdaq breadth, rates, and AI/semi leadership staying constructive.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        reducers.append("Real contract flow, budget language, backlog growth, or direct defense revenue exposure.")

    if risk_label:
        reducers.append(f"Risk label improving from current read: {risk_label}.")

    if volume_label:
        reducers.append(f"Volume read improving from: {volume_label}.")

    return reducers[:5]


def build_risk_triggers(score: float | None, risk_label: str, action: str, category: str) -> list[str]:
    triggers = [
        "Failed breakout or loss of support after a strong move.",
        "Weak volume on attempted continuation.",
        "Negative earnings revision, guide-down, margin pressure, or weak catalyst follow-through.",
    ]

    category_lower = str(category or "").lower()

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        triggers.append("AI/growth leadership rotation or Nasdaq/rate pressure.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        triggers.append("Theme fading after headlines without contract or budget confirmation.")

    if score is not None and score < 70:
        triggers.append("Score failing to improve on the next read.")

    return triggers[:5]


def build_positioning_read(risk_level: str, score: float | None, action: str, bucket: str) -> str:
    risk_lower = str(risk_level or "").lower()
    bucket_lower = str(bucket or "").lower()
    action_clean = str(action or "Watch").strip()

    if risk_lower == "high":
        return "High risk. Treat as wait-first unless the setup improves. Smaller sizing or no action is appropriate."

    if risk_lower == "elevated":
        return "Elevated risk. Do not chase; require confirmation and use tighter validation."

    if "best setup" in bucket_lower and score is not None and score >= 85:
        return "Risk is controlled relative to score, but entry still matters. Favor pullbacks or confirmed continuation."

    if score is not None and score >= 75:
        return "Moderate risk. Keep on watch and require volume, catalyst, or price confirmation before sizing."

    return f"Risk read supports patience. Current action bias: {action_clean}."


def build_related_commands(symbol: str) -> str:
    return f"""
/stock {symbol}
/scorecard {symbol}
/volume {symbol}
/earnings {symbol}
/top10
""".strip()


def build_risk_intelligence_report(symbol: str) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /risk SYMBOL"

    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    score_data = find_score_data(symbol, scores)
    score = get_score_value(score_data)

    try:
        label = get_smart_money_label(score_data)
    except Exception:
        label = "Signal developing"

    try:
        signal = get_signal_strength(score_data)
    except Exception:
        signal = label

    try:
        risk_label = get_risk_label(score_data)
    except Exception:
        risk_label = "Unknown"

    try:
        action = get_action_label(score_data)
    except Exception:
        action = "Watch"

    try:
        category = get_category(score_data)
    except Exception:
        category = "Uncategorized"

    try:
        fit = get_portfolio_fit(score_data)
    except Exception:
        fit = "Unknown"

    try:
        volume_label = get_volume_label(score_data)
    except Exception:
        volume_label = "Volume confirmation unavailable"

    try:
        ranked_item = rank_candidates([score_data], limit=1)[0]
        bucket = classify_action_bucket(ranked_item)
    except Exception:
        bucket = "Watch for Confirmation"

    risk_level = derive_risk_level(score, risk_label, action, bucket)
    rank_position = get_rank_position(symbol, scores)

    rank_text = f"#{rank_position}" if rank_position else "Unranked"

    main_risks = build_main_risks(
        symbol=symbol,
        score=score,
        risk_label=risk_label,
        action=action,
        category=category,
        signal=signal,
        volume_label=volume_label,
        bucket=bucket,
    )

    reducers = build_risk_reducers(
        score=score,
        risk_label=risk_label,
        action=action,
        category=category,
        volume_label=volume_label,
    )

    triggers = build_risk_triggers(
        score=score,
        risk_label=risk_label,
        action=action,
        category=category,
    )

    return f"""
⚠️ {symbol} Risk Intelligence

Headline
Risk Level: {risk_level}
Risk Label: {risk_label}
Score: {format_score(score)}
Rank: {rank_text}
Signal: {label}
Conviction: {signal}
Bucket: {bucket}
Portfolio Fit: {fit}

Main Risks
{bullet_lines(main_risks)}

What Would Reduce Risk
{bullet_lines(reducers)}

What Would Increase Risk
{bullet_lines(triggers)}

Risk Action
{build_positioning_read(risk_level, score, action, bucket)}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()