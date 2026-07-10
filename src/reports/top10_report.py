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


def clean_text(value: Any, max_length: int = 140) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def first_text(value: Any, fallback: str) -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item)
            if text:
                return text
        return fallback

    if isinstance(value, str) and value.strip():
        return clean_text(value)

    return fallback


def build_top10_report(stocks: list[dict], limit: int = 10) -> str:
    if not stocks:
        return "No Smart Money ideas are available right now."

    top_stocks = stocks[:limit]

    lines = [
        "🔥 Top Smart Money Ideas",
        "",
        "These are ranked internally by Smart Money AI, but shown with simple labels instead of confusing scores.",
        "",
    ]

    for index, stock in enumerate(top_stocks, start=1):
        ticker = get_ticker(stock)
        label = get_smart_money_label(stock)
        signal = get_signal_strength(stock)
        fit = get_portfolio_fit(stock)
        volume = get_volume_label(stock)
        action = get_action_label(stock)
        category = get_category(stock)
        thesis = first_text(
            stock.get("strengths") or stock.get("reason"),
            "No thesis detail available yet.",
        )

        lines.append(
            f"{index}. {ticker} — {label}\n"
            f"   Signal: {signal}\n"
            f"   Fit: {fit}\n"
            f"   Action: {action}\n"
            f"   Theme: {category}\n"
            f"   Volume: {volume}\n"
            f"   Why it matters: {thesis}"
        )

    lines.append("")
    lines.append("Note: This is research only, not financial advice.")

    return "\n\n".join(lines)