from typing import Any

from src.utils.score_display import (
    format_stock_label_block,
    get_action_label,
    get_portfolio_fit,
    get_risk_label as get_display_risk_label,
    get_score_story,
    get_signal_strength,
    get_smart_money_label,
)


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

    return "No clear strength detail available yet."


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
        signals.append("core quality")

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
    text = f"{get_display_risk_label(stock)} {get_category(stock)}".upper()

    if any(
        word in text
        for word in ["HIGH", "SPECULATIVE", "VOLATILE", "EARLY STAGE", "AGGRESSIVE"]
    ):
        return "higher-risk"

    if any(
        word in text
        for word in ["LOW", "DEFENSIVE", "CONTROLLED", "CORE", "STABLE", "QUALITY"]
    ):
        return "controlled-risk"

    return "balanced-risk"


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


def get_setup_type(stock: dict) -> str:
    category = get_category(stock).upper()
    risk_tone = get_risk_tone(stock)
    label = get_smart_money_label(stock)
    congress = get_congress_score_value(stock)
    insider = get_insider_score_value(stock)

    if "DIVIDEND" in category or "INCOME" in category:
        return "income and stability setup"

    if "CYBER" in category:
        return "cybersecurity growth setup"

    if "DEFENSE" in category or "DRONE" in category or "WARFARE" in category:
        return "defense and national-security setup"

    if "AI" in category or "GROWTH" in category:
        if risk_tone == "higher-risk":
            return "aggressive AI growth setup"
        return "AI growth setup"

    if "HIGH CONVICTION" in label.upper() or "PRIME" in label.upper():
        return "quality compounder setup"

    if congress >= 65 and insider >= 65:
        return "smart-money confirmation setup"

    if "STRONG WATCH" in label.upper():
        return "strong watchlist setup"

    return "early watchlist setup"


def get_conviction_level(stock: dict) -> str:
    label = get_smart_money_label(stock)
    signal = get_signal_strength(stock)
    risk_tone = get_risk_tone(stock)

    if label in {"Prime Opportunity", "High Conviction"} and signal in {"Confirmed", "Strong"} and risk_tone != "higher-risk":
        return "High conviction"

    if label in {"High Conviction", "Strong Watch"} and signal in {"Strong", "Improving"}:
        return "Positive watch"

    if signal in {"Improving", "Early"}:
        return "Developing conviction"

    if label in {"Developing Watch", "Early Watch"}:
        return "Watchlist candidate"

    return "Low conviction"


def get_position_style(stock: dict) -> str:
    risk_tone = get_risk_tone(stock)
    signal = get_signal_strength(stock)
    label = get_smart_money_label(stock)
    category = get_category(stock).upper()

    if risk_tone == "higher-risk":
        return "best treated as a smaller, speculative position until confirmation improves"

    if "DIVIDEND" in category or "INCOME" in category:
        return "better suited for an income or defensive sleeve than an aggressive growth sleeve"

    if label in {"Prime Opportunity", "High Conviction"} and signal in {"Confirmed", "Strong"}:
        return "suitable for deeper review as a core or high-conviction watchlist candidate"

    if signal in {"Thin", "Early"}:
        return "best kept on watch until more signals confirm the thesis"

    return "appropriate for watchlist review with position size tied to risk tolerance"


