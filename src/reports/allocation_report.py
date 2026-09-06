from datetime import datetime
from typing import Any

from src.scoring.scoring_engine import get_stock_scores


GROWTH_TERMS = [
    "ai",
    "chip",
    "semiconductor",
    "growth",
    "software",
    "cloud",
    "technology",
    "tech",
    "infrastructure",
]

DEFENSE_TERMS = [
    "defense",
    "drone",
    "cyber",
    "warfare",
    "aerospace",
    "autonomous",
    "missile",
    "security",
    "military",
]

INCOME_TERMS = [
    "dividend",
    "income",
    "utility",
    "reit",
    "staples",
    "consumer defensive",
    "quality dividend",
]

SPECULATIVE_TERMS = [
    "speculative",
    "early",
    "small cap",
    "small-cap",
    "unprofitable",
    "turnaround",
]


def safe_number(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()

        return float(value)
    except Exception:
        return default


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def get_score(stock: dict) -> float:
    return safe_number(
        stock.get(
            "final_score",
            stock.get(
                "score",
                stock.get(
                    "smart_score",
                    stock.get("smart_money_score", stock.get("total_score", 0)),
                ),
            ),
        ),
        default=0,
    )


def get_category(stock: dict) -> str:
    return str(
        stock.get("category")
        or stock.get("theme")
        or stock.get("sector")
        or stock.get("industry")
        or "General Market"
    ).strip()


def get_risk_text(stock: dict) -> str:
    return str(
        stock.get("risk_label")
        or stock.get("risk_level")
        or stock.get("risk")
        or ""
    ).strip()


def category_has(category: str, terms: list[str]) -> bool:
    text = str(category or "").lower()

    return any(term in text for term in terms)


def classify_bucket(stock: dict) -> str:
    category = get_category(stock)

    if category_has(category, DEFENSE_TERMS):
        return "defense"

    if category_has(category, INCOME_TERMS):
        return "income"

    if category_has(category, SPECULATIVE_TERMS):
        return "speculative"

    if category_has(category, GROWTH_TERMS):
        return "growth"

    return "general"


def normalize_scores(raw_scores: Any) -> list[dict]:
    if isinstance(raw_scores, list):
        scores = [item for item in raw_scores if isinstance(item, dict)]
    elif isinstance(raw_scores, dict):
        scores = []
        for symbol, value in raw_scores.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("ticker", symbol)
                item.setdefault("symbol", symbol)
                scores.append(item)
            else:
                scores.append({"ticker": symbol, "symbol": symbol, "score": value})
    else:
        scores = []

    return sorted(scores, key=get_score, reverse=True)


def summarize_score_stack(scores: list[dict]) -> dict:
    selected = scores[:10]
    top_five = selected[:5]

    avg_top_score = (
        sum(get_score(item) for item in top_five) / len(top_five)
        if top_five
        else 0
    )

    buckets = {
        "growth": 0,
        "defense": 0,
        "income": 0,
        "speculative": 0,
        "general": 0,
    }

    high_risk_count = 0

    for item in selected:
        bucket = classify_bucket(item)
        buckets[bucket] = buckets.get(bucket, 0) + 1

        risk_text = get_risk_text(item).lower()

        if "high" in risk_text or "speculative" in risk_text or "elevated" in risk_text:
            high_risk_count += 1

    return {
        "avg_top_score": avg_top_score,
        "buckets": buckets,
        "high_risk_count": high_risk_count,
        "top_symbols": [clean_symbol(item.get("ticker") or item.get("symbol")) for item in top_five],
    }


def infer_portfolio_posture(
    scores: list[dict],
    market_tone: str = "",
    macro_pressure: str = "",
) -> str:
    summary = summarize_score_stack(scores)
    avg_score = summary["avg_top_score"]
    high_risk_count = summary["high_risk_count"]

    tone = str(market_tone or "").lower()
    pressure = str(macro_pressure or "").lower()

    risk_off_terms = [
        "risk-off",
        "bearish",
        "defensive",
        "growth pressure",
        "volatility rising",
        "rate",
        "rates",
        "inflation",
        "fed",
        "oil",
        "geopolitical",
        "credit",
    ]

    if any(term in tone for term in ["risk-off", "bearish"]):
        return "Defensive"

    if any(term in pressure for term in risk_off_terms) and high_risk_count >= 2:
        return "Defensive / Selective"

    if avg_score >= 86 and high_risk_count <= 1 and "bullish" in tone:
        return "Constructive / Selective"

    if avg_score >= 82:
        return "Balanced / Selective"

    if avg_score >= 75:
        return "Cautious / Watchlist"

    return "Defensive / Research First"


def allocation_mix_for_posture(posture: str) -> dict[str, int]:
    posture_text = str(posture or "").lower()

    if "constructive" in posture_text:
        return {
            "Growth / AI": 40,
            "Defense / Cyber / AI Warfare": 20,
            "Quality Dividend / Income": 15,
            "Cash / Short-Term Defense": 15,
            "Speculative / Tactical": 10,
        }

    if "defensive" in posture_text:
        return {
            "Growth / AI": 25,
            "Defense / Cyber / AI Warfare": 20,
            "Quality Dividend / Income": 25,
            "Cash / Short-Term Defense": 20,
            "Speculative / Tactical": 10,
        }

    if "cautious" in posture_text:
        return {
            "Growth / AI": 30,
            "Defense / Cyber / AI Warfare": 20,
            "Quality Dividend / Income": 20,
            "Cash / Short-Term Defense": 20,
            "Speculative / Tactical": 10,
        }

    return {
        "Growth / AI": 35,
        "Defense / Cyber / AI Warfare": 20,
        "Quality Dividend / Income": 20,
        "Cash / Short-Term Defense": 15,
        "Speculative / Tactical": 10,
    }


def format_mix(mix: dict[str, int]) -> str:
    return "\n".join(f"• {label}: {weight}%" for label, weight in mix.items())


def build_reason_text(
    scores: list[dict],
    posture: str,
    market_tone: str = "",
    macro_pressure: str = "",
) -> str:
    summary = summarize_score_stack(scores)
    symbols = ", ".join(summary["top_symbols"][:5]) if summary["top_symbols"] else "the top-ranked names"

    tone_text = market_tone or "market tone is still developing"
    pressure_text = macro_pressure or "macro pressure is mixed"

    if "Defensive" in posture:
        return (
            f"{symbols} still deserve attention, but the portfolio should keep more ballast because "
            f"{tone_text.lower()} and {pressure_text.lower()} require confirmation before adding risk."
        )

    if "Constructive" in posture:
        return (
            f"{symbols} are leading the ranked list, and the setup is constructive. "
            "The better approach is still selective buying, not chasing extended moves."
        )

    if "Cautious" in posture:
        return (
            f"{symbols} are worth monitoring, but the score stack is not strong enough for aggressive positioning yet. "
            "Wait for cleaner confirmation from price, volume, news, and risk."
        )

    return (
        f"{symbols} support a balanced stance. The portfolio can participate in strong themes, "
        "but should keep enough defense and cash to handle volatility."
    )


def build_action_text(posture: str) -> str:
    posture_text = str(posture or "").lower()

    if "constructive" in posture_text:
        return "Add selectively to confirmed leaders. Keep position sizes disciplined and avoid chasing."

    if "defensive" in posture_text:
        return "Protect capital first. Keep cash available and require stronger confirmation before adding risk."

    if "cautious" in posture_text:
        return "Watch more than act. Use /tradeplans and /risk before sizing any new position."

    return "Stay balanced. Add only when the score, news context, volume, and risk profile agree."


def build_allocation_snapshot_section(
    scores: list[dict] | None = None,
    market_tone: str = "",
    macro_pressure: str = "",
) -> str:
    scores = normalize_scores(scores or [])

    posture = infer_portfolio_posture(
        scores=scores,
        market_tone=market_tone,
        macro_pressure=macro_pressure,
    )

    mix = allocation_mix_for_posture(posture)

    return f"""
Portfolio Allocation Snapshot
Posture: {posture}
Suggested Tilt: Growth / AI {mix["Growth / AI"]}%, Defense / Cyber / AI Warfare {mix["Defense / Cyber / AI Warfare"]}%, Quality Dividend / Income {mix["Quality Dividend / Income"]}%, Cash / Short-Term Defense {mix["Cash / Short-Term Defense"]}%, Speculative / Tactical {mix["Speculative / Tactical"]}%.
Action: {build_action_text(posture)}
""".strip()


def build_allocation_report() -> str:
    try:
        scores = normalize_scores(get_stock_scores())
    except Exception:
        scores = []

    posture = infer_portfolio_posture(scores=scores)
    mix = allocation_mix_for_posture(posture)
    reason = build_reason_text(scores=scores, posture=posture)
    action = build_action_text(posture)
    summary = summarize_score_stack(scores)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    top_symbols = ", ".join(summary["top_symbols"]) if summary["top_symbols"] else "No ranked names available"

    return f"""
📊 Portfolio Allocation Snapshot

Current Posture
Posture: {posture}
Top Ranked Names: {top_symbols}
Average Top Score: {summary["avg_top_score"]:.1f}/100
High-Risk Count: {summary["high_risk_count"]}

Suggested Tilt
{format_mix(mix)}

Why This Mix
{reason}

Action Plan
{action}

How To Use This
• Use /tradeplans to see which names fit the current posture.
• Use /tradeplan SYMBOL before acting on a single name.
• Use /risk SYMBOL and /volume SYMBOL before increasing position size.
• Use /contextstatus to confirm the Smart Money Summary providers are active.

Generated: {generated_at}

Research only. Not financial advice.
""".strip()
