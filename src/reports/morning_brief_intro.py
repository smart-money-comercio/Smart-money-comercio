import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_FILE = PROJECT_ROOT / "data" / "morning_brief_cache.json"

TIMEZONE = "America/Lima"
REQUEST_TIMEOUT = 6
CACHE_TTL_SECONDS = 60 * 60 * 6

WEEK_AHEAD_EARNINGS = os.getenv(
    "WEEK_AHEAD_EARNINGS",
    "",
).strip()

WEEK_AHEAD_ECON_EVENTS = os.getenv(
    "WEEK_AHEAD_ECON_EVENTS",
    "",
).strip()

WEEK_AHEAD_NARRATIVES = os.getenv(
    "WEEK_AHEAD_NARRATIVES",
    "",
).strip()

ISSUE_MEMORY_FILE = PROJECT_ROOT / "data" / "morning_brief_issue_memory.json"

ISSUE_MEMORY_DAYS = int(
    os.getenv(
        "MORNING_BRIEF_MEMORY_DAYS",
        "4",
    )
)

MARKET_ASSETS = [ 
    {"symbol": "^GSPC", "label": "S&P 500"},
    {"symbol": "^IXIC", "label": "Nasdaq"},
    {"symbol": "^DJI", "label": "Dow"},
]

MARKET_ASSETS = [
    {"symbol": "^GSPC", "label": "S&P 500"},
    {"symbol": "^IXIC", "label": "Nasdaq"},
    {"symbol": "^DJI", "label": "Dow"},
    {"symbol": "^RUT", "label": "Russell 2000"},
    {"symbol": "^VIX", "label": "VIX"},
    {"symbol": "USO", "label": "Oil"},
    {"symbol": "TLT", "label": "Long Bonds"},
    {"symbol": "GLD", "label": "Gold"},
    {"symbol": "UUP", "label": "U.S. Dollar"},
]


RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://finance.yahoo.com/topic/stock-market-news/rss",
    "https://finance.yahoo.com/topic/earnings/rss",
]


THEME_KEYWORDS = {
    "AI / Chips": [
        "ai",
        "artificial intelligence",
        "chip",
        "chips",
        "semiconductor",
        "nvidia",
        "amd",
        "broadcom",
        "sk hynix",
        "tsmc",
        "asml",
        "data center",
        "hyperscaler",
        "openai",
        "apple",
    ],
    "AI Infrastructure / Power": [
        "data center",
        "data centers",
        "power demand",
        "electricity",
        "grid",
        "nuclear",
        "utility",
        "utilities",
        "cooling",
        "energy demand",
        "ai infrastructure",
    ],
    "Oil / Geopolitical Risk": [
        "oil",
        "crude",
        "brent",
        "wti",
        "hormuz",
        "strait of hormuz",
        "iran",
        "missile",
        "strike",
        "strikes",
        "attack",
        "attacks",
        "tanker",
        "tankers",
        "shipping",
        "blockade",
        "gulf",
        "middle east",
        "red sea",
        "geopolitical",
        "energy export",
        "oil supply",
        "sanctions",
    ],
    "Defense / AI Warfare": [
        "dod",
        "department of defense",
        "defense",
        "defence",
        "pentagon",
        "military",
        "missile defense",
        "air defense",
        "drone",
        "drones",
        "uav",
        "counter-drone",
        "counter drone",
        "autonomous warfare",
        "electronic warfare",
        "isr",
        "surveillance",
        "radar",
        "cyber warfare",
        "battlefield",
    ],
        "Defense Procurement / Munitions": [
        "famm",
        "family of affordable mass missiles",
        "low-cost cruise missile",
        "low cost cruise missile",
        "affordable mass missile",
        "air-launched cruise missile",
        "palletized munition",
        "palletized munitions",
        "standoff weapon",
        "standoff weapons",
        "stand-off weapon",
        "stand-off weapons",
        "munitions",
        "missile stockpile",
        "weapons stockpile",
        "strike munitions",
        "mass missiles",
        "affordable cruise missile",
        "barracuda",
        "barracuda-500",
        "rusty dagger",
        "agm-188",
        "agm-189",
        "coaspire",
        "anduril",
        "zone 5",
        "leidos",
        "kongsberg",
        "multi-year procurement",
        "framework agreements",
        "defense industrial base",
        "arsenal of freedom",
        "surge production",
        "firm-fixed-price",
    ],
    "Earnings Season": [
        "earnings",
        "results",
        "guidance",
        "revenue",
        "profit",
        "margin",
        "margins",
        "jpmorgan",
        "bank of america",
        "goldman",
        "wells fargo",
        "citigroup",
        "morgan stanley",
        "netflix",
    ],
    "Inflation / Fed": [
        "cpi",
        "ppi",
        "inflation",
        "fed",
        "federal reserve",
        "rates",
        "rate cut",
        "rate cuts",
        "yield",
        "treasury",
        "bond",
        "bonds",
        "warsh",
    ],
    "Banks / Credit": [
        "bank",
        "banks",
        "credit",
        "loan",
        "loans",
        "deposits",
        "delinquency",
        "commercial real estate",
        "capital markets",
        "trading revenue",
        "jpmorgan",
        "bank of america",
        "goldman",
        "wells fargo",
        "citigroup",
        "morgan stanley",
    ],
    "Consumer Stress": [
        "credit card",
        "groceries",
        "consumer",
        "walmart",
        "prices",
        "retail sales",
        "delinquency",
        "household",
        "spending",
    ],
    "Policy / Regulation": [
        "tariff",
        "tariffs",
        "refund",
        "eu",
        "regulation",
        "regulatory",
        "social media",
        "retirement",
        "white house",
        "trump",
        "congress",
    ],
    "Automation / Mobility": [
        "robotaxi",
        "waymo",
        "uber",
        "rivian",
        "tesla",
        "autonomous",
        "ev",
        "electric vehicle",
    ],
    "Market Breadth / Rotation": [
        "rotation",
        "breadth",
        "small cap",
        "small caps",
        "russell",
        "equal weight",
        "cyclical",
        "cyclicals",
        "laggards",
        "leadership",
    ],
}


