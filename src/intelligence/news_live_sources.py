import hashlib
import html
import json
import math
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.intelligence.special_alert_company_sources import OFFICIAL_FEEDS
from src.intelligence.special_alert_sources import timestamp
from src.intelligence import news_original_sources as originals


CACHE_FILE = Path(os.getenv("NEWS_LIVE_SOURCE_CACHE_FILE", "data/news_live_source_cache.json"))
CACHE_TTL_SECONDS = int(os.getenv("NEWS_LIVE_SOURCE_CACHE_TTL_SECONDS", "1800"))
REQUEST_TIMEOUT = int(os.getenv("NEWS_LIVE_SOURCE_TIMEOUT_SECONDS", "12"))
MAX_FEED_BYTES = 2_000_000
MAX_CACHE_BYTES = 12_000_000
CACHE_LOCK = RLock()
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
        "url": "https://home.treasury.gov/news/press-releases",
        "category": "treasury",
        "format": "treasury",
    },
    {
        "name": "EIA",
        "url": "https://www.eia.gov/rss/todayinenergy.xml",
        "category": "energy",
    },
    {"name": "Nvidia Newsroom", "url": OFFICIAL_FEEDS["NVDA"], "category": "company", "company_symbol": "NVDA"},
    {"name": "Microsoft Blog", "url": OFFICIAL_FEEDS["MSFT"], "category": "company", "company_symbol": "MSFT"},
    {"name": "Lockheed Martin Newsroom", "url": "https://news.lockheedmartin.com/news-releases?pagetemplate=rss", "category": "company", "company_symbol": "LMT"},
    {"name": "DARPA", "url": "https://www.darpa.mil/rss.xml", "category": "defense"},
    {"name": "Palantir Investor Relations", "url": OFFICIAL_FEEDS["PLTR"], "category": "company", "company_symbol": "PLTR", "format": "palantir"},
    {"name": "Broadcom Investor Relations", "url": "https://investors.broadcom.com/rss/news-releases.xml", "category": "company", "company_symbol": "AVGO"},
    {"name": "AeroVironment Investor Relations", "url": "https://investor.avinc.com/rss/news-releases.xml", "category": "company", "company_symbol": "AVAV"},
    {"name": "Kratos Investor Relations", "url": "https://ir.kratosdefense.com/rss/news-releases.xml", "category": "company", "company_symbol": "KTOS"},
    {"name": "CrowdStrike Investor Relations", "url": "https://ir.crowdstrike.com/rss/news-releases.xml", "category": "company", "company_symbol": "CRWD"},
    {"name": "Tesla Investor Relations", "url": "https://ir.tesla.com/rss/news-releases.xml", "category": "company", "company_symbol": "TSLA"},
    {"name": "Apple Newsroom", "url": "https://www.apple.com/newsroom/rss-feed.rss", "category": "company", "company_symbol": "AAPL"},
    {"name": "TSMC Press Center", "url": "https://pr.tsmc.com/english/latest-news", "category": "company", "company_symbol": "TSM", "format": "index", "article_pattern": r"/english/news/\d+"},
    {"name": "Northrop Grumman Newsroom", "url": "https://news.northropgrumman.com/News-Stream", "category": "company", "company_symbol": "NOC", "format": "index", "article_pattern": r"/news/releases/[^/]+|/releases/[^/]+"},
    {"name": "Northrop Grumman Investor Relations", "url": "https://investor.northropgrumman.com/rss/news-releases.xml", "category": "company", "company_symbol": "NOC"},
    {"name": "CACI Investor Relations", "url": "https://investor.caci.com/news?pagetemplate=rss", "category": "company", "company_symbol": "CACI"},
    {"name": "AMD Investor Relations", "url": "https://ir.amd.com/news-events/press-releases/rss", "category": "company", "company_symbol": "AMD"},
    {"name": "Broadcom Financial News", "url": "https://investors.broadcom.com/financial-information/financial-news-releases", "category": "company", "company_symbol": "AVGO", "format": "index", "article_pattern": r"/news-releases/news-release-details/[^/]+", "requires_original_body": True},
    {"name": "AeroVironment Newsroom", "url": "https://www.avinc.com/feed/", "category": "company", "company_symbol": "AVAV"},
    {"name": "Kratos Newsroom", "url": "https://www.kratosdefense.com/newsroom", "category": "company", "company_symbol": "KTOS", "format": "index", "article_pattern": r"/newsroom/[^/]+", "anchor_title": True, "requires_original_body": True},
    {"name": "Alphabet Investor Relations", "url": "https://abc.xyz/rss/pressrelease.aspx?LanguageId=1", "category": "company", "company_symbol": "GOOG", "format": "alphabet", "requires_original_body": True},
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
        if CACHE_FILE.stat().st_size > MAX_CACHE_BYTES:
            return {}

        with CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    temporary = None
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE_FILE.parent, delete=False) as file:
            temporary = file.name
            json.dump(cache, file, indent=2, sort_keys=True)
        if CACHE_FILE.exists():
            os.chmod(temporary, CACHE_FILE.stat().st_mode & 0o777)
        os.replace(temporary, CACHE_FILE)
    except Exception:
        return
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def get_cached_source(url: str) -> dict | None:
    with CACHE_LOCK:
        cache = load_cache()
    item = cache.get(url)

    if not isinstance(item, dict):
        return None

    fetched_at_epoch = item.get("fetched_at_epoch")

    try:
        if type(fetched_at_epoch) not in (int, float) or not math.isfinite(fetched_at_epoch):
            return None
        age = time.time() - fetched_at_epoch
    except Exception:
        return None

    if age < -60:
        return None
    if item.get("status") == "error":
        retry = item.get("retry_after_epoch")
        if type(retry) not in (int, float) or not math.isfinite(retry) or not fetched_at_epoch <= retry <= fetched_at_epoch + 6 * 3600 or time.time() >= retry:
            return None
    elif age > CACHE_TTL_SECONDS:
        return None
    return item


