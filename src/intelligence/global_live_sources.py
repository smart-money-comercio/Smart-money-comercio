import json
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


CACHE_FILE = Path(
    os.getenv("GLOBAL_LIVE_SOURCE_CACHE_FILE", "data/global_live_source_cache.json")
)

CACHE_TTL_SECONDS = int(os.getenv("GLOBAL_LIVE_SOURCE_CACHE_TTL_SECONDS", "1800"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("GLOBAL_SOURCE_TIMEOUT_SECONDS", "8"))
MAX_ITEMS_PER_SOURCE = int(os.getenv("GLOBAL_MAX_ITEMS_PER_SOURCE", "7"))


GLOBAL_SOURCE_URLS = [
    {
        "name": "Federal Reserve Press Releases",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "source_type": "Federal Reserve",
    },
    {
        "name": "Federal Reserve RSS Feeds",
        "url": "https://www.federalreserve.gov/feeds/feeds.htm",
        "source_type": "Federal Reserve",
    },
    {
        "name": "U.S. Treasury Daily Rates",
        "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        "source_type": "Treasury",
    },
    {
        "name": "White House News",
        "url": "https://www.whitehouse.gov/news/",
        "source_type": "White House",
    },
    {
        "name": "White House Fact Sheets",
        "url": "https://www.whitehouse.gov/fact-sheets/",
        "source_type": "White House",
    },
    {
        "name": "EIA RSS Feeds",
        "url": "https://www.eia.gov/tools/rssfeeds/",
        "source_type": "EIA",
    },
    {
        "name": "Defense.gov News RSS",
        "url": "https://www.defense.gov/news/rss/",
        "source_type": "Defense.gov",
    },
]


GLOBAL_KEYWORDS = [
    "federal reserve",
    "fomc",
    "interest rate",
    "inflation",
    "treasury",
    "yield",
    "dollar",
    "oil",
    "energy",
    "eia",
    "geopolitical",
    "tariff",
    "trade",
    "china",
    "taiwan",
    "iran",
    "ukraine",
    "red sea",
    "middle east",
    "defense",
    "procurement",
    "sanctions",
    "bank",
    "credit",
    "jobs",
    "employment",
    "cpi",
    "ppi",
    "consumer",
    "housing",
    "manufacturing",
    "recession",
    "growth",
    "budget",
    "debt",
    "appropriations",
]


THEME_KEYWORDS = {
    "Fed / Rates": [
        "federal reserve",
        "fomc",
        "interest rate",
        "monetary policy",
        "inflation",
        "treasury",
        "yield",
    ],
    "Inflation / Energy": [
        "inflation",
        "oil",
        "energy",
        "gasoline",
        "petroleum",
        "eia",
        "supply",
        "inventory",
    ],
    "Dollar / Liquidity": [
        "dollar",
        "treasury",
        "liquidity",
        "funding",
        "credit",
        "bank",
    ],
    "Geopolitical Risk": [
        "china",
        "taiwan",
        "iran",
        "ukraine",
        "red sea",
        "middle east",
        "sanctions",
        "tariff",
    ],
    "Defense / Policy": [
        "defense",
        "procurement",
        "military",
        "pentagon",
        "missile",
        "munitions",
        "appropriations",
    ],
    "Growth / Consumer": [
        "jobs",
        "employment",
        "consumer",
        "housing",
        "growth",
        "manufacturing",
        "recession",
    ],
}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth:
            return

        text = " ".join(str(data or "").split())

        if text:
            self.parts.append(text)


def clean_text(value: Any, max_chars: int = 240) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def strip_html(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html or "")
    return " ".join(parser.parts)


def fetch_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "SmartMoneyAI/1.3 global-intelligence",
            "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        content = response.read(800_000)

    return content.decode("utf-8", errors="replace")


def load_cache() -> dict:
    try:
        if not CACHE_FILE.exists():
            return {}

        with CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_cache(payload: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with CACHE_FILE.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)

    except Exception:
        return


def cache_is_fresh(payload: dict) -> bool:
    try:
        fetched_at = float(payload.get("fetched_at", 0) or 0)
        return time.time() - fetched_at <= CACHE_TTL_SECONDS
    except Exception:
        return False


def sentence_split(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()

    if not text:
        return []

    rough = re.split(r"(?<=[.!?])\s+", text)
    return [item.strip() for item in rough if len(item.strip()) >= 35]


def keyword_score(text: str) -> int:
    lowered = f" {str(text or '').lower()} "
    score = 0

    for keyword in GLOBAL_KEYWORDS:
        if keyword.lower() in lowered:
            score += 1

    return score


def extract_source_items(source: dict, raw_content: str) -> list[dict]:
    text = strip_html(raw_content)

    if not text:
        text = raw_content

    sentences = sentence_split(text)
    scored = []

    for sentence in sentences:
        score = keyword_score(sentence)

        if score <= 0:
            continue

        scored.append(
            {
                "source": source["name"],
                "source_type": source["source_type"],
                "url": source["url"],
                "headline": clean_text(sentence, 190),
                "score": score,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)

    deduped = []
    seen = set()

    for item in scored:
        key = item["headline"].lower()

        if key in seen:
            continue

        seen.add(key)
        deduped.append(item)

        if len(deduped) >= MAX_ITEMS_PER_SOURCE:
            break

    return deduped


def detect_themes(items: list[dict]) -> list[dict]:
    joined = " ".join(item.get("headline", "") for item in items).lower()
    themes = []

    for theme, keywords in THEME_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword.lower() in joined]

        if hits:
            themes.append(
                {
                    "theme": theme,
                    "hits": hits[:5],
                    "score": len(hits),
                }
            )

    themes.sort(key=lambda item: item["score"], reverse=True)

    return themes[:8]


def fetch_global_live_context(force_refresh: bool = False) -> dict:
    cached = load_cache()

    if cached and cache_is_fresh(cached) and not force_refresh:
        cached["cache_status"] = "fresh"
        return cached

    items = []
    source_errors = []

    for source in GLOBAL_SOURCE_URLS:
        try:
            content = fetch_url(source["url"])
            source_items = extract_source_items(source, content)
            items.extend(source_items)
        except Exception as error:
            source_errors.append(
                {
                    "source": source["name"],
                    "error": f"{type(error).__name__}: {error}",
                }
            )

    themes = detect_themes(items)

    payload = {
        "fetched_at": time.time(),
        "cache_status": "refreshed",
        "items": items[:35],
        "themes": themes,
        "source_errors": source_errors,
        "source_count": len(GLOBAL_SOURCE_URLS),
        "item_count": len(items),
    }

    save_cache(payload)
    return payload


def format_source_snapshot(payload: dict, limit: int = 8) -> str:
    items = payload.get("items", []) or []

    if not items:
        errors = payload.get("source_errors", []) or []

        if errors:
            return "• Live official-source scan unavailable; using market and scoring fallback."

        return "• No macro-specific official-source items detected in the latest scan."

    lines = []

    for item in items[:limit]:
        lines.append(f"• {item.get('source_type')}: {item.get('headline')}")

    return "\n".join(lines)


def format_theme_snapshot(payload: dict) -> str:
    themes = payload.get("themes", []) or []

    if not themes:
        return "• No dominant official-source macro theme detected."

    lines = []

    for item in themes[:6]:
        hits = ", ".join(item.get("hits", [])[:3])
        lines.append(f"• {item.get('theme')}: {hits}")

    return "\n".join(lines)


def build_live_context_summary(payload: dict) -> str:
    status = payload.get("cache_status", "unknown")
    item_count = payload.get("item_count", 0)
    source_count = payload.get("source_count", 0)
    error_count = len(payload.get("source_errors", []) or [])

    return (
        f"Source scan: {item_count} macro-relevant items across {source_count} official-source endpoints. "
        f"Cache: {status}. Source errors: {error_count}."
    )