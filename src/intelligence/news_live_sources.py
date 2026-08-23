import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


CACHE_FILE = Path(os.getenv("NEWS_LIVE_SOURCE_CACHE_FILE", "data/news_live_source_cache.json"))
CACHE_TTL_SECONDS = int(os.getenv("NEWS_LIVE_SOURCE_CACHE_TTL_SECONDS", "1800"))
REQUEST_TIMEOUT = int(os.getenv("NEWS_LIVE_SOURCE_TIMEOUT_SECONDS", "12"))
TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")

USER_AGENT = os.getenv(
    "NEWS_LIVE_SOURCE_USER_AGENT",
    "SmartMoneyAI/1.4 market-news research bot",
)


NEWS_SOURCES = [
    {
        "name": "Yahoo Finance Market",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5EIXIC,%5EDJI,%5ETNX,%5ETYX,TLT,USO,GLD,BTC-USD&region=US&lang=en-US",
        "category": "market",
    },
    {
        "name": "Yahoo Finance Technology",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA,AAPL,MSFT,AMZN,GOOGL,META,TSLA,AMD,AVGO,PLTR&region=US&lang=en-US",
        "category": "technology",
    },
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "category": "fed",
    },
    {
        "name": "U.S. Treasury",
        "url": "https://home.treasury.gov/rss/press-releases",
        "category": "treasury",
    },
    {
        "name": "EIA",
        "url": "https://www.eia.gov/rss/todayinenergy.xml",
        "category": "energy",
    },
]


THEME_TERMS = {
    "Rates / Yields": [
        "yield",
        "yields",
        "treasury",
        "bond",
        "bonds",
        "10-year",
        "30-year",
        "tnx",
        "tyx",
        "mortgage rates",
    ],
    "Fed / Policy": [
        "fed",
        "federal reserve",
        "powell",
        "warsh",
        "rate cut",
        "rate hike",
        "inflation",
        "monetary policy",
        "fomc",
    ],
    "Treasury / Debt": [
        "treasury",
        "buyback",
        "buybacks",
        "debt",
        "deficit",
        "issuance",
        "auction",
        "borrowing costs",
    ],
    "Oil / Energy": [
        "oil",
        "crude",
        "wti",
        "brent",
        "gasoline",
        "energy",
        "opec",
        "eia",
    ],
    "Geopolitical Risk": [
        "iran",
        "russia",
        "ukraine",
        "china",
        "taiwan",
        "war",
        "conflict",
        "sanctions",
        "blockade",
        "geopolitical",
    ],
    "China / Trade": [
        "china",
        "tariff",
        "tariffs",
        "trade",
        "exports",
        "imports",
        "yuan",
        "beijing",
        "hong kong",
    ],
    "AI / Semiconductors": [
        "ai",
        "artificial intelligence",
        "semiconductor",
        "semiconductors",
        "chip",
        "chips",
        "nvidia",
        "nvda",
        "amd",
        "avgo",
        "tsmc",
        "sk hynix",
    ],
    "Mega-Cap Tech": [
        "apple",
        "microsoft",
        "amazon",
        "google",
        "alphabet",
        "meta",
        "tesla",
        "magnificent seven",
        "nasdaq",
    ],
    "Consumer / Retail": [
        "consumer",
        "retail",
        "walmart",
        "target",
        "costco",
        "spending",
        "k-shaped",
        "earnings miss",
    ],
    "Defense / Policy": [
        "defense",
        "pentagon",
        "missile",
        "drone",
        "cyber",
        "contract",
        "procurement",
        "boeing",
        "lockheed",
        "palantir",
    ],
    "Crypto / Liquidity": [
        "bitcoin",
        "crypto",
        "liquidity",
        "dollar",
        "gold",
        "risk assets",
    ],
}


TICKER_TERMS = {
    "NVDA": ["nvda", "nvidia"],
    "AAPL": ["aapl", "apple"],
    "MSFT": ["msft", "microsoft"],
    "AMZN": ["amzn", "amazon"],
    "GOOGL": ["googl", "google", "alphabet"],
    "META": ["meta", "facebook"],
    "TSLA": ["tsla", "tesla"],
    "AMD": ["amd"],
    "AVGO": ["avgo", "broadcom"],
    "PLTR": ["pltr", "palantir"],
    "SPY": ["s&p 500", "sp500", "^gspc"],
    "QQQ": ["nasdaq", "^ixic"],
    "TLT": ["tlt", "long-term treasury", "long bond"],
    "USO": ["uso", "oil", "crude"],
    "GLD": ["gld", "gold"],
}