def build_core_thesis(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    setup_type = get_setup_type(stock)
    label = get_smart_money_label(stock)
    signal_strength = get_signal_strength(stock)
    portfolio_fit = get_portfolio_fit(stock)
    action_label = get_action_label(stock)
    signal_phrase = get_signal_phrase(stock)
    risk_tone = get_risk_tone(stock)
    strength = get_strength(stock)

    return (
        f"{symbol} currently screens as a {setup_type}. "
        f"The Smart Money view is {label}, with {signal_strength.lower()} confirmation "
        f"and a {portfolio_fit.lower()} profile. "
        f"The setup is led by {signal_phrase}. "
        f"The thesis is strongest when viewed as a {risk_tone} idea where the key positive is: {strength} "
        f"The current action label is: {action_label}."
    )


def build_confirmation_logic(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    congress = get_congress_score_value(stock)
    insider = get_insider_score_value(stock)
    stability = get_stability_score(stock)
    label = get_smart_money_label(stock)

    confirmations = []

    if label in {"Prime Opportunity", "High Conviction", "Strong Watch"}:
        confirmations.append("the Smart Money rating is strong enough to justify continued review")

    if congress >= 65:
        confirmations.append("Congress activity is supportive")

    if insider >= 65:
        confirmations.append("insider activity adds confirmation")

    if stability >= 75:
        confirmations.append("the stability profile helps reduce setup risk")

    if not confirmations:
        return (
            f"{symbol} does not yet have strong confirmation. "
            "The setup needs better quality, smart-money activity, or risk support before conviction improves."
        )

    if len(confirmations) == 1:
        return f"Confirmation is still narrow: {confirmations[0]}."

    return "Confirmation is improving because " + ", ".join(confirmations[:-1]) + f", and {confirmations[-1]}."


def build_break_thesis_logic(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    risk_tone = get_risk_tone(stock)
    weakness = get_weakness(stock)
    signal_strength = get_signal_strength(stock)
    label = get_smart_money_label(stock)

    if risk_tone == "higher-risk":
        return (
            "The thesis weakens if volatility expands, the stock loses momentum, "
            "or the risk profile stops matching the expected upside. "
            f"Main risk to review: {weakness}"
        )

    if signal_strength in {"Thin", "Early"}:
        return (
            f"The thesis weakens if {symbol} cannot add more confirmation from smart-money activity, "
            f"price action, or stability. Main risk to review: {weakness}"
        )

    if label in {"Neutral", "Weak Signal"}:
        return (
            "The thesis weakens if the rating remains below watchlist quality. "
            f"Main risk to review: {weakness}"
        )

    return (
        "The thesis weakens if current signal confirmation fades or if the risk profile deteriorates. "
        f"Main risk to review: {weakness}"
    )


def build_next_step_logic(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    risk_tone = get_risk_tone(stock)
    signal_strength = get_signal_strength(stock)

    if risk_tone == "higher-risk":
        return f"Next step: run /risk {symbol} and /scorecard {symbol} before treating this as anything more than a speculative watch."

    if signal_strength in {"Confirmed", "Strong"}:
        return f"Next step: run /scorecard {symbol}, then compare it against /portfolio {symbol} to decide its best role."

    if signal_strength == "Improving":
        return f"Next step: run /smartmoney {symbol} and /conviction {symbol} to confirm whether the signal stack is improving."

    return f"Next step: keep {symbol} on watch and rerun /analyst {symbol} after fresh Congress, insider, or market data updates."


def build_single_stock_analysis(stock: dict) -> str:
    symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
    category = get_category(stock)
    conviction = get_conviction_level(stock)
    setup_type = get_setup_type(stock)
    position_style = get_position_style(stock)

    return f"""
{symbol} Analyst Read

Smart Money View:
{format_stock_label_block(stock)}

Conviction: {conviction}
Setup Type: {setup_type}
Category: {category}

Thesis:
{build_core_thesis(stock)}

Why It Matters:
{build_confirmation_logic(stock)}

Portfolio Role:
{symbol} is {position_style}.

What Could Break The Thesis:
{build_break_thesis_logic(stock)}

Analyst Take:
Favor {symbol} only if the thesis, risk profile, and signal confirmation still line up. A strong label alone is not enough; the best ideas need confirmation, role fit, and risk control.

{build_next_step_logic(stock)}
""".strip()


def build_ranked_analyst_summary(stocks: list[dict], limit: int = DEFAULT_MAX_ITEMS) -> str:
    ranked = rank_stocks(stocks)[:limit]

    if not ranked:
        return "No ranked analyst opportunities are available."

    lines = []

    for index, stock in enumerate(ranked, start=1):
        symbol = clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        category = get_category(stock)

        lines.append(
            f"{index}. {symbol} — {get_smart_money_label(stock)}\n"
            f"   Signal: {get_signal_strength(stock)}\n"
            f"   Fit: {get_portfolio_fit(stock)}\n"
            f"   Action: {get_action_label(stock)}\n"
            f"   Setup: {get_setup_type(stock)}\n"
            f"   Category: {category}"
        )

    return "\n\n".join(lines)


def build_market_analyst_take(stocks: list[dict]) -> str:
    if not stocks:
        return "Market analyst take unavailable because no scoring data was provided."

    ranked = rank_stocks(stocks)
    top = ranked[0]

    top_symbol = clean_symbol(get_value(top, ["ticker", "symbol", "name"], "UNKNOWN"))
    top_label = get_smart_money_label(top)
    top_signal = get_signal_strength(top)
    top_fit = get_portfolio_fit(top)

    strong_names = [
        clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        for stock in ranked
        if get_smart_money_label(stock) in {"Prime Opportunity", "High Conviction", "Strong Watch"}
    ]

    confirmed_names = [
        clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        for stock in ranked
        if get_signal_strength(stock) in {"Confirmed", "Strong"}
    ]

    higher_risk_names = [
        clean_symbol(get_value(stock, ["ticker", "symbol", "name"], "UNKNOWN"))
        for stock in ranked
        if get_risk_tone(stock) == "higher-risk"
    ]

    strong_text = ", ".join(strong_names[:4]) if strong_names else "none yet"
    confirmed_text = ", ".join(confirmed_names[:4]) if confirmed_names else "none yet"
    risk_text = ", ".join(higher_risk_names[:4]) if higher_risk_names else "limited"

    return (
        f"{top_symbol} leads the analyst board as a {top_label} idea with {top_signal.lower()} confirmation "
        f"and a {top_fit.lower()} profile. "
        f"The strongest watchlist names right now are: {strong_text}. "
        f"The cleanest confirmation appears in: {confirmed_text}. "
        f"Higher-risk names to size carefully: {risk_text}. "
        "The best setups are the names where Smart Money rating, signal confirmation, portfolio fit, and risk control agree."
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
Focus on names with strong Smart Money ratings, improving or confirmed signals, and a risk profile that matches the intended portfolio role.
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
A ticker alone is not enough for a full Smart Money AI read. The agent needs rating, category, signal, and risk data to produce a complete analysis.
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