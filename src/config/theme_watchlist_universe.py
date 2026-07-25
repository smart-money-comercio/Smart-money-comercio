CORE_PORTFOLIO_TICKERS = [
    "NVDA",
    "AMD",
    "AVGO",
    "TSM",
    "ASML",
    "MSFT",
    "GOOG",
    "AMZN",
    "META",
    "PLTR",
]

THEME_TICKERS = {
    "AI / Chips": [
        "NVDA",
        "AMD",
        "AVGO",
        "TSM",
        "ASML",
        "INTC",
        "MU",
        "MRVL",
        "SMCI",
        "ARM",
    ],
    "AI Infrastructure / Power": [
        "VRT",
        "ETN",
        "GEV",
        "CEG",
        "NEE",
        "SO",
        "PWR",
        "EME",
        "GNRC",
        "APLD",
    ],
    "Defense / AI Warfare": [
        "LMT",
        "RTX",
        "NOC",
        "GD",
        "LHX",
        "HII",
        "KTOS",
        "AVAV",
        "PLTR",
        "LDOS",
    ],
    "Defense Procurement / Munitions": [
        "LMT",
        "RTX",
        "NOC",
        "GD",
        "LHX",
        "KTOS",
        "AVAV",
        "LDOS",
        "KOG.OL",
        "HII",
    ],
    "Oil / Geopolitical Risk": [
        "XOM",
        "CVX",
        "COP",
        "SLB",
        "HAL",
        "OXY",
        "EOG",
        "LNG",
        "USO",
        "XLE",
    ],
    "Inflation / Fed": [
        "TLT",
        "IEF",
        "UUP",
        "GLD",
        "JPM",
        "BAC",
        "GS",
        "MS",
        "SCHW",
        "BX",
    ],
    "Banks / Credit": [
        "JPM",
        "BAC",
        "WFC",
        "C",
        "GS",
        "MS",
        "AXP",
        "COF",
        "ALLY",
        "SCHW",
    ],
    "Consumer Stress": [
        "WMT",
        "COST",
        "TGT",
        "HD",
        "LOW",
        "MCD",
        "SBUX",
        "AXP",
        "V",
        "MA",
    ],
    "Automation / Mobility": [
        "TSLA",
        "UBER",
        "GOOG",
        "GM",
        "F",
        "RIVN",
        "MBLY",
        "AUR",
        "LAZR",
        "SYM",
    ],
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("$", "")


def extract_theme_names(context: dict | None) -> list[str]:
    if not isinstance(context, dict):
        return []

    themes = context.get("headline_themes") or []
    clean = []

    for theme in themes:
        text = str(theme or "").strip()

        if text and text not in clean:
            clean.append(text)

    return clean


def build_relevant_watchlist(
    current_symbols: list[str] | None = None,
    context: dict | None = None,
    max_symbols: int = 20,
) -> list[str]:
    """
    Builds a portfolio-relevant research universe.

    It preserves the user's manual watchlist first, then fills remaining slots
    with theme-relevant names. This does not mean buy; it means monitor.
    """
    result = []

    for symbol in current_symbols or []:
        clean_symbol = normalize_symbol(symbol)

        if clean_symbol and clean_symbol not in result:
            result.append(clean_symbol)

    active_themes = extract_theme_names(context)

    for theme in active_themes:
        for symbol in THEME_TICKERS.get(theme, []):
            clean_symbol = normalize_symbol(symbol)

            if clean_symbol and clean_symbol not in result:
                result.append(clean_symbol)

            if len(result) >= max_symbols:
                return result[:max_symbols]

    for symbol in CORE_PORTFOLIO_TICKERS:
        clean_symbol = normalize_symbol(symbol)

        if clean_symbol and clean_symbol not in result:
            result.append(clean_symbol)

        if len(result) >= max_symbols:
            return result[:max_symbols]

    return result[:max_symbols]