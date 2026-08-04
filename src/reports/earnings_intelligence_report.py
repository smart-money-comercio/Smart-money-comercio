from datetime import datetime
from typing import Any

from src.intelligence.earnings_evolution import (
    build_earnings_evolution_notes,
    build_earnings_memory_summary,
    build_earnings_record,
    record_earnings_read,
    safe_float,
)
from src.reports.top10_report import classify_action_bucket, rank_candidates
from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
)


def clean_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("$", "").strip()


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
        ticker = clean_symbol(
            get_ticker(item) or item.get("symbol") or item.get("ticker")
        )

        if ticker == symbol:
            return item

    return {"symbol": symbol, "ticker": symbol}


def get_first_value(data: dict, keys: list[str], default=None):
    for key in keys:
        value = data.get(key)

        if value is not None and str(value).strip():
            return value

    return default


def compact_text(value: Any, max_chars: int = 150) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear catalyst detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.0f}/100"


def parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()

    if not text:
        return None

    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def extract_earnings_date(score_data: dict) -> str:
    value = get_first_value(
        score_data,
        [
            "earnings_date",
            "next_earnings_date",
            "report_date",
            "next_report_date",
            "earnings",
            "earningsDate",
            "nextEarningsDate",
        ],
        "",
    )

    return str(value or "").strip()


def days_until_earnings(earnings_date: str) -> int | None:
    parsed = parse_date(earnings_date)

    if parsed is None:
        return None

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    event_day = parsed.replace(hour=0, minute=0, second=0, microsecond=0)

    return (event_day - today).days


def build_timing_bucket(earnings_date: str) -> str:
    days = days_until_earnings(earnings_date)

    if days is None:
        return "Date unavailable"

    if days < -3:
        return "Post-earnings"
    if -3 <= days <= 3:
        return "Active earnings window"
    if days <= 14:
        return "Near-term catalyst"
    if days <= 45:
        return "Upcoming catalyst"

    return "Distant catalyst"


def build_catalyst_status(
    score: float | None,
    timing_bucket: str,
    risk: str,
    volume_label: str,
    action: str,
) -> str:
    risk_lower = str(risk or "").lower()
    volume_lower = str(volume_label or "").lower()
    action_lower = str(action or "").lower()

    if timing_bucket == "Active earnings window":
        if score is not None and score >= 80 and "high" not in risk_lower:
            return "High-interest catalyst"
        return "Event-risk watch"

    if timing_bucket == "Near-term catalyst":
        if score is not None and score >= 80 and not any(term in risk_lower for term in ["high", "speculative"]):
            return "Constructive setup into catalyst"
        return "Needs confirmation before catalyst"

    if timing_bucket == "Post-earnings":
        return "Post-event read"

    if any(term in action_lower for term in ["avoid", "reduce", "caution"]):
        return "Cautious catalyst setup"

    if any(term in volume_lower for term in ["strong", "confirm", "accumulation", "bullish"]):
        return "Volume-supported catalyst watch"

    return "Developing catalyst watch"


def build_catalyst_risk(
    score: float | None,
    timing_bucket: str,
    risk: str,
    action: str,
) -> str:
    risk_lower = str(risk or "").lower()
    action_lower = str(action or "").lower()

    if any(term in risk_lower for term in ["high", "speculative", "elevated", "volatile"]):
        return "High"

    if timing_bucket in {"Active earnings window", "Near-term catalyst"}:
        if score is not None and score >= 85 and "high" not in risk_lower:
            return "Medium"
        return "Elevated"

    if any(term in action_lower for term in ["avoid", "reduce", "caution"]):
        return "Elevated"

    return "Medium"


def build_catalyst_read(
    symbol: str,
    score: float | None,
    timing_bucket: str,
    catalyst_status: str,
    catalyst_risk: str,
    action: str,
) -> str:
    if catalyst_status == "High-interest catalyst":
        return f"{symbol} has a strong score near the earnings window. This is high interest, but not a blind chase."

    if catalyst_status == "Constructive setup into catalyst":
        return f"{symbol} has a constructive setup into the catalyst. Confirmation matters before sizing."

    if catalyst_status == "Event-risk watch":
        return f"{symbol} is in the event-risk zone. Earnings can reset the thesis quickly."

    if catalyst_status == "Post-event read":
        return f"{symbol} is post-earnings. Focus on reaction quality, guidance, margin commentary, and whether volume confirms the new read."

    if catalyst_risk == "High":
        return f"{symbol} has high catalyst risk. Treat the setup cautiously until the signal improves."

    return f"{symbol} has a developing catalyst setup. Current action bias: {action or 'Watch'}."