GENERIC_THEME_LABELS = {
    "market",
    "markets",
    "stock market",
    "stocks",
    "equities",
    "market news",
    "general market",
}


THEME_LABEL_REPLACEMENTS = {
    "Oil / Geopolitical Risk": "Geopolitical / oil risk",
    "Defense / AI Warfare": "Defense / AI warfare",
    "AI / Chips": "AI / chips",
    "AI Infrastructure / Power": "AI infrastructure / power",
    "Inflation / Fed": "Inflation / Fed risk",
    "Banks / Credit": "Banks / credit",
    "Consumer Stress": "Consumer pressure",
    "Market Breadth / Rotation": "Market breadth / rotation",
    "Defense Procurement / Munitions": "Defense procurement / munitions",
}

MARKET_TIMEZONE = os.getenv("MARKET_TIMEZONE", "America/New_York")


def get_us_market_session_status() -> dict:
    now_et = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    weekday = now_et.weekday()

    if weekday >= 5:
        return {
            "state": "closed_weekend",
            "label": "Weekend brief — U.S. markets are closed.",
            "price_note": "Index and watchlist price moves reflect the last completed regular session; headlines can still update over the weekend.",
        }

    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if now_et < market_open:
        return {
            "state": "pre_market",
            "label": "Pre-market brief — U.S. markets have not opened yet.",
            "price_note": "Index and watchlist moves may still reflect the prior session until live trading begins.",
        }

    if now_et > market_close:
        return {
            "state": "after_hours",
            "label": "After-hours brief — the regular U.S. market session is closed.",
            "price_note": "Index and watchlist moves reflect the completed regular session; new headlines may still change tomorrow’s setup.",
        }

    return {
        "state": "open",
        "label": "Market session brief — U.S. markets are open.",
        "price_note": "Price moves and watchlist movement may update during the session.",
    }

def clean_text(value: Any, max_length: int = 240) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def clean_theme_label(theme: str | None) -> str:
    text = " ".join(str(theme or "").split())

    if not text:
        return ""

    if text.lower() in GENERIC_THEME_LABELS:
        return ""

    return THEME_LABEL_REPLACEMENTS.get(text, text)


def get_clean_theme_list(theme_summary: dict) -> list[str]:
    ranked = theme_summary.get("ranked_themes") or []
    themes = []

    for item in ranked:
        if isinstance(item, dict):
            raw_theme = item.get("theme")
        elif isinstance(item, (list, tuple)) and item:
            raw_theme = item[0]
        else:
            raw_theme = None

        cleaned = clean_theme_label(raw_theme)

        if cleaned and cleaned not in themes:
            themes.append(cleaned)

    return themes[:5]


def get_top_theme(theme_summary: dict) -> str:
    top_theme = clean_theme_label(theme_summary.get("top_theme"))

    if top_theme:
        return top_theme

    clean_themes = get_clean_theme_list(theme_summary)

    if clean_themes:
        return clean_themes[0]

    return "Macro / earnings setup"


def now_iso() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).isoformat()


def read_json(path: Path, default: Any):
    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)

    except Exception:
        return

def today_memory_key() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d")


def normalize_issue_memory_key(value: str) -> str:
    text = clean_text(value, 500).lower()
    normalized = []

    for character in text:
        if character.isalnum():
            normalized.append(character)
        else:
            normalized.append(" ")

    return " ".join("".join(normalized).split())


def load_issue_memory() -> dict:
    data = read_json(ISSUE_MEMORY_FILE, {"days": []})

    if not isinstance(data, dict):
        return {"days": []}

    days = data.get("days")

    if not isinstance(days, list):
        data["days"] = []

    return data


def save_issue_memory(memory: dict) -> None:
    write_json(ISSUE_MEMORY_FILE, memory)


def prune_issue_memory(memory: dict) -> dict:
    days = memory.get("days") or []

    if not isinstance(days, list):
        days = []

    cleaned_days = []

    for day in days:
        if not isinstance(day, dict):
            continue

        date = str(day.get("date", "")).strip()
        bullets = day.get("bullets") or []

        if not date or not isinstance(bullets, list):
            continue

        cleaned_days.append(
            {
                "date": date,
                "bullets": bullets[:8],
                "keys": [
                    normalize_issue_memory_key(item)
                    for item in bullets[:8]
                ],
            }
        )

    cleaned_days = cleaned_days[-ISSUE_MEMORY_DAYS:]

    return {"days": cleaned_days}


def get_recent_issue_keys(memory: dict, exclude_today: bool = True) -> set[str]:
    today = today_memory_key()
    keys = set()

    for day in memory.get("days") or []:
        if exclude_today and day.get("date") == today:
            continue

        for key in day.get("keys") or []:
            if key:
                keys.add(key)

    return keys


def reframe_repeated_issue_bullet(bullet: str, index: int) -> str:
    angles = [
        "Portfolio angle",
        "Risk check",
        "Confirmation watch",
        "Big-picture read",
        "Watchlist impact",
    ]

    angle = angles[index % len(angles)]

    if bullet.startswith(angle):
        return bullet

    return f"{angle}: {bullet}"