def now_text() -> str:
    try:
        current = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        current = datetime.now()

    return current.strftime("%Y-%m-%d %H:%M:%S")


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact_text(value: Any, max_chars: int = 220) -> str:
    text = normalize_text(value)

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def clean_symbol(value: str) -> str:
    return str(value or "").upper().replace("$", "").strip()


def load_cache() -> dict:
    try:
        if not CACHE_FILE.exists():
            return {}

        with CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with CACHE_FILE.open("w", encoding="utf-8") as file:
            json.dump(cache, file, indent=2, sort_keys=True)

    except Exception:
        return


def get_cached_source(url: str) -> dict | None:
    cache = load_cache()
    item = cache.get(url)

    if not isinstance(item, dict):
        return None

    fetched_at_epoch = item.get("fetched_at_epoch")

    try:
        age = time.time() - float(fetched_at_epoch)
    except Exception:
        return None

    if age > CACHE_TTL_SECONDS:
        return None

    return item


def set_cached_source(url: str, payload: dict) -> None:
    cache = load_cache()
    cache[url] = payload
    save_cache(cache)


def fetch_url(url: str, force_refresh: bool = False) -> dict:
    if not force_refresh:
        cached = get_cached_source(url)

        if cached:
            cached["cache_hit"] = True
            return cached

    try:
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, text/html",
            },
        )

        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")

        payload = {
            "url": url,
            "status": "ok",
            "error": "",
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": raw,
        }

        set_cached_source(url, payload)
        return payload

    except HTTPError as error:
        return {
            "url": url,
            "status": "error",
            "error": f"HTTPError {error.code}",
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": "",
        }

    except URLError as error:
        return {
            "url": url,
            "status": "error",
            "error": f"URLError {error.reason}",
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": "",
        }

    except Exception as error:
        return {
            "url": url,
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": "",
        }


def child_text(item: ET.Element, tag_name: str) -> str:
    for child in list(item):
        local_name = child.tag.split("}")[-1].lower()

        if local_name == tag_name.lower():
            return normalize_text(child.text or "")

    return ""


