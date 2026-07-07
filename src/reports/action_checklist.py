from typing import Any


def safe_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 120) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def get_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if key in stock and stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


def get_signal_overlap(stock: dict) -> int:
    overlap = 0

    if get_score(stock, "congress_score") >= 65:
        overlap += 1

    if get_score(stock, "insider_score") >= 65:
        overlap += 1

    if get_score(stock, "final_score", "score", "smart_money_score") >= 75:
        overlap += 1

    if get_score(stock, "defense_score") >= 75:
        overlap += 1

    return overlap


def is_high_risk(stock: dict) -> bool:
    text = " ".join(
        [
            clean_text(stock.get("risk_label") or "", 100),
            clean_text(stock.get("risk_level") or "", 100),
            clean_text(stock.get("category") or "", 120),
        ]
    ).upper()

    high_risk_words = [
        "HIGH RISK",
        "HIGH",
        "SPECULATIVE",
        "VOLATILE",
        "EARLY STAGE",
        "AGGRESSIVE",
    ]

    return any(word in text for word in high_risk_words)


def rank_key(stock: dict) -> tuple:
    return (
        get_signal_overlap(stock),
        get_score(stock, "final_score", "score", "smart_money_score"),
        get_score(stock, "congress_score") + get_score(stock, "insider_score"),
        get_score(stock, "defense_score"),
    )


def get_top_candidates(stocks: list[dict], limit: int = 3) -> list[dict]:
    return sorted(stocks, key=rank_key, reverse=True)[:limit]


def get_high_risk_candidates(stocks: list[dict], limit: int = 3) -> list[dict]:
    candidates = [
        stock
        for stock in stocks
        if is_high_risk(stock)
        and get_score(stock, "final_score", "score", "smart_money_score") >= 70
    ]

    return sorted(candidates, key=rank_key, reverse=True)[:limit]


def get_watch_candidates(stocks: list[dict], limit: int = 3) -> list[dict]:
    candidates = [
        stock
        for stock in stocks
        if get_signal_overlap(stock) >= 2
        and get_score(stock, "final_score", "score", "smart_money_score") >= 70
    ]

    return sorted(candidates, key=rank_key, reverse=True)[:limit]


def symbols_line(stocks: list[dict]) -> str:
    symbols = [
        clean_symbol(stock.get("ticker") or stock.get("symbol"))
        for stock in stocks
        if clean_symbol(stock.get("ticker") or stock.get("symbol"))
    ]

    return ", ".join(symbols) if symbols else "None"


def build_review_line(stocks: list[dict]) -> str:
    top = get_top_candidates(stocks, limit=3)

    if not top:
        return "Review: No ranked candidates are available yet."

    return (
        f"Review: Start with {symbols_line(top)}. "
        "These names currently rank highest by score, overlap, and stability."
    )


def build_refresh_line(stocks: list[dict]) -> str:
    if not stocks:
        return "Refresh: Run /congress refresh and /insiders refresh before relying on today’s read."

    neutral_congress = [
        stock for stock in stocks
        if get_score(stock, "congress_score") == 50
    ]

    neutral_insider = [
        stock for stock in stocks
        if get_score(stock, "insider_score") == 50
    ]

    if len(neutral_congress) > len(stocks) * 0.50 or len(neutral_insider) > len(stocks) * 0.50:
        return "Refresh: Run /congress refresh and /insiders refresh to confirm today’s smart-money signals."

    return "Refresh: Data looks usable, but refresh Congress and insider caches before sending any major daily update."


def build_watch_line(stocks: list[dict]) -> str:
    watch = get_watch_candidates(stocks, limit=3)

    if not watch:
        return "Watch: Wait for stronger signal overlap before upgrading new names."

    return (
        f"Watch: Track {symbols_line(watch)} for confirmation from price action, "
        "fresh disclosures, or stronger risk-adjusted scoring."
    )


def build_risk_line(stocks: list[dict]) -> str:
    high_risk = get_high_risk_candidates(stocks, limit=3)

    if not high_risk:
        return "Risk Control: Favor names where score strength and stability agree."

    return (
        f"Risk Control: Do not chase {symbols_line(high_risk)} without reviewing /risk and /scorecard first. "
        "High score does not erase high volatility."
    )


def build_avoid_line(stocks: list[dict]) -> str:
    stretched = [
        stock
        for stock in stocks
        if get_score(stock, "final_score", "score", "smart_money_score") >= 75
        and get_signal_overlap(stock) <= 1
    ]

    if stretched:
        return (
            f"Avoid Chasing: {symbols_line(stretched[:3])} score well, "
            "but signal overlap is still thin. Wait for confirmation."
        )

    return "Avoid Chasing: Do not upgrade a name on score alone; require overlap, thesis, and risk confirmation."


def build_next_commands_line(stocks: list[dict]) -> str:
    top = get_top_candidates(stocks, limit=1)

    if not top:
        return "Next Commands: /top10, /smartmoney, /conviction, /undervalued"

    symbol = clean_symbol(top[0].get("ticker") or top[0].get("symbol"))

    if not symbol:
        return "Next Commands: /top10, /smartmoney, /conviction, /undervalued"

    return f"Next Commands: /scorecard {symbol}, /smartmoney {symbol}, /conviction {symbol}, /portfolio {symbol}"


def build_action_checklist(stocks: list[dict] | None = None) -> str:
    stocks = stocks or []

    return f"""
Action Checklist
1. {build_review_line(stocks)}
2. {build_refresh_line(stocks)}
3. {build_watch_line(stocks)}
4. {build_risk_line(stocks)}
5. {build_avoid_line(stocks)}
6. {build_next_commands_line(stocks)}
""".strip()