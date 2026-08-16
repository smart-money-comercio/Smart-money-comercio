import re
from typing import Any

from src.intelligence.stockanalysis_source import (
    clean_symbol,
    fetch_stockanalysis_data,
)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").replace(",", "").strip()
        match = re.search(r"-?\d+", text)

        if not match:
            return default

        return int(match.group(0))

    except Exception:
        return default


def metric_line(metrics: dict, key: str, label: str) -> str:
    value = metrics.get(key)

    if not value:
        return ""

    return f"• {label}: {value}"


def build_stockanalysis_rating_interpretation(metrics: dict) -> str:
    consensus = str(metrics.get("analyst_consensus") or "").lower()

    strong_buy = safe_int(metrics.get("strong_buy_count"))
    buy = safe_int(metrics.get("buy_count"))
    hold = safe_int(metrics.get("hold_count"))
    sell = safe_int(metrics.get("sell_count"))
    strong_sell = safe_int(metrics.get("strong_sell_count"))

    bullish = strong_buy + buy
    bearish = sell + strong_sell
    total = bullish + hold + bearish

    if "strong buy" in consensus:
        return "• Analyst setup is strongly bullish. Confirm with valuation, volume, filings, and macro risk."

    if "buy" in consensus:
        return "• Analyst setup leans bullish. Treat as supportive, not standalone confirmation."

    if "hold" in consensus:
        return "• Analyst setup is neutral. Require stronger Smart Money or technical confirmation."

    if "sell" in consensus:
        return "• Analyst setup is bearish. Treat as a risk flag unless other signals strongly offset it."

    if total > 0:
        if bullish >= max(hold + bearish, 1) * 2:
            return "• Analyst vote mix is strongly bullish. Confirm with Smart Money score, risk, and filings."

        if bullish > hold + bearish:
            return "• Analyst vote mix leans bullish. Useful support, but not a standalone buy signal."

        if hold >= bullish and hold >= bearish:
            return "• Analyst vote mix is mostly neutral. Wait for stronger confirmation."

        if bearish > bullish:
            return "• Analyst vote mix leans bearish. Treat as a risk flag."

    return "• Analyst setup is mixed or unavailable. Use /analyst, /scorecard, /risk, and /filing for confirmation."


def build_stockanalysis_rating_section(data: dict, symbol: str) -> str:
    metrics = data.get("metrics", {}) if isinstance(data, dict) else {}

    if not isinstance(metrics, dict):
        metrics = {}

    consensus = metrics.get("analyst_consensus", "")
    price_target = metrics.get("price_target", "")
    upside = metrics.get("price_target_upside", "")

    strong_buy = metrics.get("strong_buy_count", "")
    buy = metrics.get("buy_count", "")
    hold = metrics.get("hold_count", "")
    sell = metrics.get("sell_count", "")
    strong_sell = metrics.get("strong_sell_count", "")
    total = metrics.get("analyst_total", "")

    return f"""
StockAnalysis Rating: {symbol}
Source: {data.get("source", "StockAnalysis.com") if isinstance(data, dict) else "StockAnalysis.com"}
Fetched: {data.get("fetched_at", "unknown") if isinstance(data, dict) else "unknown"}

External Analyst Consensus
• Consensus: {consensus or "Unavailable"}
• Price Target: {price_target or "Unavailable"}
• Implied Upside/Downside: {upside or "Unavailable"}

Buy / Hold / Sell Mix
• Strong Buy: {strong_buy or "N/A"}
• Buy: {buy or "N/A"}
• Hold: {hold or "N/A"}
• Sell: {sell or "N/A"}
• Strong Sell: {strong_sell or "N/A"}
• Total Analysts: {total or "N/A"}

Interpretation
{build_stockanalysis_rating_interpretation(metrics)}
""".strip()


def build_stockanalysis_snapshot_section(data: dict, symbol: str) -> str:
    metrics = data.get("metrics", {}) if isinstance(data, dict) else {}

    if not isinstance(metrics, dict):
        metrics = {}

    if not data.get("available"):
        errors = data.get("errors") or ["No usable StockAnalysis data returned."]
        return (
            f"StockAnalysis Snapshot: {symbol}\n"
            "Status: unavailable\n\n"
            + "\n".join(f"• {error}" for error in errors[:5])
        )

    lines = [
        f"StockAnalysis Snapshot: {symbol}",
        f"Source: {data.get('source', 'StockAnalysis.com')}",
        f"Fetched: {data.get('fetched_at', 'unknown')}",
        "",
        "Valuation / Market",
        metric_line(metrics, "market_cap", "Market Cap"),
        metric_line(metrics, "pe_ratio", "P/E"),
        metric_line(metrics, "forward_pe", "Forward P/E"),
        metric_line(metrics, "price_to_sales", "Price/Sales"),
        metric_line(metrics, "price_to_book", "Price/Book"),
        "",
        "Income Quality",
        metric_line(metrics, "revenue", "Revenue"),
        metric_line(metrics, "gross_profit", "Gross Profit"),
        metric_line(metrics, "operating_income", "Operating Income"),
        metric_line(metrics, "net_income", "Net Income"),
        metric_line(metrics, "eps", "EPS"),
        "",
        "Cash Flow / Balance Sheet",
        metric_line(metrics, "operating_cash_flow", "Operating Cash Flow"),
        metric_line(metrics, "free_cash_flow", "Free Cash Flow"),
        metric_line(metrics, "capital_expenditures", "Capital Expenditures"),
        metric_line(metrics, "cash_and_equivalents", "Cash & Equivalents"),
        metric_line(metrics, "total_debt", "Total Debt"),
        metric_line(metrics, "total_assets", "Total Assets"),
        metric_line(metrics, "total_liabilities", "Total Liabilities"),
    ]

    clean_lines = [
        line
        for line in lines
        if line is not None and str(line).strip() != ""
    ]

    return "\n".join(clean_lines).strip()


def build_page_status_lines(data: dict) -> str:
    pages = data.get("pages", {})
    page_lines = []

    for page_name, page in pages.items():
        if not isinstance(page, dict):
            continue

        status = page.get("status", "unknown")
        cache_hit = "cache" if page.get("cache_hit") else "live"
        tables = page.get("table_count", 0)

        page_lines.append(
            f"• {page_name}: {status} | {cache_hit} | tables: {tables}"
        )

    if not page_lines:
        return "• No page data available."

    return "\n".join(page_lines)


def build_source_notes(data: dict) -> str:
    errors = data.get("errors", [])

    if not errors:
        return "• StockAnalysis data loaded successfully."

    return "\n".join(f"• {error}" for error in errors[:6])


def build_stockanalysis_data_report(symbol: str, force_refresh: bool = False) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return "Usage: /stockdata SYMBOL"

    data = fetch_stockanalysis_data(symbol, force_refresh=force_refresh)

    rating = build_stockanalysis_rating_section(data, symbol)
    snapshot = build_stockanalysis_snapshot_section(data, symbol)

    page_status = build_page_status_lines(data)
    source_notes = build_source_notes(data)

    return f"""
📊 StockAnalysis Data: {symbol}

{rating}

{snapshot}

Pages Checked
{page_status}

Source Notes
{source_notes}

Use:
/stock {symbol}
/analyst {symbol}
/scorecard {symbol}
/risk {symbol}
/filing {symbol}

Research only. Not financial advice.
""".strip()