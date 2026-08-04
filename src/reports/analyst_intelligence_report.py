from typing import Any

from src.intelligence.analyst_evolution import (
    build_analyst_evolution_notes,
    build_analyst_memory_summary,
    build_analyst_record,
    record_analyst_read,
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


try:
    from src.commands.watchlist_commands import fetch_quotes_for_symbols
except Exception:
    fetch_quotes_for_symbols = None


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


def get_quote_data(symbol: str) -> dict:
    if fetch_quotes_for_symbols is None:
        return {}

    try:
        quotes = fetch_quotes_for_symbols([symbol])

        if isinstance(quotes, dict):
            return quotes.get(symbol) or quotes.get(symbol.upper()) or {}

    except Exception:
        return {}

    return {}


def get_quote_value(quote: dict, *keys, default=None):
    for key in keys:
        if key in quote:
            return quote.get(key)

    return default


def compact_text(value: Any, max_chars: int = 150) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear analyst detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.0f}/100"


def format_price(value: float | None) -> str:
    if value is None:
        return "Unavailable"

    return f"${value:,.2f}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "Unavailable"

    sign = "+" if value > 0 else ""

    return f"{sign}{value:.2f}%"


def extract_price(score_data: dict, quote: dict) -> float | None:
    value = get_first_value(
        score_data,
        [
            "price",
            "current_price",
            "currentPrice",
            "regularMarketPrice",
            "last_price",
            "close",
        ],
    )

    if value is None:
        value = get_quote_value(
            quote,
            "price",
            "current_price",
            "regularMarketPrice",
            "last",
            "close",
        )

    return safe_float(value)


def extract_analyst_consensus(score_data: dict) -> str:
    value = get_first_value(
        score_data,
        [
            "analyst_consensus",
            "analyst_rating",
            "consensus",
            "recommendation",
            "recommendation_key",
            "recommendationKey",
            "rating",
            "street_rating",
            "wall_street_rating",
        ],
        "",
    )

    text = str(value or "").replace("_", " ").strip()

    return text.title() if text else "Unavailable"


def extract_analyst_count(score_data: dict) -> str:
    value = get_first_value(
        score_data,
        [
            "analyst_count",
            "number_of_analysts",
            "num_analysts",
            "recommendation_count",
            "target_analyst_count",
            "targetMeanPriceAnalystCount",
        ],
        "",
    )

    return str(value or "Unavailable").strip()


def extract_price_target(score_data: dict) -> float | None:
    value = get_first_value(
        score_data,
        [
            "price_target",
            "target_price",
            "mean_price_target",
            "median_price_target",
            "targetMeanPrice",
            "targetMedianPrice",
            "analyst_price_target",
            "average_price_target",
        ],
    )

    return safe_float(value)


def extract_high_target(score_data: dict) -> float | None:
    value = get_first_value(
        score_data,
        [
            "target_high",
            "high_price_target",
            "targetHighPrice",
            "analyst_high_target",
        ],
    )

    return safe_float(value)


def extract_low_target(score_data: dict) -> float | None:
    value = get_first_value(
        score_data,
        [
            "target_low",
            "low_price_target",
            "targetLowPrice",
            "analyst_low_target",
        ],
    )

    return safe_float(value)


def extract_upside_percent(score_data: dict, price: float | None, price_target: float | None) -> float | None:
    value = get_first_value(
        score_data,
        [
            "upside_percent",
            "analyst_upside_percent",
            "target_upside",
            "price_target_upside",
            "upside",
        ],
    )

    explicit = safe_float(value)

    if explicit is not None:
        return explicit

    if price is None or price <= 0 or price_target is None:
        return None

    return ((price_target - price) / price) * 100


def normalize_consensus_bucket(consensus: str) -> str:
    text = str(consensus or "").lower()

    if consensus == "Unavailable":
        return "Unavailable"

    if any(term in text for term in ["strong buy", "buy", "outperform", "overweight"]):
        return "Bullish"

    if any(term in text for term in ["hold", "neutral", "market perform", "equal weight"]):
        return "Neutral / mixed"

    if any(term in text for term in ["sell", "underperform", "underweight", "reduce"]):
        return "Cautious"

    return "Mixed / unclear"