def apply_issue_memory_filter(bullets: list[str]) -> list[str]:
    memory = prune_issue_memory(load_issue_memory())
    recent_keys = get_recent_issue_keys(memory, exclude_today=True)

    fresh_bullets = []
    reframed_bullets = []

    for index, bullet in enumerate(bullets):
        cleaned = clean_text(bullet, 180)

        if not cleaned:
            continue

        key = normalize_issue_memory_key(cleaned)

        if key in recent_keys:
            reframed_bullets.append(
                reframe_repeated_issue_bullet(cleaned, index)
            )
        else:
            fresh_bullets.append(cleaned)

    combined = fresh_bullets + reframed_bullets

    unique = []

    for bullet in combined:
        if bullet not in unique:
            unique.append(bullet)

    return unique[:5]


def record_issue_bullets(bullets: list[str]) -> None:
    memory = prune_issue_memory(load_issue_memory())
    today = today_memory_key()

    cleaned_bullets = [
        clean_text(item, 180)
        for item in bullets
        if clean_text(item, 180)
    ][:8]

    days = [
        day
        for day in memory.get("days") or []
        if day.get("date") != today
    ]

    days.append(
        {
            "date": today,
            "bullets": cleaned_bullets,
            "keys": [
                normalize_issue_memory_key(item)
                for item in cleaned_bullets
            ],
        }
    )

    memory["days"] = days[-ISSUE_MEMORY_DAYS:]

    save_issue_memory(memory)

def request_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SmartMoneyAI/1.0",
            "Accept": "application/json, application/xml, text/xml, text/html, */*",
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="ignore")


def get_asset_move(symbol: str) -> dict:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d"

    try:
        payload = json.loads(request_text(url))
        result = payload["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]

        clean_closes = [
            float(value)
            for value in closes
            if value is not None
        ]

        if len(clean_closes) < 2:
            return {"symbol": symbol, "move": None, "week_move": None}

        week_start = clean_closes[0]
        previous = clean_closes[-2]
        latest = clean_closes[-1]

        if previous == 0:
            day_move = None
        else:
            day_move = ((latest - previous) / previous) * 100

        if week_start == 0:
            week_move = None
        else:
            week_move = ((latest - week_start) / week_start) * 100

        return {
            "symbol": symbol,
            "latest": round(latest, 2),
            "previous": round(previous, 2),
            "week_start": round(week_start, 2),
            "move": round(day_move, 2) if day_move is not None else None,
            "week_move": round(week_move, 2) if week_move is not None else None,
        }

    except Exception:
        return {"symbol": symbol, "move": None, "week_move": None}


def fetch_market_moves() -> list[dict]:
    moves = []

    for asset in MARKET_ASSETS:
        data = get_asset_move(asset["symbol"])
        data["label"] = asset["label"]
        moves.append(data)

    return moves


def fetch_rss_headlines() -> list[str]:
    headlines = []

    for feed_url in RSS_FEEDS:
        try:
            xml_text = request_text(feed_url)
            root = ET.fromstring(xml_text)

            for item in root.findall(".//item"):
                title_node = item.find("title")

                if title_node is None or not title_node.text:
                    continue

                title = clean_text(title_node.text, 180)

                if title and title not in headlines:
                    headlines.append(title)

                if len(headlines) >= 30:
                    break

        except Exception:
            continue

        if len(headlines) >= 30:
            break

    manual_defense_headline = os.getenv("MANUAL_DEFENSE_HEADLINE", "").strip()

    if manual_defense_headline:
        manual_defense_headline = clean_text(manual_defense_headline, 180)

        if manual_defense_headline and manual_defense_headline not in headlines:
            headlines.insert(0, manual_defense_headline)

    return headlines[:30]

def classify_headline(headline: str) -> list[str]:
    text = headline.lower()
    themes = []

    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            themes.append(theme)

    # Do not add generic "Market" as a fallback.
    # Generic headlines should not dominate the morning brief.
    return themes


def build_theme_summary(headlines: list[str]) -> dict:
    theme_counts = {}
    theme_headlines = {}

    for headline in headlines:
        themes = classify_headline(headline)

        for theme in themes:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
            theme_headlines.setdefault(theme, [])

            if len(theme_headlines[theme]) < 3:
                theme_headlines[theme].append(headline)

    ranked_themes = sorted(
        theme_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    top_theme = ranked_themes[0][0] if ranked_themes else "Macro / earnings setup"

    return {
        "top_theme": top_theme,
        "ranked_themes": ranked_themes[:6],
        "theme_headlines": theme_headlines,
    }


def format_market_recap(moves: list[dict]) -> str:
    by_symbol = {
        item.get("symbol"): item
        for item in moves
    }

    sp500 = by_symbol.get("^GSPC", {}).get("move")
    nasdaq = by_symbol.get("^IXIC", {}).get("move")
    dow = by_symbol.get("^DJI", {}).get("move")

    if sp500 is None or nasdaq is None or dow is None:
        return "Stocks enter the day with investors focused on earnings, inflation, rates, geopolitical risk, and the next phase of the AI trade."

    direction = "higher" if sp500 >= 0 else "lower"

    return (
        f"Stocks finished the latest session {direction}, with the "
        f"S&P 500 {'up' if sp500 >= 0 else 'down'} {abs(sp500):.1f}%, "
        f"the Nasdaq {'up' if nasdaq >= 0 else 'down'} {abs(nasdaq):.1f}%, "
        f"and the Dow {'up' if dow >= 0 else 'down'} {abs(dow):.1f}%."
    )


def build_what_watching(theme_summary: dict) -> str:
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]
    top_theme = get_top_theme(theme_summary)

    watch_items = []

    if "Oil / Geopolitical Risk" in themes:
        watch_items.append("oil prices, shipping risk, and geopolitical spillover")

    if "Defense / AI Warfare" in themes:
        watch_items.append("whether defense, cyber, drones, ISR, and AI warfare names see follow-through")

    if "Inflation / Fed" in themes:
        watch_items.append("inflation data and the bond-market reaction")

    if "Earnings Season" in themes:
        watch_items.append("bank earnings, margins, guidance, and credit quality")

    if "AI / Chips" in themes:
        watch_items.append("whether AI leadership stabilizes or continues to rotate")

    if "AI Infrastructure / Power" in themes:
        watch_items.append("AI infrastructure demand across power, data centers, and grid capacity")

    if "Consumer Stress" in themes:
        watch_items.append("consumer credit, retail demand, and household pressure")

    if not watch_items:
        watch_items.append(f"whether the {top_theme.lower()} theme changes market leadership")

    watch_text = "; ".join(watch_items[:4])

    return f"What we're watching: {watch_text}."


def build_portfolio_read(theme_summary: dict) -> str:
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]

    reads = []

    if "Oil / Geopolitical Risk" in themes:
        reads.append("treat geopolitical risk as two-sided: negative for oil/inflation/shipping risk, supportive for defense and security attention.")

    if "Defense Procurement / Munitions" in themes:
        reads.append(
            "treat munitions procurement as a real demand signal; prioritize public names with direct exposure to missiles, autonomous systems, sensors, mission software, and scalable production."
        )

    if "Defense / AI Warfare" in themes:
        reads.append("watch defense, drones, cyber, ISR, missile defense, and AI warfare names for real volume confirmation.")

    if "AI / Chips" in themes:
        reads.append("stay selective in AI and semiconductors; favor infrastructure winners over crowded momentum.")

    if "AI Infrastructure / Power" in themes:
        reads.append("AI infrastructure exposure remains important across power, grid, and data-center demand.")

    if "Earnings Season" in themes:
        reads.append("use earnings to separate companies with durable margins from weaker guidance stories.")

    if "Consumer Stress" in themes:
        reads.append("favor quality balance sheets and value-oriented consumer exposure over weaker discretionary names.")

    if not reads:
        reads.append("keep portfolio exposure balanced across growth, defense, quality, and income themes.")

    return "Portfolio read: " + " ".join(reads[:3])