def set_cached_source(url: str, payload: dict) -> None:
    with CACHE_LOCK:
        cache = load_cache()
        cache[url] = payload
        save_cache(cache)


def fetch_url(url: str, force_refresh: bool = False, *, cache_result: bool = True, binary: bool = False, user_agent: str | None = None) -> dict:
    cached = get_cached_source(url) if not binary else None
    if binary:
        cache_result = False
    if cached and (not force_refresh or cached.get("status") == "error"):
        return {**cached, "cache_hit": True}

    try:
        request = Request(
            url,
            headers={
                "User-Agent": user_agent or USER_AGENT,
                "Accept": "application/pdf" if binary else "application/json, application/rss+xml, application/atom+xml, application/xml, text/xml, text/html",
            },
        )

        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw_bytes = response.read(MAX_FEED_BYTES + 1)
            if len(raw_bytes) > MAX_FEED_BYTES:
                raise ValueError("Publisher response exceeds the size limit")
            raw = raw_bytes if binary else raw_bytes.decode("utf-8", errors="replace")
            final_url = response.geturl()

        payload = {
            "url": url,
            "final_url": final_url,
            "status": "ok",
            "error": "",
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": raw,
        }

        if cache_result:
            set_cached_source(url, payload)
        return payload

    except HTTPError as error:
        retry = 3600 if error.code in (403, 404) else 900 if error.code == 429 else 300
        try:
            retry = min(6 * 3600, max(retry, int(error.headers.get("Retry-After", retry))))
        except (TypeError, ValueError, AttributeError):
            pass
        payload = {
            "url": url,
            "status": "error",
            "error": f"HTTPError {error.code}",
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": "",
            "http_status": error.code,
            "retry_after_epoch": time.time() + retry,
        }
    except Exception as error:
        retry = 300
        payload = {
            "url": url,
            "status": "error",
            "error": type(error).__name__,
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "body": "",
            "retry_after_epoch": time.time() + 300,
        }
    payload["retry_after_epoch"] = payload["fetched_at_epoch"] + retry
    set_cached_source(url, payload)
    return payload


