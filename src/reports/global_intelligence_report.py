from typing import Any

from src.intelligence.global_evolution import (
    build_global_evolution_notes,
    build_global_memory_summary,
    build_global_record,
    record_global_read,
    safe_float,
)
from src.intelligence.global_live_sources import (
    build_live_context_summary,
    fetch_global_live_context,
    format_source_snapshot,
    format_theme_snapshot,
)


try:
    from src.commands.watchlist_commands import fetch_quotes_for_symbols
except Exception:
    fetch_quotes_for_symbols = None


MACRO_SYMBOLS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
    "TLT": "Long Bonds / TLT",
    "USO": "Oil / USO",
    "GLD": "Gold / GLD",
    "UUP": "Dollar / UUP",
    "EEM": "Emerging Markets / EEM",
    "FXI": "China / FXI",
}


def safe_label(value: Any, fallback: str = "Unavailable") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def get_quote_data(symbols: list[str]) -> dict:
    if fetch_quotes_for_symbols is None:
        return {}

    try:
        quotes = fetch_quotes_for_symbols(symbols)

        if isinstance(quotes, dict):
            return quotes

    except Exception:
        return {}

    return {}


def get_quote_value(quote: dict | None, *keys, default=None):
    if not isinstance(quote, dict):
        return default

    for key in keys:
        if key in quote and quote.get(key) is not None:
            return quote.get(key)

    return default


def get_change_percent(quote: dict | None) -> float | None:
    return safe_float(
        get_quote_value(
            quote,
            "change_percent",
            "percent_change",
            "regularMarketChangePercent",
            "regular_market_change_percent",
            "changePercent",
        )
    )


def get_price(quote: dict | None) -> float | None:
    return safe_float(
        get_quote_value(
            quote,
            "price",
            "current_price",
            "regularMarketPrice",
            "regular_market_price",
            "last",
            "close",
        )
    )


def format_percent(value: float | None) -> str:
    if value is None:
        return "Unavailable"

    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def format_price(value: float | None) -> str:
    if value is None:
        return "Unavailable"

    return f"{value:,.2f}"


def bullet_lines(items: list[str]) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]

    if not cleaned:
        return "• No clear macro detail available."

    return "\n".join(f"• {item}" for item in cleaned)


def build_market_snapshot(quotes: dict) -> str:
    lines = []

    for symbol, label in MACRO_SYMBOLS.items():
        quote = quotes.get(symbol) or quotes.get(symbol.upper()) or {}
        price = get_price(quote)
        change = get_change_percent(quote)

        lines.append(f"• {label}: {format_price(price)} ({format_percent(change)})")

    return "\n".join(lines)


def get_move(quotes: dict, symbol: str) -> float | None:
    quote = quotes.get(symbol) or quotes.get(symbol.upper()) or {}
    return get_change_percent(quote)


def pressure_notes(quotes: dict, live_context: dict) -> list[str]:
    notes = []

    sp500 = get_move(quotes, "^GSPC")
    nasdaq = get_move(quotes, "^IXIC")
    russell = get_move(quotes, "^RUT")
    vix = get_move(quotes, "^VIX")
    tlt = get_move(quotes, "TLT")
    oil = get_move(quotes, "USO")
    dollar = get_move(quotes, "UUP")
    china = get_move(quotes, "FXI")
    eem = get_move(quotes, "EEM")

    if sp500 is not None and sp500 <= -0.75:
        notes.append("Broad-market pressure: S&P weakness is risk-off input.")

    if nasdaq is not None and nasdaq <= -0.9:
        notes.append("Growth pressure: Nasdaq weakness can weigh on AI, software, and semis.")

    if russell is not None and russell <= -1:
        notes.append("Breadth pressure: Russell weakness suggests small-cap risk appetite is poor.")

    if vix is not None and vix >= 3:
        notes.append("Volatility pressure: VIX is rising enough to tighten sizing discipline.")

    if tlt is not None and tlt <= -0.75:
        notes.append("Rate pressure: long-duration bonds are weak, which can pressure growth valuations.")

    if oil is not None and oil >= 1:
        notes.append("Oil pressure: energy strength can revive inflation and margin concerns.")

    if dollar is not None and dollar >= 0.5:
        notes.append("Dollar pressure: stronger dollar can pressure multinationals and emerging markets.")

    if china is not None and china <= -1:
        notes.append("China pressure: China proxy weakness adds global risk input.")

    if eem is not None and eem <= -1:
        notes.append("Emerging-market pressure: EEM weakness signals global risk-off behavior.")

    themes = " ".join(
        str(item.get("theme") or "")
        for item in live_context.get("themes", []) or []
    ).lower()

    if "geopolitical" in themes:
        notes.append("Official-source geopolitical pressure is active.")

    if "fed" in themes or "rates" in themes:
        notes.append("Official-source Fed/rates pressure is active.")

    if "inflation" in themes or "energy" in themes:
        notes.append("Official-source inflation/energy pressure is active.")

    if not notes:
        notes.append("No major macro pressure detected from available market and official-source inputs.")

    return notes[:8]


