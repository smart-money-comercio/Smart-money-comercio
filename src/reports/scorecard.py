from typing import Any

from src.scoring.scoring_engine import get_stock_scores, score_ticker
from src.utils.score_display import (
    get_action_label,
    get_category,
    get_portfolio_fit,
    get_risk_label,
    get_signal_strength,
    get_smart_money_label,
    get_ticker,
    get_volume_label,
)


CONGRESS_THRESHOLD = 65
INSIDER_THRESHOLD = 65
CORE_THRESHOLD = 75
STABILITY_THRESHOLD = 75


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
    return str(value or "").strip().upper().replace("$", "")


def get_score(stock: dict, *keys: str, default: float = 0) -> float:
    for key in keys:
        if stock.get(key) is not None:
            return safe_float(stock.get(key), default)

    return default


def first_list_text(value: Any, fallback: str = "No detail available yet.") -> str:
    if isinstance(value, list):
        for item in value:
            text = clean_text(item, 160)
            if text:
                return text

    if isinstance(value, str) and value.strip():
        return clean_text(value, 160)

    return fallback


def format_list_block(value: Any, fallback: str) -> str:
    if isinstance(value, list) and value:
        cleaned = [
            clean_text(item, 160)
            for item in value[:4]
            if clean_text(item, 160)
        ]

        if cleaned:
            return "\n".join(f"- {item}" for item in cleaned)

    if isinstance(value, str) and value.strip():
        return f"- {clean_text(value, 180)}"

    return f"- {fallback}"


def get_signal_flags(stock: dict) -> dict:
    congress_score = get_score(stock, "congress_score")
    insider_score = get_score(stock, "insider_score")
    final_score = get_score(stock, "final_score", "score", "smart_money_score")
    stability_score = get_score(stock, "defense_score", "stability_score")

    return {
        "congress": congress_score >= CONGRESS_THRESHOLD,
        "insider": insider_score >= INSIDER_THRESHOLD,
        "core": final_score >= CORE_THRESHOLD,
        "stability": stability_score >= STABILITY_THRESHOLD,
    }


def get_signal_count(stock: dict) -> int:
    flags = get_signal_flags(stock)
    return sum(1 for enabled in flags.values() if enabled)


def get_overlap_label(stock: dict) -> str:
    count = get_signal_count(stock)

    if count >= 4:
        return "Elite Overlap"
    if count == 3:
        return "Strong Overlap"
    if count == 2:
        return "Building Overlap"
    if count == 1:
        return "Early Signal"

    return "Limited Signal"


def get_signal_icons(stock: dict) -> str:
    flags = get_signal_flags(stock)

    return " | ".join(
        [
            "Congress ✅" if flags["congress"] else "Congress ⚪",
            "Insiders ✅" if flags["insider"] else "Insiders ⚪",
            "Core ✅" if flags["core"] else "Core ⚪",
            "Stability ✅" if flags["stability"] else "Stability ⚪",
        ]
    )


def find_stock(symbol: str, stocks: list[dict]) -> dict | None:
    wanted = clean_symbol(symbol)

    for stock in stocks or []:
        current = clean_symbol(stock.get("ticker") or stock.get("symbol"))

        if current == wanted:
            return stock

    return None


def find_score_for_symbol(stocks: Any, symbol: Any = None) -> dict | None:
    if isinstance(stocks, str) and isinstance(symbol, list):
        stocks, symbol = symbol, stocks

    wanted = clean_symbol(symbol)

    for stock in stocks or []:
        if not isinstance(stock, dict):
            continue

        current = clean_symbol(stock.get("ticker") or stock.get("symbol"))

        if current == wanted:
            return stock

    return None


def get_quote_for_symbol(symbol: str) -> dict:
    ticker = clean_symbol(symbol)

    return {
        "ticker": ticker,
        "symbol": ticker,
        "price": None,
        "change_percent": None,
        "status": "Quote data not required for label-based scorecard.",
    }

