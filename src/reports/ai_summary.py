from typing import Any


MAX_SUMMARY_ITEMS = 4


def safe_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any, max_length: int = 120) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


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


def get_signal_phrase(stock: dict) -> str:
    signals = []

    if get_score(stock, "congress_score") >= 65:
        signals.append("Congress")

    if get_score(stock, "insider_score") >= 65:
        signals.append("insiders")

    if get_score(stock, "final_score", "score", "smart_money_score") >= 75:
        signals.append("core score")

    if get_score(stock, "defense_score") >= 75:
        signals.append("stability")

    if not signals:
        return "limited signal confirmation"

    if len(signals) == 1:
        return f"{signals[0]} confirmation"

    return ", ".join(signals[:-1]) + f", and {signals[-1]} confirmation"


def get_risk_phrase(stock: dict) -> str:
    risk_label = clean_text(
        stock.get("risk_label")
        or stock.get("risk_level")
        or "",
        80,
    )

    category = clean_text(stock.get("category") or "", 100)

    combined = f"{risk_label} {category}".upper()

    if any(word in combined for word in ["HIGH RISK", "SPECULATIVE", "VOLATILE", "EARLY STAGE"]):
        return "higher-risk"

    if any(word in combined for word in ["LOW", "DEFENSIVE", "CORE", "STABLE"]):
        return "more controlled-risk"

    return "balanced-risk"


def rank_stocks(stocks: list[dict]) -> list[dict]:
    return sorted(
        stocks,
        key=lambda stock: (
            get_signal_overlap(stock),
            get_score(stock, "final_score", "score", "smart_money_score"),
            get_score(stock, "congress_score") + get_score(stock, "insider_score"),
            get_score(stock, "defense_score"),
        ),
        reverse=True,
    )


def find_best_themes(stocks: list[dict]) -> list[str]:
    themes = []

    for stock in rank_stocks(stocks):
        category = clean_text(stock.get("category") or "", 80)

        if not category:
            continue

        simplified = category.split("/")[0].strip()

        if simplified and simplified not in themes:
            themes.append(simplified)

        if len(themes) >= 3:
            break

    return themes


def build_top_idea_sentence(stocks: list[dict]) -> str:
    ranked = rank_stocks(stocks)

    if not ranked:
        return "No ranked opportunities were available for today’s report."

    top = ranked[0]

    ticker = clean_symbol(top.get("ticker"))
    final_score = get_score(top, "final_score", "score", "smart_money_score")
    category = clean_text(top.get("category") or "its category", 80)
    signal_phrase = get_signal_phrase(top)
    risk_phrase = get_risk_phrase(top)

    return (
        f"{ticker} leads today’s board with a {final_score:.0f}/100 score, "
        f"supported by {signal_phrase}. The setup is strongest as a {risk_phrase} "
        f"idea within {category}."
    )


def build_breadth_sentence(stocks: list[dict]) -> str:
    if not stocks:
        return "Signal breadth is limited because no scoring data was available."

    strong = [
        stock
        for stock in stocks
        if get_score(stock, "final_score", "score", "smart_money_score") >= 80
    ]

    overlap = [
        stock
        for stock in stocks
        if get_signal_overlap(stock) >= 3
    ]

    themes = find_best_themes(stocks)

    theme_text = ", ".join(themes) if themes else "mixed sectors"

    return (
        f"Signal breadth is concentrated in {theme_text}. "
        f"{len(strong)} names score 80+ and {len(overlap)} names show 3+ overlapping signals."
    )


def build_watch_sentence(stocks: list[dict]) -> str:
    ranked = rank_stocks(stocks)

    if len(ranked) < 2:
        return "The next step is to refresh Congress and insider data before making a stronger read."

    watch_names = [
        clean_symbol(stock.get("ticker"))
        for stock in ranked[1:4]
        if clean_symbol(stock.get("ticker"))
    ]

    if not watch_names:
        return "The next step is to monitor whether the top score can hold after the next data refresh."

    return (
        "Watch "
        + ", ".join(watch_names)
        + " next. These names have enough signal strength to matter, "
        "but need confirmation from price action, risk profile, or fresh smart-money activity."
    )


def build_risk_sentence(stocks: list[dict]) -> str:
    high_risk = [
        stock
        for stock in stocks
        if get_risk_phrase(stock) == "higher-risk"
    ]

    controlled = [
        stock
        for stock in stocks
        if get_risk_phrase(stock) == "more controlled-risk"
    ]

    if high_risk and controlled:
        return (
            "Risk is mixed: there are attractive aggressive-growth ideas, but the cleaner setups "
            "are still the ones with stronger stability scores."
        )

    if high_risk:
        return (
            "Risk is elevated today. Treat the highest-scoring speculative names as watchlist ideas, "
            "not automatic buys."
        )

    if controlled:
        return (
            "Risk looks more controlled today, with several higher-quality names supported by stability or defensive characteristics."
        )

    return (
        "Risk is balanced. The best setups are the names where score strength and signal overlap agree."
    )


def build_ai_summary(stocks: list[dict] | None = None, quotes: Any = None, max_items: int = MAX_SUMMARY_ITEMS) -> str:
    stocks = stocks or []

    ranked = rank_stocks(stocks)[:max_items]

    if not ranked:
        return (
            "AI Summary\n"
            "Today’s report does not have enough ranked scoring data to build a strong read. "
            "Refresh market, Congress, and insider data, then rerun /report."
        )

    top_symbols = ", ".join(
        clean_symbol(stock.get("ticker"))
        for stock in ranked
        if clean_symbol(stock.get("ticker"))
    )

    return f"""
AI Summary
Today’s Read: {build_top_idea_sentence(stocks)}

Market Tone: {build_breadth_sentence(stocks)}

Risk Check: {build_risk_sentence(stocks)}

What To Watch: {build_watch_sentence(stocks)}

Focus List: {top_symbols}

Bottom Line: Favor names where the final score, smart-money signals, and risk profile line up. Avoid chasing high scores when the risk label or signal overlap does not confirm the move.
""".strip()