def build_alignment(
    score: float | None,
    consensus_bucket: str,
    upside_percent: float | None,
    risk: str,
    action: str,
) -> str:
    risk_lower = str(risk or "").lower()
    action_lower = str(action or "").lower()

    bullish_street = consensus_bucket == "Bullish"
    cautious_street = consensus_bucket == "Cautious"
    upside_positive = upside_percent is not None and upside_percent >= 10
    downside = upside_percent is not None and upside_percent < 0

    if score is not None and score >= 80 and bullish_street and not downside:
        return "Aligned bullish"

    if score is not None and score >= 80 and consensus_bucket in {"Neutral / mixed", "Mixed / unclear", "Unavailable"}:
        return "Smart Money ahead of Street"

    if score is not None and score < 70 and bullish_street:
        return "Wall Street more bullish than Smart Money"

    if score is not None and score >= 75 and cautious_street:
        return "Positive Smart Money / cautious Street divergence"

    if downside and score is not None and score >= 75:
        return "Score-target disconnect"

    if upside_positive and score is not None and score >= 75:
        return "Constructive alignment"

    if "high" in risk_lower or any(term in action_lower for term in ["avoid", "reduce", "caution"]):
        return "Caution alignment"

    return "Alignment developing"


def build_analyst_risk(
    score: float | None,
    consensus_bucket: str,
    upside_percent: float | None,
    risk: str,
    alignment: str,
) -> str:
    risk_lower = str(risk or "").lower()
    alignment_lower = str(alignment or "").lower()

    if any(term in risk_lower for term in ["high", "speculative", "elevated", "volatile"]):
        return "High"

    if "disconnect" in alignment_lower or "divergence" in alignment_lower:
        return "Elevated"

    if consensus_bucket == "Cautious":
        return "Elevated"

    if upside_percent is not None and upside_percent < -5:
        return "Elevated"

    if score is not None and score >= 80 and consensus_bucket == "Bullish":
        return "Controlled"

    return "Medium"


def build_consensus_read(
    symbol: str,
    score: float | None,
    consensus_bucket: str,
    alignment: str,
    upside_percent: float | None,
    analyst_risk: str,
) -> str:
    if alignment == "Aligned bullish":
        return f"{symbol} shows agreement between Smart Money quality and Wall Street optimism. That supports the thesis, but still needs price and volume confirmation."

    if alignment == "Smart Money ahead of Street":
        return f"{symbol} ranks better in Smart Money AI than the visible analyst consensus suggests. That can be opportunity or early-warning; confirm with /volume and /scorecard."

    if alignment == "Wall Street more bullish than Smart Money":
        return f"Wall Street appears more positive than Smart Money AI. That is a caution flag: analyst optimism may already be priced in or unsupported by the score."

    if alignment == "Positive Smart Money / cautious Street divergence":
        return f"Smart Money AI is more constructive than Wall Street. This is a divergence setup, so confirmation matters before sizing."

    if alignment == "Score-target disconnect":
        return f"{symbol} has a disconnect between Smart Money score and analyst target/upside. Treat the setup carefully until price action clarifies."

    if analyst_risk == "High":
        return f"{symbol} has high analyst-consensus risk. Do not treat consensus as confirmation."

    return f"{symbol} has a developing analyst consensus read. Use the Street view as context, not as the decision engine."


def build_difference_points(
    score: float | None,
    consensus_bucket: str,
    upside_percent: float | None,
    risk: str,
    volume_label: str,
) -> list[str]:
    points = []

    if score is not None:
        if score >= 85:
            points.append("Smart Money score is high, so analyst agreement is confirmation, not the core thesis.")
        elif score >= 75:
            points.append("Smart Money score is constructive, but still needs confirmation.")
        else:
            points.append("Smart Money score is not yet strong enough to rely on analyst optimism.")

    points.append(f"Wall Street bucket: {consensus_bucket}.")

    if upside_percent is not None:
        points.append(f"Implied analyst upside/downside: {format_percent(upside_percent)}.")

    if risk:
        points.append(f"Risk overlay: {risk}.")

    if volume_label:
        points.append(f"Volume confirmation: {volume_label}.")

    return points[:5]