def build_risk_regime(quotes: dict, live_context: dict) -> str:
    notes = pressure_notes(quotes, live_context)
    pressure_count = len([note for note in notes if "No major" not in note])

    sp500 = get_move(quotes, "^GSPC")
    nasdaq = get_move(quotes, "^IXIC")
    vix = get_move(quotes, "^VIX")

    if pressure_count >= 5 or (vix is not None and vix >= 5):
        return "Risk-off / defensive"

    if pressure_count >= 3:
        return "Cautious / validation-first"

    if sp500 is not None and nasdaq is not None and sp500 > 0.5 and nasdaq > 0.5:
        return "Risk-on / constructive"

    return "Mixed / selective"


def build_macro_regime(quotes: dict, live_context: dict) -> str:
    risk_regime = build_risk_regime(quotes, live_context)
    themes = live_context.get("themes", []) or []
    top_theme = str(themes[0].get("theme") if themes else "")

    if top_theme:
        return f"{risk_regime} with {top_theme} pressure"

    return risk_regime


def build_portfolio_impact(risk_regime: str, notes: list[str]) -> str:
    lowered = " ".join(notes).lower()

    if risk_regime == "Risk-off / defensive":
        return "Reduce chase behavior, require confirmation, and prioritize risk control."

    if "rate pressure" in lowered or "growth pressure" in lowered:
        return "Be selective with growth and AI names; require volume and catalyst confirmation."

    if "oil pressure" in lowered or "geopolitical" in lowered:
        return "Watch defense, energy, and inflation-sensitive exposure; avoid broad-market complacency."

    if risk_regime == "Risk-on / constructive":
        return "Selective offense is acceptable, but only in names with strong score and confirmation."

    return "Stay balanced and selective; let single-stock confirmation drive sizing."


def top_theme(live_context: dict) -> str:
    themes = live_context.get("themes", []) or []

    if not themes:
        return "Mixed / developing"

    return str(themes[0].get("theme") or "Mixed / developing")


def build_what_matters(notes: list[str], risk_regime: str, top_theme_name: str) -> list[str]:
    items = [
        f"Risk regime: {risk_regime}.",
        f"Dominant official-source theme: {top_theme_name}.",
    ]

    items.extend(notes[:5])

    return items[:7]


def build_confirming_signals(risk_regime: str) -> list[str]:
    if risk_regime == "Risk-off / defensive":
        return [
            "VIX cools while indexes stabilize.",
            "TLT/rates stop pressuring growth valuations.",
            "Oil/dollar pressure eases.",
            "Breadth improves across Russell and growth proxies.",
            "Top-ranked stocks confirm with volume instead of fading.",
        ]

    if risk_regime == "Risk-on / constructive":
        return [
            "S&P and Nasdaq strength broadens beyond a few leaders.",
            "VIX remains contained.",
            "TLT/rates do not undercut growth.",
            "Dollar and oil do not create new inflation pressure.",
            "Top-ranked names confirm with volume and catalysts.",
        ]

    return [
        "Macro pressure count falls.",
        "Rates, oil, dollar, and VIX stop moving against risk assets.",
        "Official-source themes become less risk-heavy.",
        "Watchlist leaders confirm with volume.",
        "Portfolio risk names stabilize.",
    ]