def refresh_morning_brief_cache() -> dict:
    """
    Live refresh.

    Use this before the scheduled daily report or a manual refresh command.
    Do not call this inside deployment preflight.
    """
    market_moves = fetch_market_moves()
    headlines = fetch_rss_headlines()
    theme_summary = build_theme_summary(headlines)

    issue_bullets = build_today_issue_bullets(
        theme_summary,
        use_memory=True,
        record_memory=True,
    )

    payload = {
        "cached_at": time.time(),
        "cached_at_iso": now_iso(),
        "source": "Yahoo Finance RSS and market chart data",
        "market_moves": market_moves,
        "headlines": headlines[:20],
        "theme_summary": theme_summary,
    }

    write_json(CACHE_FILE, payload)

    return payload


def load_morning_brief_cache() -> dict:
    payload = read_json(CACHE_FILE, {})

    if not isinstance(payload, dict):
        return {}

    return payload


def cache_is_fresh(payload: dict) -> bool:
    cached_at = payload.get("cached_at")

    try:
        return time.time() - float(cached_at) <= CACHE_TTL_SECONDS
    except Exception:
        return False


def build_fallback_intro() -> str:
    return """
Good morning.

Markets enter the day focused on earnings, inflation, interest rates, geopolitical risk, AI leadership, and portfolio risk. The daily report is using the latest available cached morning brief. Use /headlines and /global for live market context if you want a fresh intraday read.

In today's issue:
• Market leadership and risk appetite.
• Earnings and guidance quality.
• Inflation, rates, and Fed expectations.
• AI, semiconductors, and infrastructure demand.
• Defense, cyber, drones, ISR, and geopolitical risk when headlines justify it.
• Watchlist opportunities and risk notes.

What we're watching:
Whether earnings, macro data, and geopolitical headlines support a broader rally or keep leadership concentrated in a smaller group of high-conviction names.
""".strip()

def get_market_move(market_moves: list[dict], symbol: str) -> float | None:
    for item in market_moves:
        if str(item.get("symbol", "")).upper() == symbol.upper():
            value = item.get("move")

            try:
                if value is None:
                    return None

                return float(value)
            except Exception:
                return None

    return None


def format_index_move(label: str, value: float | None) -> str:
    if value is None:
        return f"{label} was unavailable"

    direction = "gained" if value >= 0 else "fell"

    return f"{label} {direction} {abs(value):.1f}%"


def build_index_recap(market_moves: list[dict]) -> str:
    session = get_us_market_session_status()

    sp500 = get_market_move(market_moves, "^GSPC")
    nasdaq = get_market_move(market_moves, "^IXIC")
    dow = get_market_move(market_moves, "^DJI")

    if sp500 is None or nasdaq is None or dow is None:
        return (
            f"{session['label']} "
            "Major index data is limited in the latest cache, so today’s read leans more on "
            "headlines, earnings, macro risk, and watchlist movement. "
            f"{session['price_note']}"
        )

    green_count = len([value for value in [sp500, nasdaq, dow] if value is not None and value >= 0])
    red_count = len([value for value in [sp500, nasdaq, dow] if value is not None and value < 0])

    if green_count > red_count:
        balance = "The last completed session tilted positive"
    elif red_count > green_count:
        balance = "The last completed session tilted defensive"
    else:
        balance = "The last completed session finished mixed"

    if session["state"] == "open":
        balance = balance.replace("last completed session", "market session")

    return (
        f"{session['label']} {balance}, with "
        f"{format_index_move('the S&P 500', sp500)}, "
        f"{format_index_move('the Nasdaq', nasdaq)}, and "
        f"{format_index_move('the Dow', dow)}. "
        f"{session['price_note']}"
    )


