from datetime import datetime

from src.scoring.scoring_engine import get_stock_scores
from src.agents.analyst_agent import generate_ai_summary

try:
    from src.utils.watchlist_store import load_watchlist
    from src.commands.watchlist_commands import (
        fetch_quotes_for_symbols,
        format_change,
        format_large_number,
        format_percent,
        format_price,
    )
except Exception:
    load_watchlist = None
    fetch_quotes_for_symbols = None
    format_change = None
    format_large_number = None
    format_percent = None
    format_price = None


WATCHLIST_ALERT_THRESHOLD_PERCENT = 2.0


def safe_number(value, default=0):
    if isinstance(value, (int, float)):
        return value

    try:
        return float(value)
    except Exception:
        return default


def safe_text(value, default="N/A"):
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def build_score_lines(scores: list[dict], score_key: str, label: str, limit: int = 5) -> str:
    if not scores:
        return "No score data available."

    sorted_scores = sorted(
        scores,
        key=lambda item: safe_number(item.get(score_key)),
        reverse=True,
    )

    lines = []

    for index, stock in enumerate(sorted_scores[:limit], start=1):
        ticker = safe_text(stock.get("ticker"))
        score = safe_text(stock.get(score_key))
        category = safe_text(stock.get("category"))

        lines.append(
            f"{index}. {ticker} - {label}: {score} ({category})"
        )

    return "\n".join(lines)


def build_watchlist_daily_section() -> str:
    if load_watchlist is None or fetch_quotes_for_symbols is None:
        return (
            "📋 WATCHLIST INTELLIGENCE\n"
            "Watchlist module unavailable.\n"
        )

    try:
        watchlist_symbols = load_watchlist()

        if not watchlist_symbols:
            return (
                "📋 WATCHLIST INTELLIGENCE\n"
                "No watchlist symbols saved.\n\n"
                "Add symbols with:\n"
                "/watchlist add AAPL MSFT NVDA\n"
            )

        quote_results = fetch_quotes_for_symbols(watchlist_symbols)

        gainers = []
        losers = []
        flat_or_unknown = []
        alerts = []
        failed = []

        for symbol in watchlist_symbols:
            quote = quote_results.get(symbol)

            if not quote:
                failed.append((symbol, "No quote result"))
                continue

            if not quote.get("ok"):
                failed.append((symbol, quote.get("error", "Unknown error")))
                continue

            change_percent = quote.get("change_percent")

            if not isinstance(change_percent, (int, float)):
                flat_or_unknown.append(quote)
                continue

            if abs(change_percent) >= WATCHLIST_ALERT_THRESHOLD_PERCENT:
                alerts.append(quote)

            if change_percent > 0:
                gainers.append(quote)
            elif change_percent < 0:
                losers.append(quote)
            else:
                flat_or_unknown.append(quote)

        gainers.sort(key=lambda item: item.get("change_percent", 0), reverse=True)
        losers.sort(key=lambda item: item.get("change_percent", 0))
        alerts.sort(key=lambda item: abs(item.get("change_percent", 0)), reverse=True)

        total_with_data = len(gainers) + len(losers) + len(flat_or_unknown)

        lines = [
            "📋 WATCHLIST INTELLIGENCE",
            f"Tracked symbols: {len(watchlist_symbols)}",
            f"Symbols with data: {total_with_data}",
            f"Gainers: {len(gainers)}",
            f"Losers: {len(losers)}",
            f"Flat / no signal: {len(flat_or_unknown)}",
            f"Failed quotes: {len(failed)}",
            "",
        ]

        lines.append("🟢 TOP WATCHLIST GAINERS")

        if gainers:
            for quote in gainers[:5]:
                lines.append(
                    f"{quote['symbol']} - "
                    f"{format_price(quote.get('price'))} "
                    f"({format_percent(quote.get('change_percent'))}) "
                    f"{format_change(quote.get('change'))} "
                    f"| Vol: {format_large_number(quote.get('volume'))}"
                )
        else:
            lines.append("None")

        lines.append("")
        lines.append("🔴 TOP WATCHLIST LOSERS")

        if losers:
            for quote in losers[:5]:
                lines.append(
                    f"{quote['symbol']} - "
                    f"{format_price(quote.get('price'))} "
                    f"({format_percent(quote.get('change_percent'))}) "
                    f"{format_change(quote.get('change'))} "
                    f"| Vol: {format_large_number(quote.get('volume'))}"
                )
        else:
            lines.append("None")

        lines.append("")
        lines.append(f"🚨 WATCHLIST ALERTS OVER +/- {WATCHLIST_ALERT_THRESHOLD_PERCENT:.1f}%")

        if alerts:
            for quote in alerts[:10]:
                lines.append(
                    f"{quote['symbol']} - "
                    f"{format_price(quote.get('price'))} "
                    f"({format_percent(quote.get('change_percent'))}) "
                    f"{format_change(quote.get('change'))}"
                )
        else:
            lines.append("None")

        if failed:
            lines.append("")
            lines.append("Symbols without watchlist data:")

            for symbol, error in failed[:10]:
                lines.append(f"- {symbol}: {error}")

        return "\n".join(lines)

    except Exception as error:
        return (
            "📋 WATCHLIST INTELLIGENCE\n"
            "Watchlist section could not be generated.\n"
            f"Error: {type(error).__name__}\n"
        )


def build_daily_report():
    today = datetime.now().strftime("%B %d, %Y")

    scores = get_stock_scores()
    ai_summary = generate_ai_summary(scores)

    top_picks = build_score_lines(
        scores=scores,
        score_key="final_score",
        label="Score",
        limit=5,
    )

    defense_picks = build_score_lines(
        scores=scores,
        score_key="defense_score",
        label="Defense Score",
        limit=5,
    )

    watchlist_section = build_watchlist_daily_section()

    report = f"""
🚀 SMART MONEY AI
Daily Report - {today}

🔥 TOP PICKS
{top_picks}

🛡️ DEFENSE INTELLIGENCE
{defense_picks}

{watchlist_section}

📊 PORTFOLIO STRATEGY
Growth: 40%
Defense / AI Warfare: 20%
ETFs: 25%
Dividend: 15%

🧠 AI ANALYST SUMMARY
{ai_summary}

COMMANDS
/watchlist report
/watchlist movers
/watchlist alerts
/watchlist add SYMBOL

Status: MVP scoring engine active
"""
    return report.strip()