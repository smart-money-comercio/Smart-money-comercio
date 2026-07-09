from typing import Any


DEFAULT_MAX_ITEMS = 5


def safe_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any, max_length: int = 180) -> str:
    if value is None:
        return ""

    text = " ".join(str(value).split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def clean_symbol(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("$", "")


def get_value(data: dict, keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value

    return default


def get_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


def get_final_score(stock: dict) -> float:
    return get_score(
        stock,
        "final_score",
        "score",
        "smart_money_score",
        "total_score",
        "rating_score",
    )


def get_congress_score_value(stock: dict) -> float:
    return get_score(stock, "congress_score", default=50)


def get_insider_score_value(stock: dict) -> float:
    return get_score(stock, "insider_score", default=50)


def get_stability_score(stock: dict) -> float:
    return get_score(stock, "defense_score", "stability_score", default=50)


def get_category(stock: dict) -> str:
    return clean_text(
        get_value(stock, ["category", "sector", "industry"], "Uncategorized"),
        120,
    )


def get_rating(stock: dict) -> str:
    return clean_text(
        get_value(stock, ["rating", "grade", "signal"], "Unrated"),
        80,
    )


def get_risk_label(stock: dict) -> str:
    return clean_text(
        get_value(stock, ["risk_label", "risk_level", "risk"], "N/A"),
        80,
    )


def get_strength(stock: dict) -> str:
    strengths = get_value(stock, ["strengths", "pros", "bull_case"], [])

    if isinstance(strengths, list):
        for item in strengths:
            text = clean_text(item, 140)
            if text:
                return text

    if isinstance(strengths, str) and strengths.strip():
        return clean_text(strengths, 140)

    reason = get_value(stock, ["reason", "thesis", "summary"], "")

    if reason:
        return clean_text(reason, 140)

    return "No clear strength detail available."


def get_weakness(stock: dict) -> str:
    weaknesses = get_value(stock, ["weaknesses", "cons", "bear_case", "risks"], [])

    if isinstance(weaknesses, list):
        for item in weaknesses:
            text = clean_text(item, 140)
            if text:
                return text

    if isinstance(weaknesses, str) and weaknesses.strip():
        return clean_text(weaknesses, 140)

    return "Risk should be reviewed before upgrading conviction."


def get_signal_overlap(stock: dict) -> int:
    overlap = 0

    if get_final_score(stock) >= 75:
        overlap += 1

    if get_congress_score_value(stock) >= 65:
        overlap += 1

    if get_insider_score_value(stock) >= 65:
        overlap += 1

    if get_stability_score(stock) >= 75:
        overlap += 1

    return overlap


def get_signal_phrase(stock: dict) -> str:
    signals = []

    if get_final_score(stock) >= 75:
        signals.append("score strength")

    if get_congress_score_value(stock) >= 65:
        signals.append("Congress activity")

    if get_insider_score_value(stock) >= 65:
        signals.append("insider activity")

    if get_stability_score(stock) >= 75:
        signals.append("stability")

    if not signals:
        return "limited confirmation"

    if len(signals) == 1:
        return signals[0]

    return ", ".join(signals[:-1]) + f", and {signals[-1]}"


def get_risk_tone(stock: dict) -> str:
    text = f"{get_risk_label(stock)} {get_category(stock)}".upper()

    if any(word in text for word in ["HIGH", "SPECULATIVE", "VOLATILE", "EARLY STAGE", "AGGRESSIVE"]):
        return "higher-risk"

    if any(word in text for word in ["LOW", "DEFENSIVE", "CORE", "STABLE", "QUALITY"]):
        return "controlled-risk"

    return "balanced-risk"


def classify_score(score: float) -> str:
    if score >= 90:
        return "Elite"
    if score >= 82:
        return "High conviction"
    if score >= 75:
        return "Strong watch"
    if score >= 68:
        return "Good watch"
    if score >= 60:
        return "Moderate watch"
    if score >= 50:
        return "Neutral"
    return "Weak"


def rank_stocks(stocks: list[dict]) -> list[dict]:
    return sorted(
        stocks or [],
        key=lambda stock: (
            get_signal_overlap(stock),
            get_final_score(stock),
            get_congress_score_value(stock) + get_insider_score_value(stock),
            get_stability_score(stock),
        ),
        reverse=True,
    )


def normalize_stocks(scores: Any) -> list[dict]:
    if not scores:
        return []

    if isinstance(scores, list):
        return [
            stock
            for stock in scores
            if isinstance(stock, dict)
        ]

    if isinstance(scores, dict):
        normalized = []

        for symbol, value in scores.items():
            if isinstance(value, dict):
                stock = dict(value)
                stock.setdefault("ticker", symbol)
                normalized.append(stock)
            else:
                normalized.append(
                    {
                        "ticker": symbol,
                        "final_score": value,
                    }
                )

        return normalized

    return []


def build_single_stock_analysis(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    final_score = get_final_score(stock)
    category = get_category(stock)
    rating = get_rating(stock)
    risk_label = get_risk_label(stock)
    signal_overlap = get_signal_overlap(stock)
    signal_phrase = get_signal_phrase(stock)
    risk_tone = get_risk_tone(stock)
    strength = get_strength(stock)
    weakness = get_weakness(stock)

    return f"""
{symbol} Analyst Read

Score: {final_score:.0f}/100 — {classify_score(final_score)}
Rating: {rating}
Category: {category}
Risk: {risk_label}
Signal Overlap: {signal_overlap}/4

Thesis:
{symbol} screens as a {risk_tone} idea with confirmation from {signal_phrase}. The strongest part of the setup is: {strength}

Risk Check:
{weakness}

Analyst Take:
Favor {symbol} only if the thesis, risk profile, and signal overlap still line up. A high score alone is not enough; confirmation matters.
""".strip()


def build_ranked_analyst_summary(stocks: list[dict], limit: int = DEFAULT_MAX_ITEMS) -> str:
    ranked = rank_stocks(stocks)[:limit]

    if not ranked:
        return "No ranked analyst opportunities are available."

    lines = []

    for index, stock in enumerate(ranked, start=1):
        symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        final_score = get_final_score(stock)
        category = get_category(stock)
        overlap = get_signal_overlap(stock)
        risk_tone = get_risk_tone(stock)
        signal_phrase = get_signal_phrase(stock)

        lines.append(
            f"{index}. {symbol} — {final_score:.0f}/100 | "
            f"{classify_score(final_score)} | {risk_tone}\n"
            f"   Category: {category}\n"
            f"   Confirmation: {overlap}/4 signals — {signal_phrase}"
        )

    return "\n\n".join(lines)


def build_market_analyst_take(stocks: list[dict]) -> str:
    if not stocks:
        return "Market analyst take unavailable because no scoring data was provided."

    ranked = rank_stocks(stocks)
    top = ranked[0]

    strong_count = len(
        [
            stock for stock in stocks
            if get_final_score(stock) >= 80
        ]
    )

    overlap_count = len(
        [
            stock for stock in stocks
            if get_signal_overlap(stock) >= 3
        ]
    )

    high_risk_count = len(
        [
            stock for stock in stocks
            if get_risk_tone(stock) == "higher-risk"
        ]
    )

    top_symbol = clean_symbol(get_value(top, ["ticker", "symbol", "name"], "UNKNOWN"))
    top_score = get_final_score(top)

    return (
        f"{top_symbol} leads the analyst board with a {top_score:.0f}/100 score. "
        f"Across the list, {strong_count} names score 80+ and {overlap_count} names show 3+ overlapping signals. "
        f"Risk remains important: {high_risk_count} ranked names carry higher-risk characteristics. "
        "The best setups are the names where score strength, smart-money confirmation, and risk control agree."
    )


def build_analyst_summary(scores: Any, symbol: str | None = None, limit: int = DEFAULT_MAX_ITEMS) -> str:
    stocks = normalize_stocks(scores)

    if symbol:
        wanted = clean_symbol(symbol)

        for stock in stocks:
            current_symbol = clean_symbol(
                get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN")
            )

            if current_symbol == wanted:
                return build_single_stock_analysis(stock)

        return f"No analyst data found for {wanted}."

    if not stocks:
        return "No analyst data available."

    return f"""
Smart Money AI Analyst Summary

Market Read:
{build_market_analyst_take(stocks)}

Top Analyst Ideas:
{build_ranked_analyst_summary(stocks, limit=limit)}

Bottom Line:
Focus on names with strong scores, multiple confirmation signals, and a risk profile that matches the intended portfolio role.
""".strip()


def generate_ai_summary(scores: Any) -> str:
    """
    Backward-compatible wrapper for older report code.
    """
    return build_analyst_summary(scores=scores, symbol=None, limit=4)


def generate_analyst_summary(scores: Any, symbol: str | None = None) -> str:
    """
    Compatibility wrapper for agent-style callers.
    """
    return build_analyst_summary(scores=scores, symbol=symbol, limit=5)


def analyze_stock(stock: Any) -> str:
    """
    Compatibility helper for single-stock callers.

    Accepts either:
    - a stock dictionary
    - a ticker string
    """

    if isinstance(stock, dict):
        return build_single_stock_analysis(stock)

    symbol = clean_symbol(stock)

    return f"""
{symbol} Analyst Read

Analyst data for {symbol} was requested, but only a ticker symbol was provided.
Use analyze_ticker(scores, "{symbol}") when full scoring data is available.

Analyst Take:
A ticker alone is not enough for a full Smart Money AI read. The agent needs score, category, signal, and risk data to produce a complete analysis.
""".strip()

def analyze_ticker(scores: Any, ticker: str) -> str:
    """
    Compatibility helper for ticker-based callers.
    """
    return build_analyst_summary(scores=scores, symbol=ticker, limit=5)


def run_analyst_agent(scores: Any, symbol: str | None = None) -> str:
    """
    Main deterministic analyst-agent entry point.
    """
    return build_analyst_summary(scores=scores, symbol=symbol, limit=5)