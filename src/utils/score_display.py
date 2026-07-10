from typing import Any


def clean_text(value: Any, fallback: str = "N/A") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def get_smart_money_label(stock: dict) -> str:
    return clean_text(
        stock.get("smart_money_label")
        or stock.get("rating")
        or stock.get("signal"),
        "Monitor Only",
    )


def get_signal_strength(stock: dict) -> str:
    return clean_text(stock.get("signal_strength"), "Developing")


def get_portfolio_fit(stock: dict) -> str:
    return clean_text(stock.get("portfolio_fit"), "General Watchlist")


def get_action_label(stock: dict) -> str:
    return clean_text(stock.get("action_label"), "Review Carefully")


def get_risk_label(stock: dict) -> str:
    return clean_text(stock.get("risk_label"), "Balanced")


def get_score_story(stock: dict) -> str:
    story = stock.get("score_story")

    if story:
        return clean_text(story)

    return (
        f"{get_smart_money_label(stock)} | "
        f"Signal: {get_signal_strength(stock)} | "
        f"Fit: {get_portfolio_fit(stock)} | "
        f"Action: {get_action_label(stock)}"
    )


def get_category(stock: dict) -> str:
    return clean_text(stock.get("category"), "Uncategorized")


def get_ticker(stock: dict) -> str:
    return clean_text(stock.get("ticker") or stock.get("symbol"), "UNKNOWN").upper()


def format_stock_label_block(stock: dict) -> str:
    return (
        f"Smart Money Rating: {get_smart_money_label(stock)}\n"
        f"Signal Strength: {get_signal_strength(stock)}\n"
        f"Portfolio Fit: {get_portfolio_fit(stock)}\n"
        f"Action: {get_action_label(stock)}\n"
        f"Risk Profile: {get_risk_label(stock)}"
    )