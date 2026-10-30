"""Timestamped Yahoo chart and RSS inputs; no old quote fallback or news cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
from html.parser import HTMLParser
import json
import math
import os
import re
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


UTC = timezone.utc
NY = ZoneInfo("America/New_York")
INDEX_NAMES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^VIX": "VIX"}
TESLA_IR_HOME = "https://ir.tesla.com/"
TESLA_IR_RSS = "https://ir.tesla.com/rss/news-releases.xml"
TESLA_RELEASE_LIMIT = 3
ALIASES = {
    "TSLA": ("tesla",), "NVDA": ("nvidia",), "MSFT": ("microsoft",),
    "AVGO": ("broadcom",), "PLTR": ("palantir",), "AVAV": ("aerovironment",),
    "KTOS": ("kratos",), "CRWD": ("crowdstrike",), "AAPL": ("apple",),
    "AMZN": ("amazon",), "GOOGL": ("alphabet", "google"), "GOOG": ("alphabet", "google"),
    "AMD": ("advanced micro devices",), "META": ("meta",),
    "TSM": ("tsmc", "taiwan semiconductor"), "ASML": ("asml",),
    "NOC": ("northrop grumman",), "LMT": ("lockheed martin",),
    "RTX": ("raytheon", "rtx"), "GD": ("general dynamics",),
    "HII": ("huntington ingalls",), "MU": ("micron",),
    "ORCL": ("oracle",), "ARM": ("arm holdings",), "ON": ("onsemi", "on semiconductor"),
}
OFFICIAL_DOMAINS = {
    "TSLA": ("tesla.com",), "NVDA": ("nvidia.com",), "MSFT": ("microsoft.com",),
    "AVGO": ("broadcom.com",), "PLTR": ("palantir.com",), "AVAV": ("avinc.com",),
    "KTOS": ("kratosdefense.com",), "CRWD": ("crowdstrike.com",),
    "TSM": ("tsmc.com",), "AMD": ("amd.com",), "ASML": ("asml.com",),
    "INTC": ("intel.com", "intc.com"),
    "NOC": ("northropgrumman.com",), "LMT": ("lockheedmartin.com",),
    "RTX": ("rtx.com",), "AMZN": ("amazon.com", "aboutamazon.com"),
    "CACI": ("caci.com",),
    "AAPL": ("apple.com",), "META": ("meta.com",),
    "GOOG": ("google.com", "abc.xyz"), "GOOGL": ("google.com", "abc.xyz"),
}


def company_url(symbol: str, url: str) -> bool:
    parts = urlsplit(safe_url(url))
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == d or host.endswith("." + d)
                                            for d in OFFICIAL_DOMAINS.get(symbol, ()))


def mentions_company(title: str, symbol: str) -> bool:
    # Short tickers such as ON or MU must not match ordinary words in headlines.
    ticker = len(symbol) >= 3 and re.search(r"\b" + re.escape(symbol) + r"\b", title)
    return bool(ticker or any(re.search(r"\b" + re.escape(name) + r"\b", title, re.I)
                              for name in ALIASES.get(symbol, ())))


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


def request_bytes(url: str, *, prefix_bytes: int | None = None, authority_domain: str = "") -> bytes:
    if prefix_bytes is not None and (type(prefix_bytes) is not int or not 1 <= prefix_bytes <= 1_000_000):
        raise ValueError("Invalid bounded excerpt size")
    user_agent = os.getenv("SEC_USER_AGENT", "SmartMoneyAI/1.5 public IPO monitor") if authority_domain == "sec.gov" else "Mozilla/5.0 SmartMoneyAI/1.4"
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json,application/rss+xml,application/atom+xml,text/xml,text/html"})
    with urlopen(request, timeout=10) as response:
        if authority_domain:
            final = urlsplit(response.geturl())
            host = final.hostname or ""
            if final.scheme != "https" or final.username or final.password or final.port not in (None, 443) or not (host == authority_domain or host.endswith("." + authority_domain)):
                raise ValueError("IPO source redirected outside its original authority")
        if urlsplit(url).hostname == "ir.tesla.com":
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.netloc.lower() not in {"ir.tesla.com", "ir.tesla.com:443"}:
                raise ValueError("Official source redirected outside Tesla IR")
        else:
            # A trusted feed cannot acquire company authority through an external redirect.
            for symbol in ("NVDA", "MSFT", "PLTR"):
                if company_url(symbol, url) and not company_url(symbol, response.geturl()):
                    raise ValueError("Official source redirected outside the company domain")
            if urlsplit(url).hostname == "www.businesswire.com":
                final = urlsplit(response.geturl())
                if final.scheme != "https" or final.hostname not in {"www.businesswire.com", "businesswire.com"}:
                    raise ValueError("Release timestamp source redirected outside Business Wire")
        body = response.read(prefix_bytes or 2_000_001)
    if prefix_bytes is None and len(body) > 2_000_000:
        raise ValueError("Source response too large")
    return body


def source_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    return type(exc).__name__


class TeslaReleasePage(HTMLParser):
    """Read Tesla's observed release markup, never its earnings-calendar date."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []
        self.title_parts = []
        self.publications = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag not in self.VOID:
            self.stack.append((tag, classes))
        if tag == "a":
            url = safe_url(urljoin(TESLA_IR_HOME, attrs.get("href", "")))
            parts = urlsplit(url)
            if (parts.scheme == "https" and parts.netloc.lower() in {"ir.tesla.com", "ir.tesla.com:443"}
                    and re.fullmatch(r"/press-release/[a-zA-Z0-9-]+/?", parts.path)
                    and not parts.path.startswith(("/press-release/delivery-consensus-", "/press-release/earnings-consensus-"))):
                url = parts._replace(query="", fragment="").geturl()
                if url not in self.links:
                    self.links.append(url)
        if tag == "time" and any("press-release__date" in item[1] for item in self.stack):
            self.publications.append(timestamp(attrs.get("datetime")))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any("press-release__title" in item[1] for item in self.stack):
            self.title_parts.append(data)


