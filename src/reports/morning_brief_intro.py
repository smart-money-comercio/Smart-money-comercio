import json
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


MARKET_ASSETS = [
    {"symbol": "^GSPC", "label": "S&P 500"},
    {"symbol": "^IXIC", "label": "Nasdaq"},
    {"symbol": "^DJI", "label": "Dow"},
    {"symbol": "^RUT", "label": "Russell 2000"},
    {"symbol": "^VIX", "label": "VIX"},
    {"symbol": "USO", "label": "Oil"},
]

RSS_FEEDS = [
    "https://finance.yahoo.com/news/rssindex",
    "https://finance.yahoo.com/topic/stock-market-news/rss",
    "https://finance.yahoo.com/topic/earnings/rss",
]


THEME_KEYWORDS = {
    "AI / Chips": [
        "ai", "chip", "semiconductor", "nvidia", "amd", "broadcom",
        "sk hynix", "tsmc", "asml", "data center", "hyperscaler",
        "openai", "apple",
    ],
    "Oil / Geopolitical Risk": [
        "oil", "crude", "hormuz", "iran", "middle east", "strait",
        "geopolitical", "shipping",
    ],
    "Earnings Season": [
        "earnings", "results", "guidance", "revenue", "profit",
        "jpmorgan", "bank of america", "goldman", "wells fargo",
        "citigroup", "morgan stanley",
    ],
    "Inflation / Fed": [
        "cpi", "ppi", "inflation", "fed", "federal reserve",
        "rates", "yield", "treasury", "warsh",
    ],
    "Consumer Stress": [
        "credit card", "groceries", "consumer", "walmart",
        "prices", "retail sales", "delinquency",
    ],
    "Policy / Regulation": [
        "tariff", "refund", "eu", "regulation", "social media",
        "retirement", "white house", "trump",
    ],
    "Automation / Mobility": [
        "robotaxi", "waymo", "uber", "rivian", "tesla",
        "autonomous",
    ],
}


def clean_text(value: Any, max_length: int = 240) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


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
            return {"symbol": symbol, "move": None}

        previous = clean_closes[-2]
        latest = clean_closes[-1]

        if previous == 0:
            return {"symbol": symbol, "move": None}

        move = ((latest - previous) / previous) * 100

        return {
            "symbol": symbol,
            "latest": round(latest, 2),
            "previous": round(previous, 2),
            "move": round(move, 2),
        }

    except Exception:
        return {"symbol": symbol, "move": None}


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
                    return headlines

        except Exception:
            continue

    return headlines


def classify_headline(headline: str) -> list[str]:
    text = headline.lower()
    themes = []

    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            themes.append(theme)

    if not themes:
        themes.append("Market")

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

    top_theme = ranked_themes[0][0] if ranked_themes else "Market"

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
        return "Stocks enter the day with investors focused on earnings, inflation, rates, and the next phase of the AI trade."

    direction = "higher" if sp500 >= 0 else "lower"

    return (
        f"Stocks finished the latest session {direction}, with the "
        f"S&P 500 {'up' if sp500 >= 0 else 'down'} {abs(sp500):.1f}%, "
        f"the Nasdaq {'up' if nasdaq >= 0 else 'down'} {abs(nasdaq):.1f}%, "
        f"and the Dow {'up' if dow >= 0 else 'down'} {abs(dow):.1f}%."
    )


def build_today_issue_bullets(theme_summary: dict) -> list[str]:
    ranked = theme_summary.get("ranked_themes") or []
    theme_headlines = theme_summary.get("theme_headlines") or {}

    bullets = []

    for theme, _count in ranked[:5]:
        examples = theme_headlines.get(theme, [])
        example = examples[0] if examples else ""

        if theme == "AI / Chips":
            bullets.append("AI and chip-sector headlines remain the market’s most important growth theme.")
        elif theme == "Oil / Geopolitical Risk":
            bullets.append("Oil and geopolitical risk are back in focus for inflation and risk sentiment.")
        elif theme == "Earnings Season":
            bullets.append("Earnings season is driving the next test for margins, guidance, and credit quality.")
        elif theme == "Inflation / Fed":
            bullets.append("Inflation and Fed-rate expectations remain central to the market setup.")
        elif theme == "Consumer Stress":
            bullets.append("Consumer stress headlines are worth watching for credit, retail, and bank exposure.")
        elif theme == "Policy / Regulation":
            bullets.append("Policy and regulation headlines could affect sector leadership.")
        elif example:
            bullets.append(example)

    if not bullets:
        bullets = [
            "Earnings, inflation, rates, and AI leadership remain the main market drivers.",
            "Portfolio positioning should stay selective until leadership broadens.",
        ]

    return bullets[:5]


def build_what_watching(theme_summary: dict) -> str:
    top_theme = theme_summary.get("top_theme", "Market")
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]

    watch_items = []

    if "Inflation / Fed" in themes:
        watch_items.append("inflation data and the bond-market reaction")

    if "Earnings Season" in themes:
        watch_items.append("bank earnings, margins, guidance, and credit quality")

    if "AI / Chips" in themes:
        watch_items.append("whether AI leadership stabilizes or continues to rotate")

    if "Oil / Geopolitical Risk" in themes:
        watch_items.append("oil prices and geopolitical spillover risk")

    if "Consumer Stress" in themes:
        watch_items.append("consumer credit, retail demand, and household pressure")

    if not watch_items:
        watch_items.append(f"whether the {top_theme.lower()} theme changes market leadership")

    return "What we're watching: " + "; ".join(watch_items[:4]) + "."


def build_portfolio_read(theme_summary: dict) -> str:
    themes = [item[0] for item in theme_summary.get("ranked_themes", [])]

    reads = []

    if "AI / Chips" in themes:
        reads.append("stay selective in AI and semiconductors; favor infrastructure winners over crowded momentum.")

    if "Oil / Geopolitical Risk" in themes:
        reads.append("watch oil-sensitive inflation risk and defense/geopolitical beneficiaries.")

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

Markets enter the day focused on earnings, inflation, interest rates, AI leadership, and portfolio risk. The daily report is using the latest available cached morning brief. Use /headlines and /global for live market context if you want a fresh intraday read.

In today's issue:
• Market leadership and risk appetite.
• Earnings and guidance quality.
• Inflation, rates, and Fed expectations.
• AI, semiconductors, and infrastructure demand.
• Watchlist opportunities and risk notes.

What we're watching:
Whether earnings and macro data support a broader rally or keep leadership concentrated in a smaller group of high-conviction names.
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

    market_recap = format_market_recap(market_moves)
    issue_bullets = build_today_issue_bullets(theme_summary)
    what_watching = build_what_watching(theme_summary)
    portfolio_read = build_portfolio_read(theme_summary)

    bullet_text = "\n".join(f"• {bullet}" for bullet in issue_bullets)

    top_theme = theme_summary.get("top_theme", "Market")

    return f"""
Good morning.

{market_recap}

The dominant market theme right now is {top_theme}. The signal from headlines is that investors are not just reacting to price action — they are reassessing earnings quality, inflation risk, AI leadership, and where capital is rotating next.

In today's issue:
{bullet_text}

{what_watching}

{portfolio_read}

Data freshness:
Morning brief refreshed at {cached_at_iso}.
""".strip()