def build_catalyst_drivers(
    score: float | None,
    timing_bucket: str,
    risk: str,
    signal: str,
    volume_label: str,
    category: str,
) -> list[str]:
    drivers = []

    if timing_bucket != "Date unavailable":
        drivers.append(f"Timing: {timing_bucket}.")

    if score is not None:
        if score >= 85:
            drivers.append("Score is strong enough to make the catalyst worth monitoring closely.")
        elif score >= 75:
            drivers.append("Score is constructive, but catalyst confirmation is still needed.")
        else:
            drivers.append("Score is not yet strong enough to treat the catalyst as high-conviction.")

    if signal:
        drivers.append(f"Signal strength: {signal}.")

    if volume_label:
        drivers.append(f"Volume confirmation: {volume_label}.")

    if risk:
        drivers.append(f"Risk overlay: {risk}.")

    category_lower = str(category or "").lower()

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        drivers.append("AI/growth names need clean guidance, margin strength, and demand commentary.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        drivers.append("Defense names need contract flow, backlog, budget language, or funded demand.")

    return drivers[:5]


def build_confirming_signals(category: str) -> list[str]:
    category_lower = str(category or "").lower()

    signals = [
        "Beat-and-raise report or guidance that supports the thesis.",
        "Positive reaction with volume, not just a one-day headline pop.",
        "Management commentary that confirms demand, margins, backlog, or pricing power.",
    ]

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        signals.append("AI demand, data center growth, margins, and forward orders improving.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        signals.append("Funded contracts, backlog expansion, production scale, or budget visibility.")

    return signals[:5]


def build_breaking_signals(category: str) -> list[str]:
    category_lower = str(category or "").lower()

    signals = [
        "Guide-down, weak margins, lower demand, or cautious management tone.",
        "Price fades after earnings despite headline strength.",
        "Volume does not confirm the move.",
    ]

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        signals.append("AI/growth expectations reset lower or sector leadership rotates away.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        signals.append("Headline defense demand fails to translate into contract or backlog evidence.")

    return signals[:5]


def build_earnings_action(
    symbol: str,
    score: float | None,
    timing_bucket: str,
    catalyst_risk: str,
    action: str,
) -> str:
    if timing_bucket == "Active earnings window":
        return "Do not force a trade into the event. Let the report and reaction confirm the thesis."

    if timing_bucket == "Near-term catalyst" and catalyst_risk == "Elevated":
        return "Catalyst is close and risk is elevated. Favor smaller sizing, patience, or wait for post-event clarity."

    if score is not None and score >= 85 and catalyst_risk != "High":
        return f"High-quality setup. Review /volume {symbol} and /risk {symbol} before acting around the catalyst."

    if score is not None and score >= 75:
        return f"Constructive watch. Use /scorecard {symbol} to validate whether the setup deserves attention."

    return f"Wait for confirmation. Current action bias: {action or 'Watch'}."


def build_related_commands(symbol: str) -> str:
    return f"""
/stock {symbol}
/scorecard {symbol}
/risk {symbol}
/volume {symbol}
/top10
""".strip()


def build_earnings_intelligence_report(symbol: str) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /earnings SYMBOL"

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
        risk = get_risk_label(score_data)
    except Exception:
        risk = "Unknown"

    try:
        action = get_action_label(score_data)
    except Exception:
        action = "Watch"

    try:
        category = get_category(score_data)
    except Exception:
        category = "Uncategorized"

    try:
        volume_label = get_volume_label(score_data)
    except Exception:
        volume_label = "Volume confirmation unavailable"

    earnings_date = extract_earnings_date(score_data)
    timing_bucket = build_timing_bucket(earnings_date)

    catalyst_status = build_catalyst_status(
        score=score,
        timing_bucket=timing_bucket,
        risk=risk,
        volume_label=volume_label,
        action=action,
    )

    catalyst_risk = build_catalyst_risk(
        score=score,
        timing_bucket=timing_bucket,
        risk=risk,
        action=action,
    )

    try:
        ranked_item = rank_candidates([score_data], limit=1)[0]
        bucket = classify_action_bucket(ranked_item)
    except Exception:
        bucket = "Watch for Confirmation"

    record = build_earnings_record(
        symbol=symbol,
        score=score,
        earnings_date=earnings_date,
        timing_bucket=timing_bucket,
        catalyst_status=catalyst_status,
        catalyst_risk=catalyst_risk,
        action=action,
        risk=risk,
        signal=signal,
        category=category,
    )

    evolution = record_earnings_read(symbol, record)

    evolution_notes = build_earnings_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    drivers = build_catalyst_drivers(
        score=score,
        timing_bucket=timing_bucket,
        risk=risk,
        signal=signal,
        volume_label=volume_label,
        category=category,
    )

    return f"""
🗓️ {symbol} Earnings / Catalyst Intelligence

Headline
Catalyst Status: {catalyst_status}
Catalyst Risk: {catalyst_risk}
Earnings Date: {earnings_date or "Unavailable"}
Timing: {timing_bucket}
Score: {format_score(score)}
Signal: {label}
Conviction: {signal}
Risk: {risk}
Action: {action}
Bucket: {bucket}
Category: {category}

Catalyst Read
{build_catalyst_read(symbol, score, timing_bucket, catalyst_status, catalyst_risk, action)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_earnings_memory_summary(symbol)}

What Matters
{bullet_lines(drivers)}

What Would Confirm The Thesis
{bullet_lines(build_confirming_signals(category))}

What Would Break The Thesis
{bullet_lines(build_breaking_signals(category))}

Catalyst Action
{build_earnings_action(symbol, score, timing_bucket, catalyst_risk, action)}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()