def tesla_page(body: bytes) -> TeslaReleasePage:
    page = TeslaReleasePage()
    page.feed(body.decode("utf-8"))
    page.close()
    return page


def tesla_ir_news(now: datetime, config: dict) -> tuple[list[dict], str, list[str]]:
    """Try public release pages if RSS fails; never promote third-party headlines."""
    try:
        items = parse_feed(request_bytes(TESLA_IR_RSS), ["TSLA"], "Tesla IR", publisher_symbol="TSLA")
        return items, "official RSS available", []
    except Exception as exc:
        rss_error = source_error(exc)

    # Bounded requests to discovered, same-host public release URLs only.
    try:
        links = tesla_page(request_bytes(TESLA_IR_HOME)).links[:TESLA_RELEASE_LIMIT]
        if not links:
            raise ValueError("No public release links found")
    except Exception as exc:
        message = f"Tesla IR: RSS {rss_error}; public release index {source_error(exc)}; company confirmation unavailable"
        return [], "unavailable; TSLA headlines remain a separate source", [message]

    items, issues, checked = [], [], 0
    for url in links:
        try:
            page = tesla_page(request_bytes(url))
            title = clean(" ".join(page.title_parts))
            dates = set(page.publications)
            if not re.search(r"\bTesla\b", title, re.I) or len(dates) != 1 or None in dates:
                raise ValueError("Release title or original publication time missing")
            published = dates.pop()
            checked += 1
            if not 0 <= (now - published).total_seconds() <= config["news_hours"] * 3600:
                continue
            items.append({"symbol": "TSLA", "title": title, "url": url,
                          "published": published.isoformat(), "official": True,
                          "source": "ir.tesla.com", "publisher_symbol": "TSLA"})
        except Exception as exc:
            issues.append(f"Tesla IR release: {source_error(exc)} (unavailable or missing original publication time)")
    if not checked:
        issues.insert(0, f"Tesla IR: RSS {rss_error}; no dated public release could be read; company confirmation unavailable")
    detail = f"official release pages: {checked}/{len(links)} dated pages read (RSS {rss_error})"
    return items, detail, issues


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