def build_theme_collision_sentence(theme_summary: dict) -> str:
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]
    top_theme = get_top_theme(theme_summary)
    examples = get_theme_examples(theme_summary, limit=3)

    if examples:
        first_theme, first_headline = examples[0]
        second_headline = examples[1][1] if len(examples) > 1 else ""

        if second_headline:
            return (
                f"The headline setup is led by {first_headline}. "
                f"The second read-through is {second_headline}. "
                f"For the portfolio, the question is whether this changes exposure to {clean_theme_label(first_theme) or top_theme}."
            )

        return (
            f"The headline setup is led by {first_headline}. "
            f"For the portfolio, the question is whether this creates real confirmation or just more noise around {top_theme}."
        )

    has_earnings = "Earnings Season" in themes
    has_oil_geo = "Oil / Geopolitical Risk" in themes
    has_ai = "AI / Chips" in themes or "AI Infrastructure / Power" in themes
    has_defense = "Defense / AI Warfare" in themes
    has_munitions = "Defense Procurement / Munitions" in themes
    has_fed = "Inflation / Fed" in themes
    has_banks = "Banks / Credit" in themes

    if has_munitions and has_oil_geo:
        return (
            "The market is watching a real defense procurement signal: geopolitical risk is colliding with a Pentagon push to scale low-cost missiles and rebuild munitions depth."
        )

    if has_munitions:
        return (
            "A major defense procurement signal is in focus, with investors watching low-cost missiles, munitions depth, production scale, and defense industrial base expansion."
        )

    if has_earnings and has_oil_geo and has_ai:
        return (
            "Earnings, oil risk, and the AI trade are competing for investor attention."
        )

    if has_earnings and has_oil_geo:
        return (
            "The market is trying to balance better earnings news against renewed oil and geopolitical risk."
        )

    if has_oil_geo and has_defense:
        return (
            "Geopolitical headlines are putting oil, shipping, defense technology, and AI warfare exposure back in focus."
        )

    if has_ai and has_fed:
        return (
            "AI leadership is still important, but rates and Fed expectations are shaping how much investors are willing to pay for growth."
        )

    if has_banks and has_earnings:
        return (
            "Bank earnings are giving investors a fresh read on credit quality, deposits, trading, and the health of the consumer."
        )

    return (
        f"The main setup today is {top_theme}, with investors watching whether the theme changes market leadership."
    )


def build_issue_title(theme: str, example: str = "") -> str:
    if theme == "Oil / Geopolitical Risk":
        return "Hormuz risk, oil prices, and the inflation problem investors cannot ignore"

    if theme == "Defense / AI Warfare":
        return "Why renewed strikes matter for defense technology, drones, cyber, ISR, and AI warfare"

    if theme == "Defense Procurement / Munitions":
        return "Why the Pentagon’s low-cost missile push matters for defense, autonomy, munitions, and AI warfare stocks"    
    
    if theme == "AI / Chips":
        return "The AI trade faces another test from chips, memory, and semiconductor demand"

    if theme == "AI Infrastructure / Power":
        return "AI infrastructure keeps spreading into power, data centers, and grid capacity"

    if theme == "Earnings Season":
        return "Earnings season separates real margin strength from weak guidance stories"

    if theme == "Banks / Credit":
        return "Banks give the first real read on credit, deposits, trading, and consumer stress"

    if theme == "Inflation / Fed":
        return "How to decode the Fed path after the latest inflation and rates signals"

    if theme == "Consumer Stress":
        return "The consumer stress signals that matter for retail, banks, and credit quality"

    if theme == "Policy / Regulation":
        return "Policy headlines that could shift sector leadership"

    if theme == "Market Breadth / Rotation":
        return "Whether market leadership is finally broadening beyond the usual winners"

    if example:
        return clean_text(example, 120)

    return "The market setup investors need to watch today"

def get_theme_examples(theme_summary: dict, limit: int = 6) -> list[tuple[str, str]]:
    theme_headlines = theme_summary.get("theme_headlines") or {}
    ranked = theme_summary.get("ranked_themes") or []

    examples = []

    for item in ranked:
        if isinstance(item, dict):
            theme = item.get("theme")
        elif isinstance(item, (list, tuple)) and item:
            theme = item[0]
        else:
            theme = None

        if not theme:
            continue

        for headline in theme_headlines.get(theme, []) or []:
            cleaned_headline = clean_text(headline, 120)

            if cleaned_headline and (theme, cleaned_headline) not in examples:
                examples.append((theme, cleaned_headline))

            if len(examples) >= limit:
                return examples

    return examples


def build_headline_issue_bullet(theme: str, headline: str) -> str:
    if theme == "Defense Procurement / Munitions":
        return f"Defense procurement watch: {headline}"

    if theme == "Defense / AI Warfare":
        return f"Defense and AI warfare read-through: {headline}"

    if theme == "Oil / Geopolitical Risk":
        return f"Oil/geopolitical risk: {headline}"

    if theme == "AI / Chips":
        return f"AI and chips: {headline}"

    if theme == "AI Infrastructure / Power":
        return f"AI infrastructure and power demand: {headline}"

    if theme == "Earnings Season":
        return f"Earnings setup: {headline}"

    if theme == "Banks / Credit":
        return f"Banks and credit: {headline}"

    if theme == "Inflation / Fed":
        return f"Fed/rates setup: {headline}"

    if theme == "Consumer Stress":
        return f"Consumer pressure: {headline}"

    return headline