def parse_rss_items(xml_text: str, source: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    items = []

    for item in root.iter():
        if item.tag.split("}")[-1].lower() != "item":
            continue

        title = child_text(item, "title")
        description = child_text(item, "description")
        link = child_text(item, "link")
        published = child_text(item, "pubDate")

        if not title:
            continue

        items.append(
            {
                "title": compact_text(title, 180),
                "description": compact_text(description, 280),
                "link": link,
                "published": published,
                "source": source.get("name", "Unknown"),
                "category": source.get("category", "market"),
            }
        )

    return items


def extract_html_title(raw_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.I | re.S)

    if match:
        return compact_text(match.group(1), 180)

    return ""


def parse_source_payload(payload: dict, source: dict) -> list[dict]:
    body = payload.get("body", "") or ""

    items = parse_rss_items(body, source)

    if items:
        return items

    title = extract_html_title(body)

    if title:
        return [
            {
                "title": title,
                "description": "",
                "link": source.get("url", ""),
                "published": payload.get("fetched_at", ""),
                "source": source.get("name", "Unknown"),
                "category": source.get("category", "market"),
            }
        ]

    return []


def text_blob(item: dict) -> str:
    return " ".join(
        [
            str(item.get("title", "")),
            str(item.get("description", "")),
            str(item.get("source", "")),
            str(item.get("category", "")),
        ]
    ).lower()


def detect_item_themes(item: dict) -> list[str]:
    blob = text_blob(item)
    themes = []

    for theme, terms in THEME_TERMS.items():
        if any(term.lower() in blob for term in terms):
            themes.append(theme)

    return themes


def detect_item_tickers(item: dict) -> list[str]:
    blob = text_blob(item)
    tickers = []

    for symbol, terms in TICKER_TERMS.items():
        if any(term.lower() in blob for term in terms):
            tickers.append(symbol)

    return tickers


def fingerprint_items(items: list[dict]) -> str:
    core = "|".join(
        sorted(
            compact_text(
                f"{item.get('source','')}::{item.get('title','')}::{item.get('published','')}",
                260,
            )
            for item in items[:80]
        )
    )

    return hashlib.sha256(core.encode("utf-8", errors="ignore")).hexdigest()[:16]


def enrich_items(items: list[dict]) -> list[dict]:
    enriched = []

    seen_titles = set()

    for item in items:
        title_key = normalize_text(item.get("title", "")).lower()

        if not title_key or title_key in seen_titles:
            continue

        seen_titles.add(title_key)

        copy = dict(item)
        copy["themes"] = detect_item_themes(copy)
        copy["tickers"] = detect_item_tickers(copy)
        copy["importance"] = score_item_importance(copy)
        enriched.append(copy)

    enriched.sort(key=lambda item: item.get("importance", 0), reverse=True)

    return enriched


def score_item_importance(item: dict) -> int:
    themes = item.get("themes", []) or []
    tickers = item.get("tickers", []) or []
    blob = text_blob(item)

    score = 1
    score += min(len(themes), 4)
    score += min(len(tickers), 3)

    high_impact_terms = [
        "fed",
        "treasury",
        "yield",
        "inflation",
        "oil",
        "china",
        "tariff",
        "debt",
        "war",
        "earnings",
        "guidance",
        "downgrade",
        "upgrade",
        "buyback",
    ]

    score += sum(1 for term in high_impact_terms if term in blob)

    return score


def summarize_theme_counts(items: list[dict]) -> dict[str, int]:
    counts = {}

    for item in items:
        for theme in item.get("themes", []) or []:
            counts[theme] = counts.get(theme, 0) + 1

    return dict(sorted(counts.items(), key=lambda pair: pair[1], reverse=True))


def summarize_ticker_counts(items: list[dict]) -> dict[str, int]:
    counts = {}

    for item in items:
        for ticker in item.get("tickers", []) or []:
            counts[ticker] = counts.get(ticker, 0) + 1

    return dict(sorted(counts.items(), key=lambda pair: pair[1], reverse=True))


def fetch_news_live_context(force_refresh: bool = False) -> dict:
    source_results = []
    items = []
    errors = []

    for source in NEWS_SOURCES:
        payload = fetch_url(source["url"], force_refresh=force_refresh)
        parsed_items = parse_source_payload(payload, source)

        source_results.append(
            {
                "name": source.get("name", "Unknown"),
                "category": source.get("category", "market"),
                "status": payload.get("status", "unknown"),
                "cache_hit": payload.get("cache_hit", False),
                "item_count": len(parsed_items),
                "error": payload.get("error", ""),
            }
        )

        if payload.get("status") != "ok":
            errors.append(f"{source.get('name', 'Unknown')}: {payload.get('error', 'unknown error')}")

        items.extend(parsed_items)

    enriched = enrich_items(items)
    theme_counts = summarize_theme_counts(enriched)
    ticker_counts = summarize_ticker_counts(enriched)

    return {
        "source": "Live Market News",
        "fetched_at": now_text(),
        "force_refresh": force_refresh,
        "items": enriched,
        "top_items": enriched[:20],
        "themes": theme_counts,
        "tickers": ticker_counts,
        "fingerprint": fingerprint_items(enriched),
        "source_results": source_results,
        "errors": errors,
    }


def format_source_status(context: dict) -> str:
    rows = []

    for source in context.get("source_results", []) or []:
        cache = "cache" if source.get("cache_hit") else "live"
        rows.append(
            f"• {source.get('name')}: {source.get('status')} | {cache} | items: {source.get('item_count', 0)}"
        )

    if not rows:
        return "• No source status available."

    return "\n".join(rows[:10])


def filter_items_for_symbol(items: list[dict], symbol: str) -> list[dict]:
    symbol = clean_symbol(symbol)

    if not symbol:
        return []

    terms = [symbol.lower()] + TICKER_TERMS.get(symbol, [])

    selected = []

    for item in items:
        blob = text_blob(item)

        if symbol in item.get("tickers", []) or any(term.lower() in blob for term in terms):
            selected.append(item)

    return selected