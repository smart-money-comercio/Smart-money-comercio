"""Timestamped Yahoo chart and RSS inputs; no old quote fallback or news cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import json
import math
import re
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


UTC = timezone.utc
NY = ZoneInfo("America/New_York")
INDEX_NAMES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^VIX": "VIX"}
ALIASES = {
    "TSLA": ("tesla",), "NVDA": ("nvidia",), "MSFT": ("microsoft",),
    "AVGO": ("broadcom",), "PLTR": ("palantir",), "AVAV": ("aerovironment",),
    "KTOS": ("kratos",), "CRWD": ("crowdstrike",), "AAPL": ("apple",),
    "AMZN": ("amazon",), "GOOGL": ("alphabet", "google"), "GOOG": ("alphabet", "google"),
    "AMD": ("advanced micro devices",), "META": ("meta",),
}
OFFICIAL_DOMAINS = {
    "TSLA": ("tesla.com",), "NVDA": ("nvidia.com",), "MSFT": ("microsoft.com",),
    "AVGO": ("broadcom.com",), "PLTR": ("palantir.com",), "AVAV": ("avinc.com",),
    "KTOS": ("kratosdefense.com",), "CRWD": ("crowdstrike.com",),
}


def finite(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            result = datetime.fromtimestamp(value, UTC)
        else:
            text = str(value or "").strip()
            try:
                result = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                result = parsedate_to_datetime(text)
        return result.astimezone(UTC) if result.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def clean(value, limit=240) -> str:
    value = re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme in {"https", "http"} and parts.hostname and not parts.username and not parts.password:
            return value[:800]
    except ValueError:
        pass
    return ""


def request_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 SmartMoneyAI/1.4", "Accept": "application/json,application/rss+xml,application/atom+xml,text/xml"})
    with urlopen(request, timeout=10) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Source response too large")
    return body


def chart_observation(symbol: str, payload: dict, now: datetime, config: dict) -> dict:
    """Calculate each return from the correct prior session, not range chartPreviousClose."""
    chart = payload.get("chart", {})
    rows = chart.get("result") or []
    if chart.get("error") or not rows:
        raise ValueError("Chart unavailable")
    result = rows[0]
    meta = result.get("meta", {})
    if meta.get("symbol") != symbol:
        raise ValueError("Wrong instrument")
    asof = timestamp(meta.get("regularMarketTime"))
    price = finite(meta.get("regularMarketPrice"))
    if asof is None or price is None or price <= 0:
        raise ValueError("Quote missing price or timestamp")
    age = (now - asof).total_seconds()
    if age < -60 or age > config["max_quote_age"]:
        raise ValueError("Quote stale or from the future")
    session = meta.get("currentTradingPeriod", {}).get("regular", {})
    start, end = timestamp(session.get("start")), timestamp(session.get("end"))
    if start is None or end is None or end <= start:
        raise ValueError("Session hours unavailable")
    # The provider's session dates handle holidays, early closes and US DST.
    if not (start <= now <= end + timedelta(minutes=20)):
        raise ValueError("Outside the regular session and closing check window")
    session_date = start.astimezone(NY).date()
    if asof.astimezone(NY).date() != session_date or not start <= asof <= end:
        raise ValueError("Quote does not belong to this session")
    bars = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    prior_by_date = {}
    prior_dates = set()
    for epoch, close in zip(result.get("timestamp", []), bars):
        when, value = timestamp(epoch), finite(close)
        if when is not None:
            day = when.astimezone(NY).date()
            if day < session_date:
                prior_dates.add(day)
                if value is not None and value > 0:
                    prior_by_date[day] = value
    if prior_dates and max(prior_dates) not in prior_by_date:
        raise ValueError("Latest prior session close is missing")
    days = sorted(prior_by_date)
    if not days:
        raise ValueError("Previous session close unavailable")
    previous = prior_by_date[days[-1]]
    if (session_date - days[-1]).days > 4:
        raise ValueError("Previous session history too old")
    change = 100 * (price / previous - 1)
    two_day = prior_change = None
    if len(days) >= 2 and sorted(prior_dates)[-2] == days[-2]:
        before_previous = prior_by_date[days[-2]]
        two_day = 100 * (price / before_previous - 1)
        prior_change = 100 * (previous / before_previous - 1)
    return {"symbol": symbol, "name": INDEX_NAMES[symbol], "price": price,
            "change": change, "two_day": two_day, "prior_change": prior_change,
            "asof": asof.isoformat(), "session_date": session_date.isoformat(),
            "previous_date": days[-1].isoformat(),
            "source": "Yahoo Finance chart (may be delayed)",
            "url": "https://finance.yahoo.com/quote/" + quote(symbol, safe="") + "/"}


def parse_feed(body: bytes, symbols: list[str], feed_name: str) -> list[dict]:
    root = ET.fromstring(body)
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        fields = {}
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "link":
                # Atom link can be in href; do not use an enclosure as the article link.
                if child.get("rel", "alternate") == "alternate":
                    fields["link"] = child.get("href") or child.text or ""
            elif tag in {"title", "summary", "description", "pubDate", "published", "updated"}:
                fields[tag] = "".join(child.itertext())
        title = clean(fields.get("title"))
        link = safe_url(str(fields.get("link", "")).strip())
        published = timestamp(fields.get("pubDate") or fields.get("published"))
        if not title or not link or published is None:
            continue
        for symbol in symbols:
            terms = (symbol.lower(),) + ALIASES.get(symbol, ())
            if not any(re.search(r"\b" + re.escape(term) + r"\b", title, re.I) for term in terms):
                continue
            host = (urlsplit(link).hostname or "").lower()
            official = any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS.get(symbol, ()))
            items.append({"symbol": symbol, "title": title, "url": link,
                          "published": published.isoformat(), "official": official,
                          "source": host or feed_name})
    return items


def collect_inputs(now: datetime, config: dict) -> tuple[dict, list[dict], list[str]]:
    observations, news, issues = {}, [], []
    tasks = [("index", symbol, "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + "?range=1mo&interval=1d")
             for symbol in INDEX_NAMES]
    for symbol in config["symbols"]:
        tasks.append(("news", symbol + " news", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + quote(symbol, safe="") + "&region=US&lang=en-US"))
    if "TSLA" in config["symbols"]:
        tasks.append(("news", "Tesla IR", "https://ir.tesla.com/rss/news-releases.xml"))

    def fetch(task):
        kind, name, url = task
        try:
            raw = request_bytes(url)
            if kind == "index":
                return kind, name, chart_observation(name, json.loads(raw), now, config), ""
            return kind, name, parse_feed(raw, config["symbols"], name), ""
        except Exception as exc:
            return kind, name, None, f"{name}: {type(exc).__name__} (unavailable or invalid/stale source)"

    with ThreadPoolExecutor(max_workers=5) as executor:
        for kind, name, result, error in executor.map(fetch, tasks):
            if error:
                issues.append(error)
            elif kind == "index":
                observations[name] = result
            else:
                news.extend(result)
    return observations, news, issues
