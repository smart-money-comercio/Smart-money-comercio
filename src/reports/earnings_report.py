from typing import Any

from src.market.market_data import format_number, format_percent


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace("$", "")


def format_plain(value: Any) -> str:
    if value is None:
        return "N/A"

    return str(value)


def classify_growth(value: Any) -> str:
    growth = safe_float(value)

    if growth is None:
        return "Growth data unavailable"

    if growth >= 0.25:
        return "Very strong revenue growth"
    if growth >= 0.10:
        return "Strong revenue growth"
    if growth > 0:
        return "Positive revenue growth"
    if growth == 0:
        return "Flat revenue growth"

    return "Revenue contraction"


def classify_margin(value: Any, margin_type: str) -> str:
    margin = safe_float(value)

    if margin is None:
        return f"{margin_type} margin unavailable"

    if margin >= 0.30:
        return f"Very strong {margin_type.lower()} margin"
    if margin >= 0.20:
        return f"Strong {margin_type.lower()} margin"
    if margin >= 0.10:
        return f"Moderate {margin_type.lower()} margin"
    if margin > 0:
        return f"Thin {margin_type.lower()} margin"

    return f"Negative {margin_type.lower()} margin"


def classify_valuation(pe_ratio: Any, forward_pe: Any) -> str:
    pe = safe_float(pe_ratio)
    fpe = safe_float(forward_pe)
    valuation = fpe if fpe is not None else pe

    if valuation is None:
        return "Valuation data unavailable"

    if valuation >= 80:
        return "Very expensive earnings multiple"
    if valuation >= 50:
        return "Expensive earnings multiple"
    if valuation >= 30:
        return "Elevated earnings multiple"
    if valuation >= 15:
        return "Moderate earnings multiple"
    if valuation > 0:
        return "Lower earnings multiple"

    return "Earnings multiple may not be meaningful"


def build_watch_items(data: dict) -> list[str]:
    items = []

    revenue_growth = safe_float(data.get("revenue_growth"))
    gross_margin = safe_float(data.get("gross_margin"))
    operating_margin = safe_float(data.get("operating_margin"))
    net_margin = safe_float(data.get("net_margin"))
    pe_ratio = safe_float(data.get("pe_ratio"))
    forward_pe = safe_float(data.get("forward_pe"))

    if revenue_growth is None:
        items.append("Confirm whether revenue is growing or slowing.")
    elif revenue_growth < 0:
        items.append("Watch for continued revenue contraction.")
    elif revenue_growth < 0.10:
        items.append("Watch whether revenue growth can accelerate.")
    else:
        items.append("Watch whether strong revenue growth is sustainable.")

    if operating_margin is None:
        items.append("Verify operating margin trend.")
    elif operating_margin < 0:
        items.append("Watch for operating losses and cash burn.")
    elif operating_margin < 0.10:
        items.append("Watch whether operating margin can expand.")
    else:
        items.append("Watch whether operating margin remains strong.")

    if net_margin is None:
        items.append("Check net income quality and one-time items.")
    elif net_margin < 0:
        items.append("Watch for net losses and balance sheet pressure.")
    else:
        items.append("Check whether net income growth matches revenue growth.")

    valuation = forward_pe if forward_pe is not None else pe_ratio

    if valuation is None:
        items.append("Compare valuation against sector peers.")
    elif valuation >= 50:
        items.append("High valuation requires strong future growth confirmation.")
    elif valuation <= 15 and valuation > 0:
        items.append("Lower valuation may signal value or weaker growth expectations.")
    else:
        items.append("Compare valuation with growth and margin quality.")

    if gross_margin is not None and gross_margin < 0.20:
        items.append("Gross margin is thin; watch pricing power and cost pressure.")

    cleaned = []

    for item in items:
        if item not in cleaned:
            cleaned.append(item)

    return cleaned[:5]


def format_bullets(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items)


def build_earnings_report(symbol: str, data: dict, ai_summary: str | None = None) -> str:
    clean = clean_symbol(symbol)

    ticker = data.get("ticker") or clean
    company_name = data.get("company_name") or "N/A"
    period_type = data.get("period_type") or "N/A"
    latest_period = data.get("latest_period") or "N/A"
    sector = data.get("sector") or "N/A"

    revenue = data.get("revenue")
    revenue_growth = data.get("revenue_growth")
    gross_profit = data.get("gross_profit")
    operating_income = data.get("operating_income")
    net_income = data.get("net_income")
    diluted_eps = data.get("diluted_eps")

    gross_margin = data.get("gross_margin")
    operating_margin = data.get("operating_margin")
    net_margin = data.get("net_margin")

    pe_ratio = data.get("pe_ratio")
    forward_pe = data.get("forward_pe")
    dividend_yield = data.get("dividend_yield")

    watch_items = build_watch_items(data)

    if not ai_summary:
        ai_summary = "AI summary unavailable."

    return f"""
📊 Smart Money AI Earnings Snapshot: {ticker}

Company
Company: {company_name}
Sector: {sector}

Reporting Period
Period Type: {period_type}
Latest Period: {latest_period}

Revenue
Revenue: {format_number(revenue)}
Revenue Growth: {format_percent(revenue_growth)}
Growth Readout: {classify_growth(revenue_growth)}

Profitability
Gross Profit: {format_number(gross_profit)}
Operating Income: {format_number(operating_income)}
Net Income: {format_number(net_income)}

Margins
Gross Margin: {format_percent(gross_margin)}
Gross Margin Readout: {classify_margin(gross_margin, "Gross")}
Operating Margin: {format_percent(operating_margin)}
Operating Margin Readout: {classify_margin(operating_margin, "Operating")}
Net Margin: {format_percent(net_margin)}
Net Margin Readout: {classify_margin(net_margin, "Net")}

EPS
Diluted EPS: {format_plain(diluted_eps)}

Valuation
P/E Ratio: {format_plain(pe_ratio)}
Forward P/E: {format_plain(forward_pe)}
Valuation Readout: {classify_valuation(pe_ratio, forward_pe)}

Income
Dividend Yield: {format_percent(dividend_yield)}

AI Earnings Summary
{ai_summary}

What To Watch Next
{format_bullets(watch_items)}

Next Commands
/quote {ticker}
/market {ticker}
/scorecard {ticker}
/risk {ticker}

Notes
This earnings snapshot is informational only and is not financial advice.
Verify earnings data before making investment decisions.
""".strip()