def fetch_source(source: dict, force_refresh: bool = False) -> dict:
    if source.get("format") not in {"palantir", "index", "treasury", "alphabet"}:
        return fetch_url(source["url"], force_refresh)
    cached = get_cached_source(source["url"])
    if cached and (cached.get("status") == "error" or not force_refresh and cached.get("original_profile") == 2):
        return {**cached, "cache_hit": True}
    try:
        from src.intelligence.alphabet_source import attachment_url
        payload = originals.retrieve(source, lambda url: fetch_url(url, force_refresh,
            cache_result=source["format"] == "palantir" and url.startswith(source["url"] + "?"),
            **({"binary": True} if source["format"] == "alphabet" and attachment_url(url) else {})), datetime.now(timezone.utc))
        # Structured release evidence is retained; large index HTML is not duplicated.
        payload = {**payload, "body": ""}
    except (ValueError, TypeError, KeyError) as exc:
        # A structured reader can reject the failed fetch as unusable evidence.
        # Keep that fetch's HTTP status and cooldown instead of shortening it.
        failure = get_cached_source(source["url"])
        if failure and failure.get("status") == "error":
            payload = dict(failure)
        else:
            payload = {"url": source["url"], "status": "error", "error": str(exc)[:160], "body": "",
                       "fetched_at_epoch": time.time(), "fetched_at": now_text(), "cache_hit": False,
                       "retry_after_epoch": time.time() + 300}
    set_cached_source(source["url"], payload)
    return payload


def child_text(item: ET.Element, tag_name: str) -> str:
    for child in list(item):
        local_name = child.tag.split("}")[-1].lower()

        if local_name == tag_name.lower():
            return normalize_text(child.text or "")

    return ""


