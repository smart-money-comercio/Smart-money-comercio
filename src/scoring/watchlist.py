WATCHLIST = [
    # Growth / AI
    {"ticker": "NVDA", "category": "Growth / AI Infrastructure", "smart_score": 93, "defense_score": 68},
    {"ticker": "MSFT", "category": "Growth / AI / Cloud / Government", "smart_score": 89, "defense_score": 84},
    {"ticker": "AVGO", "category": "Growth / AI Semiconductors / Networking", "smart_score": 88, "defense_score": 76},
    {"ticker": "META", "category": "Growth / AI Advertising", "smart_score": 86, "defense_score": 68},
    {"ticker": "AMZN", "category": "Growth / Cloud / AI", "smart_score": 85, "defense_score": 70},
    {"ticker": "GOOGL", "category": "Growth / AI / Cloud", "smart_score": 84, "defense_score": 74},
    {"ticker": "AMD", "category": "Growth / AI Semiconductors", "smart_score": 83, "defense_score": 60},
    {"ticker": "AAPL", "category": "Growth / Consumer AI / Hardware", "smart_score": 82, "defense_score": 78},
    {"ticker": "TSLA", "category": "High Risk Growth / Autonomous Systems", "smart_score": 76, "defense_score": 42},
    {"ticker": "SHOP", "category": "High Risk Growth / E-Commerce Infrastructure", "smart_score": 75, "defense_score": 46},
    {"ticker": "NFLX", "category": "Growth / Streaming / Media", "smart_score": 75, "defense_score": 56},

    # Defense / AI Warfare
    {"ticker": "PLTR", "category": "Defense AI / Government Software", "smart_score": 89, "defense_score": 76},
    {"ticker": "LMT", "category": "Defense Prime", "smart_score": 78, "defense_score": 88},
    {"ticker": "NOC", "category": "Space / Defense Prime", "smart_score": 77, "defense_score": 88},
    {"ticker": "RTX", "category": "Missile Defense / Aerospace", "smart_score": 78, "defense_score": 86},
    {"ticker": "GD", "category": "Defense Prime / Military Systems", "smart_score": 76, "defense_score": 84},
    {"ticker": "HII", "category": "Naval Defense / Shipbuilding", "smart_score": 72, "defense_score": 82},
    {"ticker": "AVAV", "category": "Defense / Drones / Counter-Drone", "smart_score": 82, "defense_score": 66},
    {"ticker": "KTOS", "category": "Defense / Autonomous Aircraft", "smart_score": 78, "defense_score": 62},
    {"ticker": "RKLB", "category": "High Risk Growth / Space / Defense Launch", "smart_score": 74, "defense_score": 50},
    {"ticker": "ONDS", "category": "High Risk Growth / Autonomous Drones / Counter-UAS", "smart_score": 66, "defense_score": 42},

    # Cybersecurity
    {"ticker": "CRWD", "category": "Growth / Cyber Warfare", "smart_score": 84, "defense_score": 66},
    {"ticker": "PANW", "category": "Cybersecurity / Government Security", "smart_score": 83, "defense_score": 74},
    {"ticker": "FTNT", "category": "Cybersecurity Infrastructure", "smart_score": 79, "defense_score": 72},
    {"ticker": "ZS", "category": "Growth / Zero Trust Cybersecurity", "smart_score": 76, "defense_score": 58},

    # ETFs
    {"ticker": "QQQ", "category": "Growth ETF", "smart_score": 83, "defense_score": 72},
    {"ticker": "VOO", "category": "Core Market ETF", "smart_score": 82, "defense_score": 86},
    {"ticker": "ITA", "category": "Aerospace & Defense ETF", "smart_score": 79, "defense_score": 86},
    {"ticker": "CIBR", "category": "Cybersecurity ETF", "smart_score": 77, "defense_score": 76},
    {"ticker": "SCHD", "category": "Dividend ETF", "smart_score": 78, "defense_score": 84},
    {"ticker": "VYM", "category": "High Dividend ETF", "smart_score": 76, "defense_score": 82},

    # Dividend / High Income
    {"ticker": "JNJ", "category": "Dividend / Healthcare", "smart_score": 72, "defense_score": 82},
    {"ticker": "PG", "category": "Dividend / Consumer Defensive", "smart_score": 74, "defense_score": 86},
    {"ticker": "KO", "category": "Dividend / Consumer Defensive", "smart_score": 72, "defense_score": 84},
    {"ticker": "PEP", "category": "Dividend / Consumer Defensive", "smart_score": 73, "defense_score": 84},
    {"ticker": "ABBV", "category": "Dividend / Healthcare", "smart_score": 74, "defense_score": 78},
    {"ticker": "O", "category": "High Dividend / REIT", "smart_score": 72, "defense_score": 68},
    {"ticker": "VZ", "category": "High Dividend / Telecom", "smart_score": 70, "defense_score": 64},
    {"ticker": "T", "category": "High Dividend / Telecom", "smart_score": 69, "defense_score": 62},
    {"ticker": "MO", "category": "High Dividend / Consumer Defensive", "smart_score": 68, "defense_score": 58},
    {"ticker": "XOM", "category": "Dividend / Energy", "smart_score": 77, "defense_score": 72},
    {"ticker": "CVX", "category": "Dividend / Energy", "smart_score": 76, "defense_score": 74},

]