def normalize_scores(scores: Any) -> list[dict]:
    """
    Backward-compatible helper used by market_commands.py.

    Accepts:
    - list[dict]
    - dict[ticker, dict]
    - dict[ticker, score]
    - None

    Returns a clean list of stock dictionaries.
    """
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
            ticker = clean_symbol(symbol)

            if isinstance(value, dict):
                stock = dict(value)
                stock.setdefault("ticker", ticker)
                stock.setdefault("symbol", ticker)
                normalized.append(stock)
            else:
                normalized.append(
                    {
                        "ticker": ticker,
                        "symbol": ticker,
                        "final_score": safe_float(value, 0),
                        "score": safe_float(value, 0),
                        "smart_money_score": safe_float(value, 0),
                    }
                )

        return normalized

    return []

def load_stock(symbol: str, stocks: Any = None) -> tuple[dict, bool]:
    wanted = clean_symbol(symbol)

    if isinstance(stocks, dict):
        return stocks, True

    if stocks is None:
        try:
            stocks = get_stock_scores()
        except Exception:
            stocks = []

    found = find_stock(wanted, stocks)

    if found:
        return found, True

    return score_ticker(wanted), False


def get_setup_type(stock: dict) -> str:
    category = get_category(stock).upper()
    label = get_smart_money_label(stock)
    risk = get_risk_label(stock).upper()

    if "DIVIDEND" in category or "INCOME" in category:
        return "Income and stability setup"

    if "CYBER" in category:
        return "Cybersecurity growth setup"

    if "DEFENSE" in category or "DRONE" in category or "WARFARE" in category:
        return "Defense and national-security setup"

    if "AI" in category or "SEMICONDUCTOR" in category:
        return "AI infrastructure setup"

    if "SPECULATIVE" in category or "HIGH RISK" in risk:
        return "Speculative watch setup"

    if label in {"Prime Opportunity", "High Conviction"}:
        return "High-conviction quality setup"

    if label == "Strong Watch":
        return "Strong watchlist setup"

    return "General Smart Money watch setup"


def build_thesis(stock: dict) -> str:
    ticker = get_ticker(stock)
    category = get_category(stock)
    label = get_smart_money_label(stock)
    signal = get_signal_strength(stock)
    volume = get_volume_label(stock)
    fit = get_portfolio_fit(stock)
    strength = first_list_text(
        stock.get("strengths") or stock.get("reason") or stock.get("thesis"),
        "The thesis is still developing and needs more confirmation.",
    )

    return (
        f"{ticker} screens as a {label} idea in {category}. "
        f"The setup currently shows {signal.lower()} signal confirmation, "
        f"a {fit.lower()} profile, and a volume signal of {volume}. "
        f"Key positive: {strength}"
    )


def build_conviction_readout(stock: dict) -> str:
    label = get_smart_money_label(stock)
    signal = get_signal_strength(stock)
    overlap = get_overlap_label(stock)
    volume = get_volume_label(stock)
    action = get_action_label(stock)

    if label in {"Prime Opportunity", "High Conviction"} and signal in {"Confirmed", "Strong"}:
        conviction = "High conviction research candidate"
    elif label in {"High Conviction", "Strong Watch"} and signal in {"Strong", "Improving"}:
        conviction = "Positive watch"
    elif signal in {"Improving", "Early"}:
        conviction = "Developing conviction"
    elif label in {"Neutral", "Weak Signal"}:
        conviction = "Monitor only"
    else:
        conviction = "Watchlist candidate"

    return (
        f"{conviction}. "
        f"Smart Money rating is {label}, signal strength is {signal}, "
        f"overlap is {overlap}, volume is {volume}, and the suggested action is {action}."
    )