def build_today_issue_bullets(
    theme_summary: dict,
    use_memory: bool = False,
    record_memory: bool = False,
) -> list[str]:
    examples = get_theme_examples(theme_summary, limit=8)

    headline_bullets = []

    for theme, headline in examples:
        bullet = build_headline_issue_bullet(theme, headline)

        if bullet and bullet not in headline_bullets:
            headline_bullets.append(bullet)

    if headline_bullets:
        primary = headline_bullets[0]
        rotated_tail = rotate_items(
            headline_bullets[1:],
            get_daily_issue_seed(theme_summary),
        )
        bullets = [primary] + rotated_tail[:4]
    else:
        ranked = theme_summary.get("ranked_themes") or []
        candidates = []

        for item in ranked[:8]:
            if isinstance(item, dict):
                theme = item.get("theme")
            elif isinstance(item, (list, tuple)) and item:
                theme = item[0]
            else:
                theme = None

            if clean_theme_label(theme) == "":
                continue

            title = build_issue_title(theme)

            if title and title not in candidates:
                candidates.append(title)

        if not candidates:
            bullets = [
                "Fresh headline flow is limited, so today’s focus is earnings, rates, AI leadership, macro risk, and watchlist confirmation.",
                "Separate real demand signals from repeated market noise.",
                "Use price and volume confirmation before acting on any headline-driven move.",
            ]
        else:
            primary = candidates[0]
            rotated_tail = rotate_items(
                candidates[1:],
                get_daily_issue_seed(theme_summary),
            )
            bullets = [primary] + rotated_tail[:4]

    if use_memory and "apply_issue_memory_filter" in globals():
        bullets = apply_issue_memory_filter(bullets)

    if record_memory and "record_issue_bullets" in globals():
        record_issue_bullets(bullets)

    return bullets[:5]

def build_what_watching(theme_summary: dict) -> str:
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]

    watch_items = []

    if "Earnings Season" in themes:
        watch_items.append("earnings quality, guidance, and margin durability")

    if "Banks / Credit" in themes:
        watch_items.append("bank earnings, deposits, credit quality, and trading revenue")

    if "AI / Chips" in themes:
        watch_items.append("AI/chip leadership, memory pressure, and semiconductor demand")

    if "AI Infrastructure / Power" in themes:
        watch_items.append("power, grid, data-center, and AI infrastructure demand")

    if "Oil / Geopolitical Risk" in themes:
        watch_items.append("oil prices, Hormuz/shipping risk, and inflation spillover")

    if "Defense / AI Warfare" in themes:
        watch_items.append("defense, cyber, drones, ISR, missile defense, and AI warfare follow-through")

    if "Defense Procurement / Munitions" in themes:
        watch_items.append("low-cost missile procurement, munitions scale, Anduril-style defense tech, and public suppliers with production exposure")
   
    if "Inflation / Fed" in themes:
        watch_items.append("Fed commentary, Treasury yields, and inflation expectations")

    if "Consumer Stress" in themes:
        watch_items.append("retail sales, consumer credit, and household pressure")

    if not watch_items:
        watch_items.append("whether leadership broadens or stays concentrated in a few high-conviction names")

    today_name = datetime.now(ZoneInfo(TIMEZONE)).strftime("%A")

    return f"What we're watching {today_name}: " + "; ".join(watch_items[:4]) + "."


def build_quote_of_day() -> str:
    quote = os.getenv("DAILY_QUOTE_TEXT", "").strip()
    attribution = os.getenv("DAILY_QUOTE_ATTRIBUTION", "").strip()

    if quote and attribution:
        return f"""
Quote of the day

"{quote}"
— {attribution}
""".strip()

    if quote:
        return f"""
Quote of the day

"{quote}"
""".strip()

    return ""
def get_cache_age_minutes(payload: dict) -> float | None:
    if not payload:
        return None

    raw_iso = payload.get("cached_at_iso") or payload.get("updated_at")
    raw_epoch = payload.get("cached_at")

    if raw_iso:
        try:
            cached_at = datetime.fromisoformat(str(raw_iso).replace("Z", "+00:00"))

            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=ZoneInfo(TIMEZONE))

            now = datetime.now(cached_at.tzinfo)

            return max(0, (now - cached_at).total_seconds() / 60)
        except Exception:
            pass

    try:
        cached_at_epoch = float(raw_epoch or 0)

        if cached_at_epoch <= 0:
            return None

        return max(0, (time.time() - cached_at_epoch) / 60)
    except Exception:
        return None


def ensure_morning_brief_cache_is_fresh(
    max_age_minutes: int | None = None,
    force_refresh: bool = False,
) -> dict:
    """
    Use this from /report, /senddaily, scheduled delivery, and scripts.

    Do not call this from build_daily_report(), because deploycheck and runtime
    smoke tests should stay fast and network-safe.
    """
    if max_age_minutes is None:
        try:
            max_age_minutes = int(os.getenv("MORNING_BRIEF_MAX_CACHE_MINUTES", "360"))
        except Exception:
            max_age_minutes = 360

    payload = load_morning_brief_cache()
    age_minutes = get_cache_age_minutes(payload)

    should_refresh = (
        force_refresh
        or not payload
        or age_minutes is None
        or age_minutes > max_age_minutes
    )

    if not should_refresh:
        return payload

    try:
        refreshed = refresh_morning_brief_cache()

        if refreshed:
            return refreshed
    except Exception as exc:
        if payload:
            payload["refresh_error"] = str(exc)
            return payload

        return {
            "refresh_error": str(exc),
            "market_moves": [],
            "headlines": [],
            "theme_summary": {},
        }

    return payload or {}