SMART_MONEY_EXPANSION = [
    # AI / Semiconductors / Compute Infrastructure
    {
        "ticker": "INTC",
        "category": "Semiconductor / AI Infrastructure / Turnaround",
        "smart_score": 72,
        "defense_score": 63,
    },
    {
        "ticker": "MU",
        "category": "Semiconductor / Memory / AI Infrastructure",
        "smart_score": 78,
        "defense_score": 61,
    },
    {
        "ticker": "TSM",
        "category": "Semiconductor / Foundry / AI Infrastructure",
        "smart_score": 84,
        "defense_score": 72,
    },
    {
        "ticker": "ASML",
        "category": "Semiconductor Equipment / AI Supply Chain",
        "smart_score": 84,
        "defense_score": 74,
    },
    {
        "ticker": "ARM",
        "category": "Semiconductor / AI Compute / Growth",
        "smart_score": 78,
        "defense_score": 58,
    },
    {
        "ticker": "SMCI",
        "category": "AI Servers / Data Center Infrastructure / High Risk",
        "smart_score": 72,
        "defense_score": 46,
    },
    {
        "ticker": "ANET",
        "category": "AI Networking / Data Center Infrastructure",
        "smart_score": 83,
        "defense_score": 70,
    },
    {
        "ticker": "DELL",
        "category": "AI Servers / Enterprise Hardware / Infrastructure",
        "smart_score": 76,
        "defense_score": 62,
    },

    # Cybersecurity / Software Infrastructure
    {
        "ticker": "NET",
        "category": "Cybersecurity / Edge Cloud / Growth",
        "smart_score": 76,
        "defense_score": 56,
    },
    {
        "ticker": "DDOG",
        "category": "Cloud Monitoring / AI Software Infrastructure",
        "smart_score": 77,
        "defense_score": 57,
    },
    {
        "ticker": "OKTA",
        "category": "Cybersecurity / Identity / Turnaround",
        "smart_score": 68,
        "defense_score": 55,
    },
    {
        "ticker": "S",
        "category": "Cybersecurity / Endpoint / High Risk Growth",
        "smart_score": 70,
        "defense_score": 48,
    },
    {
        "ticker": "MDB",
        "category": "Database / AI Software Infrastructure / Growth",
        "smart_score": 73,
        "defense_score": 54,
    },

    # Defense / Security / Government Tech
    {
        "ticker": "LHX",
        "category": "Defense / Communications / National Security",
        "smart_score": 76,
        "defense_score": 78,
    },
    {
        "ticker": "LDOS",
        "category": "Defense IT / Government Services / National Security",
        "smart_score": 74,
        "defense_score": 76,
    },
    {
        "ticker": "CACI",
        "category": "Defense IT / Intelligence / Cyber Warfare",
        "smart_score": 75,
        "defense_score": 77,
    },
    {
        "ticker": "AXON",
        "category": "Public Safety / Defense Tech / AI Hardware",
        "smart_score": 79,
        "defense_score": 65,
    },
    {
        "ticker": "TXT",
        "category": "Defense / Aviation / Drones",
        "smart_score": 70,
        "defense_score": 70,
    },
    {
        "ticker": "TDG",
        "category": "Aerospace / Defense Supplier / Quality Compounder",
        "smart_score": 82,
        "defense_score": 73,
    },

    # Power / Grid / Data Center Energy
    {
        "ticker": "VST",
        "category": "Power / Data Center Energy / AI Infrastructure",
        "smart_score": 81,
        "defense_score": 64,
    },
    {
        "ticker": "CEG",
        "category": "Nuclear Power / Data Center Energy / Infrastructure",
        "smart_score": 82,
        "defense_score": 69,
    },
    {
        "ticker": "GEV",
        "category": "Grid Infrastructure / Energy / AI Power Demand",
        "smart_score": 77,
        "defense_score": 66,
    },
    {
        "ticker": "ETN",
        "category": "Electrical Infrastructure / Data Center Power / Quality",
        "smart_score": 83,
        "defense_score": 75,
    },
    {
        "ticker": "PWR",
        "category": "Grid Infrastructure / Energy Services / AI Power Demand",
        "smart_score": 78,
        "defense_score": 68,
    },
    {
        "ticker": "NEE",
        "category": "Utility / Renewable Power / Defensive Infrastructure",
        "smart_score": 68,
        "defense_score": 76,
    },

    # Quality Compounders / Blue-Chip Watchlist
    {
        "ticker": "COST",
        "category": "Quality Compounder / Consumer Defensive",
        "smart_score": 84,
        "defense_score": 80,
    },
    {
        "ticker": "WMT",
        "category": "Quality Compounder / Consumer Defensive",
        "smart_score": 79,
        "defense_score": 81,
    },
    {
        "ticker": "HD",
        "category": "Quality Compounder / Housing / Consumer",
        "smart_score": 75,
        "defense_score": 72,
    },
    {
        "ticker": "MCD",
        "category": "Dividend / Quality Compounder / Consumer Defensive",
        "smart_score": 74,
        "defense_score": 79,
    },
    {
        "ticker": "JPM",
        "category": "Financials / Quality Compounder / Dividend",
        "smart_score": 78,
        "defense_score": 75,
    },
    {
        "ticker": "BLK",
        "category": "Financial Infrastructure / Asset Management / Quality",
        "smart_score": 76,
        "defense_score": 70,
    },
    {
        "ticker": "CAT",
        "category": "Industrial / Infrastructure / Dividend",
        "smart_score": 76,
        "defense_score": 72,
    },
    {
        "ticker": "UNH",
        "category": "Healthcare / Managed Care / Quality Watch",
        "smart_score": 70,
        "defense_score": 68,
    },

    # ETF / Theme Tracking
    {
        "ticker": "SMH",
        "category": "ETF / Semiconductor / AI Infrastructure",
        "smart_score": 82,
        "defense_score": 70,
    },
    {
        "ticker": "SOXX",
        "category": "ETF / Semiconductor / AI Infrastructure",
        "smart_score": 80,
        "defense_score": 70,
    },
    {
        "ticker": "XLK",
        "category": "ETF / Technology / Core Growth",
        "smart_score": 79,
        "defense_score": 73,
    },
    {
        "ticker": "XLU",
        "category": "ETF / Utilities / Defensive Income",
        "smart_score": 65,
        "defense_score": 82,
    },
]


def dedupe_watchlist_by_ticker(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []

    for item in items:
        ticker = str(item.get("ticker", "")).strip().upper().replace("$", "")

        if not ticker or ticker in seen:
            continue

        clean_item = dict(item)
        clean_item["ticker"] = ticker

        seen.add(ticker)
        deduped.append(clean_item)

    return deduped


WATCHLIST = dedupe_watchlist_by_ticker(WATCHLIST + SMART_MONEY_EXPANSION)