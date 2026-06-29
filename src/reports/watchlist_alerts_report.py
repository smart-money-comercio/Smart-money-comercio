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


def classify_alert(change_percent: float | None, threshold_percent: float) -> str:
    if change_percent is None:
        return "⚪ No signal"

    if change_percent >= threshold_percent:
        if change_percent >= 5:
            return "🟢 Major upside alert"
        return "🟢 Upside alert"

    if change_percent <= -threshold_percent:
        if change_percent <= -5:
            return "🔴 Major downside alert"
        return "🔴 Downside alert"

    return "⚪ Inside threshold"


def normalize_quote(symbol: str, quote: dict | None, threshold_percent: float) -> dict:
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
        "alert": classify_alert(change_percent, threshold_percent),
    }


def build_rows(
    symbols: list[str],
    quote_results: dict[str, dict],
    threshold_percent: float,
) -> tuple[list[dict], list[tuple[str, str]]]:
    rows = []
    failed = []

    for symbol in symbols:
        quote = normalize_quote(symbol, quote_results.get(symbol), threshold_percent)

        if not quote.get("ok"):
            failed.append((symbol, quote.get("error") or "Unknown error"))
            continue

        rows.append(quote)

    return rows, failed


def split_alerts(
    rows: list[dict],
    threshold_percent: float,
) -> tuple[list[dict], list[dict], list[dict]]:
    upside_alerts = []
    downside_alerts = []
    quiet_symbols = []

    for row in rows:
        change_percent = row.get("change_percent")

        if change_percent is None:
            quiet_symbols.append(row)
        elif change_percent >= threshold_percent:
            upside_alerts.append(row)
        elif change_percent <= -threshold_percent:
            downside_alerts.append(row)
        else:
            quiet_symbols.append(row)

    upside_alerts.sort(
        key=lambda item: item["change_percent"]
        if item["change_percent"] is not None
        else -999,
        reverse=True,
    )

    downside_alerts.sort(
        key=lambda item: item["change_percent"]
        if item["change_percent"] is not None
        else 999,
    )

    quiet_symbols.sort(
        key=lambda item: abs(item["change_percent"])
        if item["change_percent"] is not None
        else -1,
        reverse=True,
    )

    return upside_alerts, downside_alerts, quiet_symbols


def format_alert_row(index: int, row: dict) -> str:
    return (
        f"{index}. {row['symbol']} — "
        f"{format_price(row.get('price'))} | "
        f"{format_percent(row.get('change_percent'))} | "
        f"{format_change(row.get('change'))} | "
        f"Vol: {format_volume(row.get('volume'))} | "
        f"{row.get('alert')}"
    )


def format_quiet_row(index: int, row: dict) -> str:
    return (
        f"{index}. {row['symbol']} — "
        f"{format_price(row.get('price'))} | "
        f"{format_percent(row.get('change_percent'))}"
    )


def format_alert_section(title: str, rows: list[dict], limit: int = 10) -> str:
    lines = [title]

    if not rows:
        lines.append("None")
        return "\n".join(lines)

    for index, row in enumerate(rows[:limit], start=1):
        lines.append(format_alert_row(index, row))

    return "\n".join(lines)


def format_quiet_section(rows: list[dict], limit: int = 15) -> str:
    lines = ["⚪ Inside Threshold / No Alert"]

    if not rows:
        lines.append("None")
        return "\n".join(lines)

    for index, row in enumerate(rows[:limit], start=1):
        lines.append(format_quiet_row(index, row))

    if len(rows) > limit:
        lines.append(f"...and {len(rows) - limit} more inside threshold.")

    return "\n".join(lines)


def build_alert_tone(upside_alerts: list[dict], downside_alerts: list[dict]) -> str:
    if upside_alerts and downside_alerts:
        return "Mixed alert day — both upside and downside alerts triggered."

    if upside_alerts:
        return "Positive alert day — upside alerts are leading."

    if downside_alerts:
        return "Negative alert day — downside alerts are leading."

    return "Quiet alert day — no symbols crossed the threshold."


def build_failed_section(failed: list[tuple[str, str]]) -> str:
    if not failed:
        return ""

    lines = ["Symbols Without Alert Data"]

    for symbol, error in failed:
        lines.append(f"• {symbol}: {error}")

    return "\n" + "\n".join(lines) + "\n"


def build_watchlist_alerts_report(
    symbols: list[str],
    quote_results: dict[str, dict],
    threshold_percent: float,
) -> str:
    if not symbols:
        return (
            "🚨 Smart Money AI Watchlist Alerts\n\n"
            "Your watchlist is empty.\n\n"
            "Add symbols with:\n"
            "/watchlist add AAPL MSFT NVDA"
        )

    rows, failed = build_rows(symbols, quote_results, threshold_percent)
    upside_alerts, downside_alerts, quiet_symbols = split_alerts(
        rows,
        threshold_percent,
    )

    failed_section = build_failed_section(failed)
    total_alerts = len(upside_alerts) + len(downside_alerts)

    return f"""
🚨 Smart Money AI Watchlist Alerts

Summary
Threshold: +/- {threshold_percent:.2f}%
Total Symbols: {len(symbols)}
Triggered Alerts: {total_alerts}
Upside Alerts: {len(upside_alerts)}
Downside Alerts: {len(downside_alerts)}
Inside Threshold: {len(quiet_symbols)}
Unavailable: {len(failed)}
Alert Tone: {build_alert_tone(upside_alerts, downside_alerts)}

{format_alert_section("🟢 Upside Alerts", upside_alerts)}

{format_alert_section("🔴 Downside Alerts", downside_alerts)}

{format_quiet_section(quiet_symbols)}
{failed_section}
Next Commands
/watchlist alerts
/watchlist alerts 1
/watchlist alerts 2.5
/watchlist movers
/watchlist report

Notes
This alert report is informational only and is not financial advice.
Large price moves should be verified against news, volume, earnings, and broader market conditions.
""".strip()