def parse_rss_items(xml_text: str, source: dict, *, full_titles: bool = False, full_text: bool = False) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    if root.tag.split("}")[-1].lower() not in {"rss", "rdf", "feed"}:
        return []
    items = []

    for item in root.iter():
        kind = item.tag.split("}")[-1].lower()
        if kind not in {"item", "entry"}:
            continue

        title = child_text(item, "title")
        description = child_text(item, "description") or child_text(item, "encoded")
        link = child_text(item, "link")
        published = child_text(item, "pubDate") or child_text(item, "published") or child_text(item, "date")
        if kind == "entry":
            links = [node.attrib.get("href", "") for node in item if node.tag.split("}")[-1] == "link" and node.attrib.get("rel", "alternate") == "alternate"]
            link = links[0] if len(links) == 1 else ""
            description = child_text(item, "summary")
        if full_text:
            for name in (("summary", "content") if kind == "entry" else ("encoded", "description")):
                original = next((node for node in item if node.tag.split("}")[-1].lower() == name and (node.text or len(node))), None)
                if original is not None:
                    description = (original.text or "") + "".join(ET.tostring(node, encoding="unicode") for node in original)
                    break

        if not title:
            continue

        items.append(
            {
                "title": title if full_titles else compact_text(title, 180),
                "description": originals.release_text(description) if full_text else compact_text(description, 280),
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
    items = parse_article_items(payload, source)

    if items:
        return items[:30]
    if source.get("company_symbol") or source.get("category") not in {"market", "technology"}:
        return []

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


def parse_article_items(payload: dict, source: dict, *, full_titles: bool = False, full_text: bool = False) -> list[dict]:
    if source.get("format") in {"palantir", "index", "treasury", "alphabet"}:
        rows = originals.cached_items(payload, source)
    else:
        rows = parse_rss_items(payload.get("body", ""), source, full_titles=full_titles, full_text=full_text)
    if full_text:
        for row in rows:
            row["evidence_scope"] = row.get("evidence_scope") or ("publisher feed excerpt" if row.get("description") else "headline only")
            row["evidence_checked_at"] = row.get("evidence_checked_at", payload.get("fetched_at_epoch"))
            details = payload.get("release_evidence", [])
            for detail in (details[:1] if isinstance(details, list) else []):
                if (isinstance(detail, dict) and detail.get("title") == row["title"] and detail.get("url") == row["link"]
                        and timestamp(detail.get("published")) == timestamp(row["published"])):
                    row.update(description=originals.release_text(detail.get("text", "")), evidence_scope="original release excerpt",
                               evidence_checked_at=detail.get("checked_at_epoch"))
    return rows


def is_original_source(source: dict) -> bool:
    return bool(source.get("company_symbol") or source.get("category") in {"fed", "treasury", "energy", "defense"})


def original_source_for_url(url: str) -> dict | None:
    source = next((row for row in NEWS_SOURCES if row["url"] == url and is_original_source(row)), None)
    if source is None and url == "https://home.treasury.gov/rss/press-releases":
        # Historical proofs retain their configured source identity. This retired
        # endpoint is accepted only when reading evidence, never scheduled to fetch.
        return {"name": "U.S. Treasury", "url": url, "category": "treasury"}
    return source


def describe_source(source: dict, payload, now: datetime) -> dict:
    """Distinguish an unavailable publisher from a healthy, quiet publication feed."""
    row = {"name": source["name"], "symbol": source.get("company_symbol", ""), "status": "limited",
           "checked_at": "", "entries": 0, "dated": 0, "fresh": 0, "undated": 0, "latest_publication": "", "reason": "Missing cached fetch"}
    if not isinstance(payload, dict):
        return row
    fetched = payload.get("fetched_at_epoch")
    if type(fetched) not in (int, float) or not math.isfinite(fetched) or not -60 <= now.timestamp() - fetched <= 6 * 3600:
        return {**row, "reason": "Source observation stale or invalid"}
    row["checked_at"] = datetime.fromtimestamp(fetched, timezone.utc).isoformat()
    if payload.get("status") != "ok":
        reason = str(payload.get("error") or "Failed fetch")[:100]
        retry = payload.get("retry_after_epoch")
        if type(retry) in (int, float) and math.isfinite(retry) and now.timestamp() < retry <= fetched + 6 * 3600:
            reason += "; retry after " + datetime.fromtimestamp(retry, timezone.utc).strftime("%m-%d %H:%M UTC")
        return {**row, "reason": reason}
    if not originals.authorized_response(source, payload):
        return {**row, "reason": "Publisher redirect mismatch"}
    try:
        if not source.get("format"):
            container = ET.fromstring(payload.get("body", ""))
            kind = container.tag.split("}")[-1].lower()
            if kind not in {"rss", "rdf", "feed"} or kind == "rss" and container.find("channel") is None:
                raise ValueError("no dated RSS article candidates; expected a publisher feed")
        items = parse_article_items(payload, source, full_titles=True)[:30]
        row["entries"] = len(items)
        dates = [timestamp(item.get("published")) for item in items]
        valid = [value for value in dates if value and (now - value).total_seconds() >= -60]
        mismatches = sum(not originals.authorized_response(source, {"url": item.get("link", "")}) for item in items)
        row.update(dated=len(valid), undated=len(items) - len(valid),
                   fresh=sum(value is not None and 0 <= (now - value).total_seconds() <= 24 * 3600
                             and originals.authorized_response(source, {"url": item.get("link", "")}) for item, value in zip(items, dates)),
                   latest_publication=max(valid).isoformat() if valid else "")
        row.update(status="limited" if row["undated"] or mismatches else "available",
                   reason=f"{row['undated']} original publication clocks unverified" if row["undated"] else "No fresh dated reports" if not row["fresh"] else "Fresh dated reports available; editorial review still required")
        if mismatches:
            row["reason"] += f"; {mismatches} publisher-link mismatches"
        if row["undated"] and payload.get("publication_problems"):
            row["reason"] += "; " + str(payload["publication_problems"][0])[:90]
        if source.get("format") == "alphabet" and payload.get("publication_problems"):
            row.update(status="limited", reason="Original Alphabet release text unavailable: " + str(payload["publication_problems"][0])[:150])
        if row["undated"] and not source.get("format") and not any(dates):
            root = ET.fromstring(payload.get("body", ""))
            if root.tag.split("}")[-1].lower() == "feed" and any(node.tag.split("}")[-1].lower() == "updated" for node in root.iter()):
                row["reason"] += "; update timestamps do not establish original publication"
        row["reason"] = row["reason"][:240]
    except (ET.ParseError, ValueError, TypeError, KeyError) as exc:
        row["reason"] = "no dated RSS article candidates; invalid publisher response" if isinstance(exc, ET.ParseError) else str(exc)[:150]
    return row


def coverage_summary(rows: list[dict]) -> str:
    available = sum(row["status"] == "available" for row in rows)
    fresh = sum(row["fresh"] for row in rows)
    return f"Original sources: {available}/{len(rows)} available; {len(rows) - available} limited; {fresh} fresh dated reports before editorial selection."


def cached_original_coverage(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cache = load_cache()
    return [describe_source(source, cache.get(source["url"]), now) for source in NEWS_SOURCES if is_original_source(source)]


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

    with ThreadPoolExecutor(max_workers=4) as pool:
        payloads = list(pool.map(lambda source: fetch_source(source, force_refresh), NEWS_SOURCES))
        def read_release(pair):
            source, payload = pair
            result = originals.enrich_feed(source, payload, parse_rss_items,
                lambda url: fetch_url(url, force_refresh, cache_result=False), datetime.now(timezone.utc))
            if result is not payload:
                set_cached_source(source["url"], result)
            return result
        payloads = list(pool.map(read_release, zip(NEWS_SOURCES, payloads)))
    earnings_backup = None
    if any(source.get("format") == "alphabet" for source in NEWS_SOURCES):
        from src.intelligence.alphabet_earnings import refresh, health
        earnings_backup = health(refresh(force_refresh), datetime.now(timezone.utc))
    for source, payload in zip(NEWS_SOURCES, payloads):
        try:
            parsed_items = parse_source_payload(payload, source) if payload.get("status") == "ok" else []
        except (ValueError, TypeError, KeyError):
            parsed_items = []
        health = describe_source(source, payload, datetime.now(timezone.utc)) if is_original_source(source) else None
        status = ("ok" if health["status"] == "available" else "limited") if health else payload.get("status", "unknown")
        problem = health["reason"] if health and health["status"] != "available" else payload.get("error", "")

        source_results.append(
            {
                "name": source.get("name", "Unknown"),
                "category": source.get("category", "market"),
                "status": status,
                "cache_hit": payload.get("cache_hit", False),
                "item_count": len(parsed_items),
                "error": problem,
            }
        )

        if status != "ok":
            errors.append(f"{source.get('name', 'Unknown')}: {problem or 'unknown error'}")
        if health:
            current = datetime.now(timezone.utc)
            parsed_items = [item for item in parsed_items if (published := timestamp(item.get("published"))) is not None
                            and 0 <= (current - published).total_seconds() <= 24 * 3600
                            and originals.authorized_response(source, {"url": item.get("link", "")})]
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
        "earnings_backup": earnings_backup,
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

    backup = context.get("earnings_backup")
    if backup:
        rows = rows[:24] + ["• Alphabet SEC earnings context: " + backup["status"] + " | " + backup["reason"]]
    return "\n".join(rows if backup else rows[:24])


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