def build_confirming_signals(category: str) -> list[str]:
    category_lower = str(category or "").lower()

    signals = [
        "Analyst upgrades, target increases, or estimate revisions that match improving Smart Money score.",
        "Price target upside supported by real price/volume confirmation.",
        "Consensus improving without the stock becoming overextended.",
    ]

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        signals.append("AI/growth demand, margin, backlog, or guidance commentary supports analyst optimism.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        signals.append("Defense analyst optimism is backed by contracts, backlog, budget language, or funded demand.")

    return signals[:5]


def build_breaking_signals(category: str) -> list[str]:
    category_lower = str(category or "").lower()

    signals = [
        "Downgrades, target cuts, estimate reductions, or negative revisions.",
        "Analyst optimism stays high while Smart Money score weakens.",
        "Stock sells off despite positive analyst language.",
    ]

    if any(term in category_lower for term in ["ai", "chip", "semiconductor", "technology", "growth"]):
        signals.append("AI/growth expectations reset lower or leadership rotates away.")

    if any(term in category_lower for term in ["defense", "warfare", "aerospace", "military", "munition"]):
        signals.append("Defense headlines fail to become funded revenue, backlog, or margin support.")

    return signals[:5]


def build_analyst_action(
    symbol: str,
    score: float | None,
    alignment: str,
    analyst_risk: str,
    action: str,
) -> str:
    if alignment == "Aligned bullish" and score is not None and score >= 80 and analyst_risk != "High":
        return f"Consensus supports the thesis. Validate with /volume {symbol} and /risk {symbol} before acting."

    if "ahead of Street" in alignment:
        return f"Smart Money is ahead of visible consensus. Use /scorecard {symbol}; do not act unless volume confirms."

    if "Wall Street more bullish" in alignment:
        return "Be careful. Analyst optimism may not be supported by Smart Money quality yet."

    if analyst_risk == "High":
        return "Treat analyst consensus as unreliable confirmation until the risk picture improves."

    return f"Current action bias: {action or 'Watch'}. Analyst view is context, not a standalone signal."


def build_related_commands(symbol: str) -> str:
    return f"""
/stock {symbol}
/scorecard {symbol}
/risk {symbol}
/volume {symbol}
/earnings {symbol}
/top10
""".strip()


def build_analyst_intelligence_report(symbol: str) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /analyst SYMBOL"

    try:
        raw_scores = get_stock_scores()
    except Exception:
        raw_scores = []

    scores = normalize_score_items(raw_scores)
    score_data = find_score_data(symbol, scores)
    score = get_score_value(score_data)

    quote = get_quote_data(symbol)

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

    consensus = extract_analyst_consensus(score_data)
    analyst_count = extract_analyst_count(score_data)
    consensus_bucket = normalize_consensus_bucket(consensus)

    price = extract_price(score_data, quote)
    price_target = extract_price_target(score_data)
    target_high = extract_high_target(score_data)
    target_low = extract_low_target(score_data)
    upside_percent = extract_upside_percent(score_data, price, price_target)

    alignment = build_alignment(
        score=score,
        consensus_bucket=consensus_bucket,
        upside_percent=upside_percent,
        risk=risk,
        action=action,
    )

    analyst_risk = build_analyst_risk(
        score=score,
        consensus_bucket=consensus_bucket,
        upside_percent=upside_percent,
        risk=risk,
        alignment=alignment,
    )

    try:
        ranked_item = rank_candidates([score_data], limit=1)[0]
        bucket = classify_action_bucket(ranked_item)
    except Exception:
        bucket = "Watch for Confirmation"

    record = build_analyst_record(
        symbol=symbol,
        score=score,
        consensus=consensus_bucket,
        alignment=alignment,
        analyst_risk=analyst_risk,
        price_target=price_target,
        upside_percent=upside_percent,
        action=action,
        risk=risk,
        signal=signal,
    )

    evolution = record_analyst_read(symbol, record)

    evolution_notes = build_analyst_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    difference_points = build_difference_points(
        score=score,
        consensus_bucket=consensus_bucket,
        upside_percent=upside_percent,
        risk=risk,
        volume_label=volume_label,
    )

    return f"""
🧠 {symbol} Analyst Consensus Intelligence

Headline
Consensus: {consensus}
Consensus Bucket: {consensus_bucket}
Analyst Count: {analyst_count}
Alignment: {alignment}
Analyst Risk: {analyst_risk}
Score: {format_score(score)}
Signal: {label}
Conviction: {signal}
Risk: {risk}
Action: {action}
Bucket: {bucket}
Category: {category}

Analyst Targets
Current Price: {format_price(price)}
Mean Target: {format_price(price_target)}
High Target: {format_price(target_high)}
Low Target: {format_price(target_low)}
Implied Upside: {format_percent(upside_percent)}

Consensus Read
{build_consensus_read(symbol, score, consensus_bucket, alignment, upside_percent, analyst_risk)}

Smart Money vs Wall Street
{bullet_lines(difference_points)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_analyst_memory_summary(symbol)}

What Would Confirm The Analyst Read
{bullet_lines(build_confirming_signals(category))}

What Would Break The Analyst Read
{bullet_lines(build_breaking_signals(category))}

Analyst Action
{build_analyst_action(symbol, score, alignment, analyst_risk, action)}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()