def build_data_freshness_line(payload: dict) -> str:
    age_minutes = get_cache_age_minutes(payload)
    cached_at_iso = payload.get("cached_at_iso") or payload.get("cached_at") or "unknown"

    if age_minutes is None:
        return "Data freshness: Morning brief cache timestamp unavailable."

    if age_minutes > 720:
        return (
            f"Data freshness: WARNING — Morning brief cache is stale "
            f"({age_minutes:.0f} minutes old, refreshed at {cached_at_iso})."
        )

    return (
        f"Data freshness: Morning brief refreshed {age_minutes:.0f} minutes ago "
        f"({cached_at_iso})."
    )


def rotate_items(items: list[str], seed: int) -> list[str]:
    if not items:
        return items

    offset = seed % len(items)

    return items[offset:] + items[:offset]


def get_daily_issue_seed(theme_summary: dict) -> int:
    today_key = int(datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y%m%d"))

    ranked = theme_summary.get("ranked_themes") or []
    theme_score = 0

    for _theme, count in ranked:
        try:
            theme_score += int(count)
        except Exception:
            continue

    return today_key + theme_score


def build_daily_focus_line(theme_summary: dict) -> str:
    top_theme = get_top_theme(theme_summary) or "the market setup"

    lenses = [
        "whether the move is backed by real demand or just headline momentum",
        "which themes are creating portfolio risk versus real opportunity",
        "whether leadership is broadening or staying concentrated",
        "where earnings, macro risk, and policy are changing the setup",
        "which watchlist names need confirmation before adding exposure",
    ]

    index = datetime.now(ZoneInfo(TIMEZONE)).toordinal() % len(lenses)
    lens = lenses[index]

    return f"Daily focus: {lens}, with {top_theme} as the lead theme."
def get_cache_age_minutes(payload: dict) -> float | None:
    if not payload:
        return None

    raw_iso = payload.get("cached_at_iso") or payload.get("updated_at") or ""

    if raw_iso:
        try:
            cached_at = datetime.fromisoformat(str(raw_iso).replace("Z", "+00:00"))

            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=ZoneInfo(TIMEZONE))

            now = datetime.now(cached_at.tzinfo)
            return max(0, (now - cached_at).total_seconds() / 60)
        except Exception:
            pass

    try:
        cached_at_epoch = float(payload.get("cached_at", 0) or 0)

        if cached_at_epoch <= 0:
            return None

        return max(0, (time.time() - cached_at_epoch) / 60)
    except Exception:
        return None


def ensure_morning_brief_cache_is_fresh(
    max_age_minutes: int | None = None,
    force_refresh: bool = False,
) -> dict:
    """
    Refresh Morning Brief cache before user-facing reports.

    build_daily_report() should remain cache-only so deploycheck/preflight
    stays fast and network-safe.
    """
    if max_age_minutes is None:
        try:
            max_age_minutes = int(os.getenv("MORNING_BRIEF_MAX_CACHE_MINUTES", "360"))
        except Exception:
            max_age_minutes = 360

    payload = load_morning_brief_cache()
    age_minutes = get_cache_age_minutes(payload)

    should_refresh = (
        force_refresh
        or not payload
        or age_minutes is None
        or age_minutes > max_age_minutes
    )

    if not should_refresh:
        return payload

    try:
        refreshed = refresh_morning_brief_cache()

        if refreshed:
            return refreshed

    except Exception as exc:
        if payload:
            payload["refresh_error"] = str(exc)
            return payload

        return {
            "refresh_error": str(exc),
            "market_moves": [],
            "headlines": [],
            "theme_summary": {},
        }

    return payload or {}


def build_data_freshness_line(payload: dict) -> str:
    age_minutes = get_cache_age_minutes(payload)
    cached_at_iso = payload.get("cached_at_iso") or payload.get("cached_at") or "unknown"

    if age_minutes is None:
        return "Data freshness: Morning brief cache timestamp unavailable."

    if age_minutes > 720:
        return (
            f"Data freshness: WARNING — Morning brief cache is stale "
            f"({age_minutes:.0f} minutes old, refreshed at {cached_at_iso})."
        )

    return (
        f"Data freshness: Morning brief refreshed {age_minutes:.0f} minutes ago "
        f"({cached_at_iso})."
    )

def parse_env_list(value: str, separator: str = ",") -> list[str]:
    return [
        item.strip()
        for item in str(value or "").split(separator)
        if item.strip()
    ]


def get_market_week_move(market_moves: list[dict], symbol: str) -> float | None:
    for item in market_moves:
        if str(item.get("symbol", "")).upper() == symbol.upper():
            try:
                value = item.get("week_move")

                if value is None:
                    return None

                return float(value)
            except Exception:
                return None

    return None


def should_show_week_ahead_block() -> bool:
    now_et = datetime.now(ZoneInfo(MARKET_TIMEZONE))
    # Friday after close, Saturday, Sunday, and Monday should emphasize the week ahead.
    return now_et.weekday() in {0, 4, 5, 6}


def format_move_phrase(label: str, value: float | None, period: str = "") -> str:
    if value is None:
        return f"{label} was unavailable"

    direction = "gained" if value >= 0 else "lost"
    period_text = f" {period}" if period else ""

    return f"{label} {direction} {abs(value):.1f}%{period_text}"