def build_break_thesis(stock: dict) -> str:
    ticker = get_ticker(stock)
    signal = get_signal_strength(stock)
    volume = get_volume_label(stock)
    weakness = first_list_text(
        stock.get("weaknesses") or stock.get("risks"),
        "Risk profile should be reviewed before increasing conviction.",
    )

    if signal in {"Thin", "Early"}:
        return (
            f"The thesis weakens if {ticker} cannot add stronger confirmation from "
            f"Smart Money signals, market trend, or volume. Main concern: {weakness}"
        )

    if volume == "Quiet Volume":
        return (
            "The thesis weakens if volume remains quiet while price action fades. "
            f"Main concern: {weakness}"
        )

    return (
        "The thesis weakens if signal confirmation fades, risk increases, or the market stops supporting the setup. "
        f"Main concern: {weakness}"
    )


def build_next_steps(stock: dict) -> str:
    ticker = get_ticker(stock)
    action = get_action_label(stock)
    signal = get_signal_strength(stock)

    if action == "Review First":
        return (
            f"- Run /risk {ticker}\n"
            f"- Run /volume {ticker}\n"
            f"- Compare with /portfolio {ticker}"
        )

    if action == "Watch Closely":
        return (
            f"- Run /volume {ticker}\n"
            f"- Run /smartmoney {ticker}\n"
            f"- Recheck after /volume refresh"
        )

    if signal in {"Thin", "Early"}:
        return (
            f"- Keep {ticker} on watch\n"
            f"- Run /ticker {ticker}\n"
            f"- Recheck later with /analyst {ticker}"
        )

    return (
        f"- Run /analyst {ticker}\n"
        f"- Run /risk {ticker}\n"
        f"- Review position size before acting"
    )


def build_scorecard(
    ticker_or_stock: Any,
    stocks: Any = None,
    quote: dict | None = None,
) -> str:
    if isinstance(ticker_or_stock, dict):
        stock = ticker_or_stock
        curated = True
    else:
        symbol = clean_symbol(ticker_or_stock)
        stock, curated = load_stock(symbol, stocks)

    ticker = get_ticker(stock)
    category = get_category(stock)
    label = get_smart_money_label(stock)
    signal = get_signal_strength(stock)
    fit = get_portfolio_fit(stock)
    action = get_action_label(stock)
    risk = get_risk_label(stock)
    volume = get_volume_label(stock)
    setup_type = get_setup_type(stock)

    coverage_note = ""

    if not curated:
        coverage_note = f"""

Coverage Note:
{ticker} is not currently part of the curated Smart Money watchlist. This scorecard uses fallback scoring. For stronger analysis, add {ticker} to src/scoring/watchlist.py with a category, Smart Money profile, and stability profile.
""".rstrip()

    return f"""
📋 Smart Money Scorecard: {ticker}

Smart Money View:
Smart Money Rating: {label}
Signal Strength: {signal}
Smart Money Overlap: {get_overlap_label(stock)}
Portfolio Fit: {fit}
Action: {action}
Risk Profile: {risk}
Volume Signal: {volume}

Setup Type:
{setup_type}

Category:
{category}

Signal Map:
{get_signal_icons(stock)}

Conviction Readout:
{build_conviction_readout(stock)}

Thesis:
{build_thesis(stock)}

Strengths:
{format_list_block(stock.get("strengths"), "No major strength signal dominates yet.")}

Weaknesses:
{format_list_block(stock.get("weaknesses"), "No major weakness signal dominates yet.")}

Risk Notes:
{format_list_block(stock.get("risks"), "Review valuation, trend, earnings, market conditions, and position size.")}

What Could Break The Thesis:
{build_break_thesis(stock)}

Next Steps:
{build_next_steps(stock)}
{coverage_note}

Note:
This is research only, not financial advice.
""".strip()


def build_scorecard_report(
    ticker_or_stock: Any,
    stocks: Any = None,
    quote: dict | None = None,
) -> str:
    return build_scorecard(ticker_or_stock, stocks, quote)


def get_scorecard_report(
    ticker_or_stock: Any,
    stocks: Any = None,
    quote: dict | None = None,
) -> str:
    return build_scorecard(ticker_or_stock, stocks, quote)