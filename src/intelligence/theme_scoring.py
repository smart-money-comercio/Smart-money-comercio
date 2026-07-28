from typing import Any

from src.intelligence.market_memory import load_market_memory


MAX_THEMES = 5


THEME_ACTIONS = {
    "ai / chips": "Action: require earnings quality, margin durability, order visibility, and volume confirmation.",
    "ai infrastructure / power": "Action: watch power demand, data-center capex, grid constraints, and infrastructure backlog.",
    "defense / ai warfare": "Action: prioritize DoD exposure, ISR, cyber, drones, autonomy, missile defense, and real contract flow.",
    "defense procurement / munitions": "Action: watch munitions depth, multi-year procurement, production capacity, backlog, and contract awards.",
    "oil / geopolitical risk": "Action: watch oil, shipping risk, yields, inflation expectations, and risk appetite.",
    "inflation / fed": "Action: watch Treasury yields, Fed language, CPI/PCE data, and duration-sensitive growth names.",
    "banks / credit": "Action: watch credit spreads, deposit trends, loan losses, liquidity, and regional-bank stress.",
    "consumer stress": "Action: watch guidance, delinquency data, spending weakness, and margin pressure.",
    "earnings season": "Action: prioritize guidance, backlog, margin commentary, and forward demand over headline EPS.",
    "market breadth / rotation": "Action: check whether leadership is broadening or narrowing before trusting index strength.",
}


def clean_text(value: Any, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def normalize_theme(value: Any) -> str:
    text = clean_text(value, 90)

    if not text:
        return ""

    aliases = {
        "AI / Chips": "AI / chips",
        "AI Infrastructure / Power": "AI infrastructure / power",
        "Defense / AI Warfare": "Defense / AI warfare",
        "Defense Procurement / Munitions": "Defense procurement / munitions",
        "Oil / Geopolitical Risk": "Oil / geopolitical risk",
        "Inflation / Fed": "Inflation / Fed",
        "Banks / Credit": "Banks / credit",
        "Consumer Stress": "Consumer stress",
        "Earnings Season": "Earnings season",
        "Market Breadth / Rotation": "Market breadth / rotation",
    }

    return aliases.get(text, text)


def get_context_themes(context: dict | None) -> list[str]:
    if not isinstance(context, dict):
        return []

    raw_themes = context.get("headline_themes") or []
    themes = []

    for item in raw_themes:
        theme = normalize_theme(item)

        if theme and theme not in themes:
            themes.append(theme)

    return themes[:MAX_THEMES]


def get_memory_days() -> list[dict]:
    memory = load_market_memory()
    days = memory.get("days") or []

    if not isinstance(days, list):
        return []

    return [
        day
        for day in days
        if isinstance(day, dict)
    ]


def theme_frequency(days: list[dict], theme: str, lookback: int = 5) -> int:
    count = 0

    for day in days[-lookback:]:
        day_themes = [
            normalize_theme(item)
            for item in day.get("themes", []) or []
        ]

        if theme in day_themes:
            count += 1

    return count


def previous_theme_frequency(days: list[dict], theme: str) -> int:
    if len(days) <= 5:
        return 0

    previous_window = days[-10:-5]
    count = 0

    for day in previous_window:
        day_themes = [
            normalize_theme(item)
            for item in day.get("themes", []) or []
        ]

        if theme in day_themes:
            count += 1

    return count


def classify_theme(theme: str, days: list[dict]) -> str:
    recent_count = theme_frequency(days, theme, lookback=5)
    prior_count = previous_theme_frequency(days, theme)

    if recent_count <= 1 and prior_count == 0:
        return "New theme"

    if recent_count >= 4:
        return "Persistent theme"

    if recent_count > prior_count and recent_count >= 2:
        return "Strengthening theme"

    if recent_count < prior_count and prior_count >= 2:
        return "Fading theme"

    if recent_count >= 2:
        return "Active theme"

    return "Watch theme"


def get_theme_action(theme: str) -> str:
    key = theme.lower()

    for known_theme, action in THEME_ACTIONS.items():
        if known_theme in key or key in known_theme:
            return action

    return "Action: require price, volume, headline quality, and watchlist confirmation before acting."


def build_theme_score_line(theme: str, days: list[dict], market_tone: str) -> str:
    classification = classify_theme(theme, days)
    recent_count = theme_frequency(days, theme, lookback=5)
    action = get_theme_action(theme)

    tone_note = ""

    if "risk-off" in market_tone.lower() or "defensive" in market_tone.lower():
        tone_note = " Market tone is defensive, so confirmation threshold should be higher."
    elif "risk-on" in market_tone.lower() or "bullish" in market_tone.lower():
        tone_note = " Market tone is supportive, but chasing still needs confirmation."

    return (
        f"• {theme}: {classification} — appeared {recent_count} of the last 5 reports. "
        f"{action}{tone_note}"
    )


def build_fallback_theme_scorecard(market_tone: str) -> str:
    return (
        f"• Theme history is still building. Market tone is {market_tone.lower()}.\n"
        "• Use today’s report as the baseline. Future reports will identify strengthening, fading, and persistent themes."
    )


def build_theme_scorecard(
    context: dict | None,
    market_tone: str,
    what_changed_today: str = "",
) -> str:
    themes = get_context_themes(context)
    days = get_memory_days()

    if not themes:
        return build_fallback_theme_scorecard(market_tone)

    if not days:
        return build_fallback_theme_scorecard(market_tone)

    lines = [
        build_theme_score_line(theme, days, market_tone)
        for theme in themes[:MAX_THEMES]
    ]

    change_text = str(what_changed_today or "").lower()

    if "new theme" in change_text:
        lines.append(
            "• Signal note: a new theme entered the report today, so the first job is to separate real demand from headline noise."
        )
    elif "theme persistence" in change_text:
        lines.append(
            "• Signal note: persistent themes need evidence. Do not reward repetition unless price, volume, and fundamentals confirm."
        )
    elif "market tone changed" in change_text:
        lines.append(
            "• Signal note: tone changed today, so position sizing matters more than the raw theme count."
        )

    return "\n".join(lines[:6])