def build_weekly_market_recap(market_moves: list[dict]) -> str:
    sp_day = get_market_move(market_moves, "^GSPC")
    dow_day = get_market_move(market_moves, "^DJI")
    nasdaq_day = get_market_move(market_moves, "^IXIC")

    sp_week = get_market_week_move(market_moves, "^GSPC")
    dow_week = get_market_week_move(market_moves, "^DJI")
    nasdaq_week = get_market_week_move(market_moves, "^IXIC")

    if sp_day is None or dow_day is None or nasdaq_day is None:
        return (
            "The latest index recap is limited, so the week-ahead read should lean more on "
            "headlines, earnings, macro themes, and portfolio exposure."
        )

    if sp_day < 0 and nasdaq_day < 0:
        opener = "A new week begins after a rough day in the markets."
    elif sp_day >= 0 and nasdaq_day >= 0:
        opener = "A new week begins after a constructive close for the major indexes."
    else:
        opener = "A new week begins after a mixed finish for the major indexes."

    if sp_week is None or dow_week is None or nasdaq_week is None:
        return (
            f"{opener} The S&P 500 {format_move_phrase('', sp_day).strip()}, "
            f"the Dow {format_move_phrase('', dow_day).strip()}, and "
            f"the Nasdaq {format_move_phrase('', nasdaq_day).strip()} in the latest completed session."
        )

    return (
        f"{opener} In the latest completed session, "
        f"{format_move_phrase('the S&P 500', sp_day)}, "
        f"{format_move_phrase('the Dow', dow_day)}, and "
        f"{format_move_phrase('the Nasdaq', nasdaq_day)}. "
        f"Across the recent five-day window, "
        f"{format_move_phrase('the S&P 500', sp_week)}, "
        f"{format_move_phrase('the Dow', dow_week)}, and "
        f"{format_move_phrase('the Nasdaq', nasdaq_week)}."
    )


def infer_week_ahead_narratives(theme_summary: dict) -> list[str]:
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]
    narratives = []

    if "Oil / Geopolitical Risk" in themes:
        narratives.append("Hormuz, oil, shipping, and Middle East risk")

    if "AI / Chips" in themes:
        narratives.append("whether the semiconductor trade stabilizes or keeps selling off")

    if "AI Infrastructure / Power" in themes:
        narratives.append("AI infrastructure, power demand, data centers, and grid capacity")

    if "Earnings Season" in themes:
        narratives.append("earnings quality, guidance, margins, and Big Tech AI returns")

    if "Defense Procurement / Munitions" in themes:
        narratives.append("defense procurement, munitions depth, and low-cost missile demand")

    if "Inflation / Fed" in themes:
        narratives.append("Fed commentary, Treasury yields, and inflation expectations")

    if "Banks / Credit" in themes:
        narratives.append("bank earnings, credit quality, deposits, and consumer resilience")

    if not narratives:
        narratives.append("earnings, rates, AI leadership, risk appetite, and portfolio confirmation")

    return narratives[:5]


def build_week_ahead_block(theme_summary: dict, market_moves: list[dict]) -> str:
    if not should_show_week_ahead_block():
        return ""

    manual_narratives = parse_env_list(WEEK_AHEAD_NARRATIVES, separator=";")
    earnings = parse_env_list(WEEK_AHEAD_EARNINGS)
    econ_events = parse_env_list(WEEK_AHEAD_ECON_EVENTS, separator=";")

    narratives = manual_narratives or infer_week_ahead_narratives(theme_summary)
    market_recap = build_weekly_market_recap(market_moves)

    if earnings:
        earnings_text = (
            "Earnings focus: "
            + ", ".join(earnings[:10])
            + "."
        )
    else:
        earnings_text = (
            "Earnings focus: use /weeklycalendar for the full company schedule; "
            "watch especially for Big Tech, semiconductors, banks, industrials, power, and consumer read-throughs."
        )

    if econ_events:
        econ_text = "Economic calendar: " + "; ".join(econ_events[:5]) + "."
    else:
        econ_text = (
            "Economic calendar: if the data calendar is light, the market may lean more heavily on earnings, yields, oil, the dollar, and headlines."
        )

    narrative_text = "\n".join(f"• {item}" for item in narratives[:5])

    return f"""
Week Ahead / Big Picture
{market_recap}

The big narratives:
{narrative_text}

{earnings_text}
{econ_text}
""".strip()

def build_morning_brief_intro(force_refresh: bool = False) -> str:
    """
    Report-safe builder.

    Default behavior is cache-only so /report and /deploycheck stay fast.
    Use force_refresh=True only from a refresh command or before scheduled delivery.
    """
    if force_refresh:
        payload = refresh_morning_brief_cache()
    else:
        payload = load_morning_brief_cache()

    if not payload:
        return build_fallback_intro()

    market_moves = payload.get("market_moves") or []
    theme_summary = payload.get("theme_summary") or {}
    cached_at_iso = payload.get("cached_at_iso", "latest available cache")

    opening_sentence = build_theme_collision_sentence(theme_summary)
    index_recap = build_index_recap(market_moves)
    week_ahead_block = build_week_ahead_block(theme_summary, market_moves)
    issue_bullets = payload.get("issue_bullets")

    if not isinstance(issue_bullets, list) or not issue_bullets:
        issue_bullets = build_today_issue_bullets(
        theme_summary,
        use_memory=False,
        record_memory=False,
    )
    what_watching = build_what_watching(theme_summary)
    portfolio_read = build_portfolio_read(theme_summary)
    quote_of_day = build_quote_of_day()
    daily_focus = build_daily_focus_line(theme_summary)
    freshness_line = build_data_freshness_line(payload)
    session = get_us_market_session_status()

    bullet_text = "\n".join(f"• {bullet}" for bullet in issue_bullets)

    quote_block = ""

    if quote_of_day:
        quote_block = f"\n\n{quote_of_day}"

    return f"""
Good morning!

Market Status:
{session['label']}

{opening_sentence}

{index_recap}

{week_ahead_block}

{daily_focus}

In today's issue
{bullet_text}

{what_watching}

{portfolio_read}{quote_block}

{freshness_line}
""".strip()