from typing import Any

from src.scoring.scoring_engine import get_stock_scores
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_score_story,
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


def get_first_value(data: dict, keys: list[str], default=None):
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)

    return default


def format_score(score: float | None) -> str:
    if score is None:
        return "N/A"

    return f"{score:.0f}/100"


def format_component_value(value: Any) -> str:
    number = safe_float(value)

    if number is not None:
        if number <= 10:
            return f"{number:.1f}/10"

        return f"{number:.0f}/100"

    text = str(value or "").strip()

    return text if text else "N/A"


def compact_text(value: Any, max_chars: int = 160) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def component_line(name: str, value: Any, note: str) -> str:
    return f"• {name}: {format_component_value(value)} — {compact_text(note, 110)}"


def build_component_breakdown(score_data: dict) -> str:
    smart_money_score = get_first_value(
        score_data,
        [
            "smart_money_score",
            "score",
            "total_score",
            "overall_score",
            "final_score",
            "composite_score",
        ],
    )

    volume_score = get_first_value(
        score_data,
        [
            "volume_score",
            "money_flow_score",
            "flow_score",
            "volume",
            "relative_volume_score",
        ],
    )

    risk_score = get_first_value(
        score_data,
        [
            "risk_score",
            "risk_adjusted_score",
            "quality_risk_score",
        ],
    )

    earnings_score = get_first_value(
        score_data,
        [
            "earnings_score",
            "catalyst_score",
            "growth_score",
            "revision_score",
            "momentum_score",
        ],
    )

    fit_score = get_first_value(
        score_data,
        [
            "portfolio_fit_score",
            "fit_score",
            "allocation_score",
            "stability_score",
        ],
    )

    try:
        volume_label = get_volume_label(score_data)
    except Exception:
        volume_label = "Volume confirmation still needs review"

    try:
        risk_label = get_risk_label(score_data)
    except Exception:
        risk_label = "Risk unavailable"

    try:
        fit_label = get_portfolio_fit(score_data)
    except Exception:
        fit_label = "Portfolio fit unavailable"

    try:
        action = get_action_label(score_data)
    except Exception:
        action = "Watch"

    return "\n".join(
        [
            component_line(
                "Smart Money",
                smart_money_score,
                "Composite signal quality and ranking strength.",
            ),
            component_line(
                "Volume / Money Flow",
                volume_score,
                volume_label,
            ),
            component_line(
                "Risk",
                risk_score,
                risk_label,
            ),
            component_line(
                "Earnings / Catalyst",
                earnings_score,
                "Looks for earnings, growth, momentum, revisions, or catalyst support.",
            ),
            component_line(
                "Portfolio Fit",
                fit_score,
                fit_label,
            ),
            component_line(
                "Action Bias",
                action,
                "Current suggested handling based on score and risk.",
            ),
        ]
    )


def build_score_drivers(symbol: str, score_data: dict, score: float | None) -> list[str]:
    drivers = []

    try:
        category = get_category(score_data)
    except Exception:
        category = ""

    try:
        label = get_smart_money_label(score_data)
    except Exception:
        label = "Signal developing"

    try:
        signal = get_signal_strength(score_data)
    except Exception:
        signal = label

    if score is not None:
        if score >= 85:
            drivers.append("Score is strong enough to qualify as a high-priority setup.")
        elif score >= 75:
            drivers.append("Score is constructive, but still needs confirmation.")
        elif score >= 65:
            drivers.append("Score is watchlist-quality, not yet a high-conviction read.")
        else:
            drivers.append("Score is still developing and needs improvement.")

    if category and str(category).lower() not in {"unknown", "none", "n/a", "uncategorized"}:
        drivers.append(f"Theme/category support: {category}.")

    if label:
        drivers.append(f"Smart Money label: {label}.")

    if signal and signal != label:
        drivers.append(f"Signal strength: {signal}.")

    if not drivers:
        drivers.append(f"{symbol} has limited scoring detail available right now.")

    return drivers[:4]


def build_improvement_factors(score_data: dict) -> list[str]:
    try:
        risk = get_risk_label(score_data)
    except Exception:
        risk = ""

    try:
        action = get_action_label(score_data)
    except Exception:
        action = ""

    try:
        volume = get_volume_label(score_data)
    except Exception:
        volume = ""

    factors = [
        "Stronger volume confirmation would improve conviction.",
        "Clear catalyst or earnings support would strengthen the setup.",
    ]

    if risk:
        factors.append(f"Lower risk profile would improve the read. Current risk: {risk}.")

    if action:
        factors.append(f"Action bias to monitor: {action}.")

    if volume:
        factors.append(f"Volume read to validate: {volume}.")

    return factors[:4]


def build_weakening_factors(score_data: dict) -> list[str]:
    try:
        risk = get_risk_label(score_data)
    except Exception:
        risk = "Unknown"

    return [
        f"Risk can weaken the setup if it rises from here. Current risk: {risk}.",
        "Weak volume or failed follow-through would reduce conviction.",
        "Earnings disappointment, guidance pressure, or sector rotation could weaken the score.",
    ]


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def build_interpretation(symbol: str, score_data: dict, score: float | None) -> str:
    drivers = build_score_drivers(symbol, score_data, score)
    improvements = build_improvement_factors(score_data)
    weakeners = build_weakening_factors(score_data)

    return f"""
What Is Driving The Score
{bullet_lines(drivers)}

What Could Improve It
{bullet_lines(improvements)}

What Could Weaken It
{bullet_lines(weakeners)}
""".strip()


def build_action_read(score_data: dict, score: float | None) -> str:
    try:
        action = get_action_label(score_data)
    except Exception:
        action = "Watch"

    try:
        risk = get_risk_label(score_data)
    except Exception:
        risk = "Unknown"

    risk_lower = str(risk or "").lower()

    if score is not None and score >= 85 and "high" not in risk_lower:
        return "Strong setup. Do not chase blindly; use confirmation, pullbacks, or volume-backed continuation."

    if score is not None and score >= 75:
        return "Constructive setup. Keep it high on watch, but require price, volume, or catalyst confirmation."

    if "high" in risk_lower or "speculative" in risk_lower:
        return "Risk is elevated. Treat as watchlist-only unless the setup improves."

    return f"Current action bias: {action}. Use /stock for the readable intelligence card."


def build_related_commands(symbol: str) -> str:
    return f"""
/stock {symbol}
/volume {symbol}
/earnings {symbol}
/risk {symbol}
/top10
""".strip()


def build_scorecard_intelligence_report(symbol: str) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /scorecard SYMBOL"

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
        category = get_category(score_data)
    except Exception:
        category = "Uncategorized"

    try:
        story = get_score_story(score_data)
    except Exception:
        story = ""

    story = compact_text(
        story or f"{symbol} has a developing Smart Money scorecard.",
        260,
    )

    return f"""
🧾 {symbol} Smart Money Scorecard

Headline
Score: {format_score(score)}
Label: {label}
Signal Strength: {signal}
Risk: {risk}
Category: {category}

Score Components
{build_component_breakdown(score_data)}

Interpretation
{story}

{build_interpretation(symbol, score_data, score)}

Action Read
{build_action_read(score_data, score)}

Related Commands:
{build_related_commands(symbol)}

Research only. Not financial advice.
""".strip()