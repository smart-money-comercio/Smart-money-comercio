from typing import Any

from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
)


SMART_MONEY_LABEL_TRANSLATIONS = {
    "Core Smart Money Quality": "Quality setup",
    "Core Smart Money quality": "Quality setup",
    "Prime Opportunity": "Top-ranked setup",
    "High Conviction": "High-conviction setup",
    "Strong Watch": "Strong watchlist candidate",
    "Developing Watch": "Developing setup",
    "Early Watch": "Early-stage setup",
    "Neutral": "Neutral setup",
    "Weak Signal": "Weak signal",
}


REPORT_PHRASE_REPLACEMENTS = {
    "Core Smart Money quality is strong": "Smart Money ranking is strong",
    "core smart money quality is strong": "Smart Money ranking is strong",
    "Core Smart Money Quality": "Quality setup",
    "core smart money quality": "quality setup",
}


def clean_text(value: Any, max_length: int = 140) -> str:
    text = " ".join(str(value or "").split())

    for old, new in REPORT_PHRASE_REPLACEMENTS.items():
        text = text.replace(old, new)

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def safe_number(value: Any) -> float:
    try:
        if value is None:
            return 0.0

        return float(value)
    except Exception:
        return 0.0


def get_score_value(stock: dict) -> float:
    return safe_number(
        stock.get("final_score")
        or stock.get("score")
        or stock.get("smart_money_score")
        or stock.get("total_score")
        or stock.get("rating_score")
    )


def translate_label(stock: dict) -> str:
    raw_label = get_smart_money_label(stock)
    return SMART_MONEY_LABEL_TRANSLATIONS.get(raw_label, raw_label)


def first_text(value: Any, fallback: str, max_length: int = 130) -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item, max_length)

            if text:
                return text

        return fallback

    if isinstance(value, tuple):
        return first_text(list(value), fallback, max_length)

    if isinstance(value, str) and value.strip():
        return clean_text(value, max_length)

    return fallback


def get_thesis(stock: dict) -> str:
    return first_text(
        stock.get("strengths")
        or stock.get("reason")
        or stock.get("thesis")
        or stock.get("bull_case")
        or stock.get("pros"),
        "Setup ranks well, but the thesis still needs price and volume confirmation.",
        max_length=135,
    )


def get_watch_reason(stock: dict) -> str:
    category = str(get_category(stock) or "").upper()
    action = get_action_label(stock)

    if "AI" in category or "SEMICONDUCTOR" in category or "TECH" in category:
        return f"AI/growth setup; confirm Nasdaq, earnings quality, and volume before acting. Action: {action}."

    if "DEFENSE" in category or "AEROSPACE" in category or "DRONE" in category or "MISSILE" in category:
        return f"Defense theme exposure; prioritize real DoD, munitions, cyber, ISR, or autonomous-systems demand. Action: {action}."

    if "ENERGY" in category or "OIL" in category or "POWER" in category or "UTILITY" in category:
        return f"Macro-sensitive setup; watch oil, rates, power demand, and infrastructure confirmation. Action: {action}."

    if "BANK" in category or "FINANCIAL" in category or "CREDIT" in category:
        return f"Financial conditions matter; confirm credit quality, yields, and market risk appetite. Action: {action}."

    return f"Strong enough to monitor, but still needs confirmation before sizing. Action: {action}."


def sort_stocks(stocks: list[dict]) -> list[dict]:
    return sorted(
        stocks or [],
        key=get_score_value,
        reverse=True,
    )


def build_top10_report(stocks: list[dict], limit: int = 20) -> str:
    if not stocks:
        return "No Smart Money ideas are available right now."

    limit = max(1, int(limit or 20))
    ranked_stocks = sort_stocks(stocks)
    top_stocks = ranked_stocks[:limit]

    lines = [
        f"🔥 Top {limit} Smart Money Ideas",
        "",
        "Ranked research list based on Smart Money AI scoring, theme fit, signal strength, portfolio fit, and confirmation needs.",
        "",
    ]

    for index, stock in enumerate(top_stocks, start=1):
        ticker = get_ticker(stock)
        label = translate_label(stock)
        signal = get_signal_strength(stock)
        fit = get_portfolio_fit(stock)
        volume = get_volume_label(stock)
        action = get_action_label(stock)
        category = get_category(stock)
        score = get_score_value(stock)
        thesis = get_thesis(stock)
        watch_reason = get_watch_reason(stock)

        lines.append(
            f"{index}. {ticker} — {label}"
            f"\n   Score: {score:.1f} | Signal: {signal} | Fit: {fit}"
            f"\n   Theme: {category} | Volume: {volume}"
            f"\n   Why it matters: {thesis}"
            f"\n   My read: {watch_reason}"
        )

    lines.append("")
    lines.append("Note: Research only. Not financial advice.")

    return "\n\n".join(lines)