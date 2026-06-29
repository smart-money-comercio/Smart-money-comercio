from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(symbol: Any) -> str:
    return str(symbol or "UNKNOWN").strip().upper().replace("$", "")


def format_score(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    if number.is_integer():
        return str(int(number))

    return f"{number:.1f}"


def format_adjustment(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "0"

    if number > 0:
        return f"+{number:.0f}"

    return f"{number:.0f}"


def get_first_text(value: Any, fallback: str) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                return text
        return fallback

    if isinstance(value, tuple):
        return get_first_text(list(value), fallback)

    if isinstance(value, str) and value.strip():
        return value.strip()

    return fallback


def clean_text(text: str, max_length: int = 120) -> str:
    cleaned = " ".join(str(text).split())

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3].rstrip() + "..."


def get_score(stock: dict) -> float:
    for key in ["final_score", "smart_money_score", "score", "total_score"]:
        value = safe_float(stock.get(key))

        if value is not None:
            return value

    return 0


def sort_stocks(stocks: list[dict]) -> list[dict]:
    return sorted(
        stocks,
        key=lambda stock: get_score(stock),
        reverse=True,
    )


def build_score_summary(stocks: list[dict]) -> str:
    if not stocks:
        return "No scoring data available."

    scored = [get_score(stock) for stock in stocks]
    scored = [score for score in scored if score is not None]

    if not scored:
        return "No scored symbols available."

    elite = len([score for score in scored if score >= 90])
    strong = len([score for score in scored if score >= 80])
    watchable = len([score for score in scored if score >= 70])

    return f"""
Total Scored Symbols: {len(stocks)}
Elite Scores 90+: {elite}
Strong Scores 80+: {strong}
Watchable Scores 70+: {watchable}
Highest Score: {format_score(max(scored))}
Average Score: {format_score(sum(scored) / len(scored))}
""".strip()


def build_rank_line(rank: int, stock: dict) -> str:
    ticker = clean_symbol(stock.get("ticker") or stock.get("symbol"))
    score = get_score(stock)
    rating = stock.get("rating") or "Unrated"
    risk_label = stock.get("risk_label") or "N/A"
    category = stock.get("category") or "N/A"
    category_adjustment = stock.get("category_adjustment", 0)

    top_strength = get_first_text(
        stock.get("strengths"),
        "No strength detail available.",
    )

    key_weakness = get_first_text(
        stock.get("weaknesses"),
        "No weakness detail available.",
    )

    return f"""
{rank}. {ticker} — {format_score(score)} / 100
Rating: {rating}
Risk: {risk_label}
Category: {category}
Category Adjustment: {format_adjustment(category_adjustment)}
Top Strength: {clean_text(top_strength)}
Key Weakness: {clean_text(key_weakness)}
""".strip()


def build_top10_report(stocks: list[dict], limit: int = 10) -> str:
    if not stocks:
        return (
            "🏆 Smart Money AI Top 10\n\n"
            "No stock scores are currently available."
        )

    ranked_stocks = sort_stocks(stocks)
    top_stocks = ranked_stocks[:limit]

    rank_blocks = [
        build_rank_line(index, stock)
        for index, stock in enumerate(top_stocks, start=1)
    ]

    return f"""
🏆 Smart Money AI Top 10

Score Summary
{build_score_summary(ranked_stocks)}

Top Ranked Stocks
{chr(10).join(rank_blocks)}

How To Use This
• Higher scores suggest stronger current opportunity ranking.
• Risk label helps separate high-conviction ideas from higher-risk trades.
• Category adjustment reflects strategic sector or theme tailwinds.
• Always confirm valuation, trend, earnings, and news before acting.

Next Commands
/scorecard SYMBOL
/ticker SYMBOL
/risk SYMBOL
/market SYMBOL
/report

Notes
This leaderboard is informational only and is not financial advice.
""".strip()