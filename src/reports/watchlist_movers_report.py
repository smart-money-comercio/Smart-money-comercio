from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"${number:,.2f}"


def format_change(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""
    return f"{sign}{number:,.2f}"


def format_percent(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""
    return f"{sign}{number:.2f}%"


def format_volume(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    abs_value = abs(number)

    if abs_value >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"

    if abs_value >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"

    if abs_value >= 1_000:
        return f"{number / 1_000:.2f}K"

    return f"{number:,.0f}"


def classify_signal(change_percent: float | None) -> str:
    if change_percent is None:
        return "⚪ No signal"

    if change_percent >= 5:
        return "🟢 Major gain"
    if change_percent >= 2:
        return "🟢 Strong gain"
    if change_percent > 0:
        return "🟢 Positive"

    if change_percent <= -5:
        return "🔴 Major drop"
    if change_percent <= -2:
        return "🔴 Strong drop"
    if change_percent < 0:
        return "🔴 Negative"

    return "⚪ Flat"


def normalize_quote(symbol: str, quote: dict | None) -> dict:
    if not quote:
        return {
            "symbol": symbol,
            "ok": False,
            "error": "No quote result",
        }

    change_percent = safe_float(quote.get("change_percent"))
    change = safe_float(quote.get("change"))
    price = safe_float(quote.get("price"))
    volume = safe_float(quote.get("volume"))

    return {
        "symbol": quote.get("symbol") or symbol,
        "ok": bool(quote.get("ok")),
        "error": quote.get("error"),
        "price": price,
        "change": change,
        "change_percent": change_percent,
        "volume": volume,
        "exchange": quote.get("exchange") or "N/A",
        "market_state": quote.get("market_state") or "N/A",
        "instrument_type": quote.get("instrument_type") or "N/A",
        "signal": classify_signal(change_percent),
    }


def build_rows(symbols: list[str], quote_results: dict[str, dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    rows = []
    failed = []

    for symbol in symbols:
        quote = normalize_quote(symbol, quote_results.get(symbol))

        if not quote.get("ok"):
            failed.append((symbol, quote.get("error") or "Unknown error"))
            continue

        rows.append(quote)

    return rows, failed


def split_movers(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    gainers = []
    losers = []
    flat_or_unknown = []

    for row in rows:
        change_percent = row.get("change_percent")

        if change_percent is None:
            flat_or_unknown.append(row)
        elif change_percent > 0:
            gainers.append(row)
        elif change_percent < 0:
            losers.append(row)
        else:
            flat_or_unknown.append(row)

    gainers.sort(
        key=lambda item: item["change_percent"]
        if item["change_percent"] is not None
        else -999,
        reverse=True,
    )

    losers.sort(
        key=lambda item: item["change_percent"]
        if item["change_percent"] is not None
        else 999,
    )

    flat_or_unknown.sort(
        key=lambda item: item["symbol"]
    )

    return gainers, losers, flat_or_unknown


def format_mover_row(index: int, row: dict) -> str:
    return (
        f"{index}. {row['symbol']} — "
        f"{format_price(row.get('price'))} | "
        f"{format_percent(row.get('change_percent'))} | "
        f"{format_change(row.get('change'))} | "
        f"Vol: {format_volume(row.get('volume'))} | "
        f"{row.get('signal')}"
    )


def format_section(title: str, rows: list[dict], limit: int = 10) -> str:
    lines = [title]

    if not rows:
        lines.append("None")
        return "\n".join(lines)

    for index, row in enumerate(rows[:limit], start=1):
        lines.append(format_mover_row(index, row))

    return "\n".join(lines)


def build_market_tone(gainers: list[dict], losers: list[dict], flat_or_unknown: list[dict]) -> str:
    active_count = len(gainers) + len(losers)

    if active_count == 0:
        return "No clear market tone from current watchlist quote data."

    if len(gainers) > len(losers):
        return "Watchlist tone is positive today."
    if len(losers) > len(gainers):
        return "Watchlist tone is negative today."

    return "Watchlist tone is mixed today."


def build_failed_section(failed: list[tuple[str, str]]) -> str:
    if not failed:
        return ""

    lines = ["Symbols Without Mover Data"]

    for symbol, error in failed:
        lines.append(f"• {symbol}: {error}")

    return "\n" + "\n".join(lines) + "\n"


def build_watchlist_movers_report(symbols: list[str], quote_results: dict[str, dict]) -> str:
    if not symbols:
        return (
            "📊 Smart Money AI Watchlist Movers\n\n"
            "Your watchlist is empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )

    rows, failed = build_rows(symbols, quote_results)
    gainers, losers, flat_or_unknown = split_movers(rows)

    failed_section = build_failed_section(failed)

    return f"""
📊 Smart Money AI Watchlist Movers

Summary
Total Symbols: {len(symbols)}
Gainers: {len(gainers)}
Losers: {len(losers)}
Flat / Unknown: {len(flat_or_unknown)}
Unavailable: {len(failed)}
Market Tone: {build_market_tone(gainers, losers, flat_or_unknown)}

{format_section("🟢 Top Gainers", gainers)}

{format_section("🔴 Top Losers", losers)}

{format_section("⚪ Flat / No Signal", flat_or_unknown)}
{failed_section}
Next Commands
/watchlist report
/watchlist alerts
/watchlist alerts 1
/top10
/marketbrief

Notes
This movers report is informational only and is not financial advice.
Large moves should be verified against news, volume, and broader market conditions.
""".strip()