from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("$", "")


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_percent(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.2f}%"


def format_score(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    if number.is_integer():
        return str(int(number))

    return f"{number:.1f}"


def get_quote_value(quote: dict | None, keys: list[str]):
    if not quote:
        return None

    for key in keys:
        value = quote.get(key)

        if value is not None:
            return value

    return None


def get_price(quote: dict | None):
    return get_quote_value(
        quote,
        [
            "price",
            "regularMarketPrice",
            "regular_market_price",
            "current_price",
            "last_price",
        ],
    )


def get_change_percent(quote: dict | None):
    return get_quote_value(
        quote,
        [
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "regular_market_change_percent",
            "changePercent",
        ],
    )


def get_quote_for_symbol(quotes: dict | None, symbol: str) -> dict | None:
    clean = clean_symbol(symbol)

    if not isinstance(quotes, dict):
        return None

    direct = quotes.get(clean)

    if isinstance(direct, dict):
        return direct

    for value in quotes.values():
        if not isinstance(value, dict):
            continue

        quote_symbol = clean_symbol(
            value.get("symbol") or value.get("ticker") or ""
        )

        if quote_symbol == clean:
            return value

    return None


def stock_symbol(stock: Any) -> str:
    if isinstance(stock, dict):
        return clean_symbol(
            stock.get("ticker")
            or stock.get("symbol")
            or stock.get("name")
            or "UNKNOWN"
        )

    return clean_symbol(stock)


def stock_score(stock: Any) -> float | None:
    if not isinstance(stock, dict):
        return None

    for key in ["final_score", "smart_score", "score", "total_score"]:
        value = stock.get(key)

        if value is not None:
            return safe_float(value)

    return None


def stock_category(stock: Any) -> str:
    if not isinstance(stock, dict):
        return "N/A"

    return str(stock.get("category") or "N/A")


def classify_score(score: float | None) -> str:
    if score is None:
        return "Unrated"
    if score >= 90:
        return "Elite"
    if score >= 80:
        return "Strong"
    if score >= 70:
        return "Good"
    if score >= 60:
        return "Average"
    if score >= 50:
        return "Weak watch"
    return "Low conviction"


def classify_daily_move(change_percent: float | None) -> str:
    if change_percent is None:
        return "No move data"
    if change_percent >= 5:
        return "Major gain"
    if change_percent >= 2:
        return "Strong gain"
    if change_percent > 0:
        return "Positive"
    if change_percent <= -5:
        return "Major drop"
    if change_percent <= -2:
        return "Weak"
    if change_percent < 0:
        return "Slightly down"
    return "Flat"


def build_watchlist_rows(watchlist: list[Any], quotes: dict | None) -> list[dict]:
    rows = []

    for stock in watchlist:
        symbol = stock_symbol(stock)
        quote = get_quote_for_symbol(quotes, symbol)
        price = safe_float(get_price(quote))
        change_percent = safe_float(get_change_percent(quote))
        score = stock_score(stock)

        rows.append(
            {
                "symbol": symbol,
                "category": stock_category(stock),
                "score": score,
                "score_label": classify_score(score),
                "price": price,
                "change_percent": change_percent,
                "move_label": classify_daily_move(change_percent),
            }
        )

    return rows


def sort_by_score(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: row["score"] if row["score"] is not None else -999,
        reverse=True,
    )


def sort_by_move(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: row["change_percent"]
        if row["change_percent"] is not None
        else -999,
        reverse=True,
    )


def format_rows(rows: list[dict], limit: int = 10) -> str:
    if not rows:
        return "No watchlist symbols available."

    lines = []

    for index, row in enumerate(rows[:limit], start=1):
        lines.append(
            f"{index}. {row['symbol']} — "
            f"{format_price(row['price'])} | "
            f"{format_percent(row['change_percent'])} | "
            f"Score: {format_score(row['score'])} "
            f"({row['score_label']})"
        )

    return "\n".join(lines)


def build_summary(rows: list[dict]) -> str:
    total = len(rows)

    if total == 0:
        return "No symbols currently in the watchlist."

    gainers = [
        row for row in rows
        if row["change_percent"] is not None and row["change_percent"] > 0
    ]

    losers = [
        row for row in rows
        if row["change_percent"] is not None and row["change_percent"] < 0
    ]

    scored = [
        row for row in rows
        if row["score"] is not None
    ]

    strong = [
        row for row in scored
        if row["score"] >= 80
    ]

    return f"""
Total Symbols: {total}
Positive Today: {len(gainers)}
Negative Today: {len(losers)}
Scored Symbols: {len(scored)}
Strong Watchlist Names: {len(strong)}
""".strip()


def build_watchlist_report(watchlist: list[Any], quotes: dict | None = None) -> str:
    rows = build_watchlist_rows(watchlist, quotes)

    score_leaders = sort_by_score(rows)
    daily_movers = sort_by_move(rows)

    return f"""
📋 Smart Money AI Watchlist Report

Summary
{build_summary(rows)}

Top By Score
{format_rows(score_leaders, limit=10)}

Top Daily Movers
{format_rows(daily_movers, limit=10)}

Next Commands
/watchlist movers
/watchlist alerts
/top10
/marketbrief

Notes
This watchlist report is informational only and is not financial advice.
Verify market data before making investment decisions.
""".strip()