def parse_feed(body: bytes, symbols: list[str], feed_name: str, publisher_symbol: str = "") -> list[dict]:
    root = ET.fromstring(body)
    if root.tag.split("}")[-1] not in {"rss", "feed", "RDF"}:
        raise ValueError("Source is not an RSS or Atom feed")
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
            publisher = symbol == publisher_symbol and company_url(symbol, link)
            if publisher_symbol and not publisher:
                continue
            if not publisher and not mentions_company(title, symbol):
                continue
            host = (urlsplit(link).hostname or "").lower()
            official = company_url(symbol, link)
            item = {"symbol": symbol, "title": title, "url": link,
                          "published": published.isoformat(), "official": official,
                          "source": host or feed_name}
            if publisher:
                item["publisher_symbol"] = symbol
            items.append(item)
    return items


def collect_inputs(now: datetime, config: dict, source_status: dict | None = None) -> tuple[dict, list[dict], list[str]]:
    from src.intelligence.special_alert_company_sources import OFFICIAL_FEEDS, official_company_news
    observations, news, issues = {}, [], []
    tasks = [("index", symbol, "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe="") + "?range=1mo&interval=1d")
             for symbol in INDEX_NAMES]
    if config.get("ipo_enabled"):
        tasks.append(("ipo", "AI IPOs", ""))
    for symbol in config["symbols"]:
        tasks.append(("news", symbol + " news", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + quote(symbol, safe="") + "&region=US&lang=en-US"))
    if "TSLA" in config["symbols"]:
        tasks.append(("tesla_ir", "Tesla IR", TESLA_IR_RSS))
    for symbol in config["symbols"]:
        if symbol in OFFICIAL_FEEDS:
            tasks.append(("official", symbol + " official", symbol))

    def fetch(task):
        kind, name, url = task
        try:
            if kind == "ipo":
                from src.intelligence import ipo_monitor
                def request_ipo(url, prefix=False):
                    domain = "sec.gov" if (urlsplit(url).hostname or "").endswith(".sec.gov") else next(row["domain"] for row in ipo_monitor.issuers().values() if ipo_monitor.issuer_url(row, url))
                    return request_bytes(url, prefix_bytes=1_000_000 if prefix else None, authority_domain=domain)
                items, detail, problems = ipo_monitor.collect(now, config, request_ipo)
                return kind, name, items, problems, detail
            if kind == "tesla_ir":
                items, detail, problems = tesla_ir_news(now, config)
                return kind, name, items, problems, detail
            if kind == "official":
                items, detail, problems = official_company_news(url, now, config)
                return kind, name, items, problems, detail
            raw = request_bytes(url)
            if kind == "index":
                row = chart_observation(name, json.loads(raw), now, config)
                return kind, name, row, [], "fresh session quote available"
            items = parse_feed(raw, config["symbols"], name)
            return kind, name, items, [], f"headline feed read; {len(items)} dated matching items"
        except Exception as exc:
            return kind, name, None, [f"{name}: {source_error(exc)} (unavailable or invalid/stale source)"], "unavailable"

    with ThreadPoolExecutor(max_workers=5) as executor:
        for kind, name, result, errors, detail in executor.map(fetch, tasks):
            issues.extend(errors)
            if source_status is not None:
                source_status[name] = detail
            if kind == "index" and result is not None:
                observations[name] = result
            elif result is not None:
                news.extend(result)
    from src.intelligence.hourly_research import approved
    reviewed = approved(now)
    news.extend(value for value in reviewed if value["kind"] == "company")
    if source_status is not None:
        source_status["Hourly Research"] = f"{len(reviewed)} fresh original-source findings approved by AI relevance review"
    return observations, news, issues