def build_breaking_signals() -> list[str]:
    return [
        "VIX accelerates while indexes weaken.",
        "Oil and dollar rise together, increasing inflation and global liquidity pressure.",
        "TLT weakens sharply, raising rate pressure on growth.",
        "Official-source headlines shift toward geopolitical escalation, tariffs, sanctions, or credit stress.",
        "Top-ranked names fail despite strong individual scores.",
    ]


def build_global_action(risk_regime: str, portfolio_impact: str) -> str:
    if risk_regime == "Risk-off / defensive":
        return "Use /portfolio first, then validate only the cleanest names. Avoid chasing and reduce exposure to weak confirmation."

    if risk_regime == "Cautious / validation-first":
        return "Require /volume, /risk, /earnings, /analyst, and /filing confirmation before sizing."

    if risk_regime == "Risk-on / constructive":
        return "Selective offense is allowed. Start with /top10, then validate entries with /volume and /risk."

    return "Stay selective. Use macro as the filter and single-stock intelligence as the trigger."


def build_next_commands() -> str:
    return """
• /portfolio
• /snapshot
• /top10
• /defense
• /brief
""".strip()


def build_global_intelligence_report(force_refresh: bool = False) -> str:
    symbols = list(MACRO_SYMBOLS.keys())
    quotes = get_quote_data(symbols)
    live_context = fetch_global_live_context(force_refresh=force_refresh)

    notes = pressure_notes(quotes, live_context)
    risk_regime = build_risk_regime(quotes, live_context)
    macro_regime = build_macro_regime(quotes, live_context)
    top_theme_name = top_theme(live_context)
    portfolio_impact = build_portfolio_impact(risk_regime, notes)

    record = build_global_record(
        macro_regime=macro_regime,
        risk_regime=risk_regime,
        portfolio_impact=portfolio_impact,
        top_theme=top_theme_name,
        pressure_count=len([note for note in notes if "No major" not in note]),
        source_item_count=int(live_context.get("item_count", 0) or 0),
        source_error_count=len(live_context.get("source_errors", []) or []),
        sp500_move=get_move(quotes, "^GSPC"),
        nasdaq_move=get_move(quotes, "^IXIC"),
        vix_move=get_move(quotes, "^VIX"),
        oil_move=get_move(quotes, "USO"),
        dollar_move=get_move(quotes, "UUP"),
        tlt_move=get_move(quotes, "TLT"),
    )

    evolution = record_global_read(record)

    evolution_notes = build_global_evolution_notes(
        evolution.get("previous"),
        evolution.get("current"),
    )

    return f"""
🌍 Global Macro Intelligence

Headline
Macro Regime: {macro_regime}
Risk Regime: {risk_regime}
Portfolio Impact: {portfolio_impact}
Top Official-Source Theme: {top_theme_name}

Market Tape
{build_market_snapshot(quotes)}

Official-Source Themes
{format_theme_snapshot(live_context)}

Official-Source Data Points
{format_source_snapshot(live_context)}

Macro Pressure
{bullet_lines(notes)}

Portfolio Read
{bullet_lines(build_what_matters(notes, risk_regime, top_theme_name))}

Why This Matters
{build_live_context_summary(live_context)}

What Changed
{bullet_lines(evolution_notes)}

Evolving Analysis
{build_global_memory_summary()}

What Would Confirm The Macro Read
{bullet_lines(build_confirming_signals(risk_regime))}

What Would Break The Macro Read
{bullet_lines(build_breaking_signals())}

Global Action
{build_global_action(risk_regime, portfolio_impact)}

Next Commands
{build_next_commands()}

Research only. Not financial advice.
""".strip()