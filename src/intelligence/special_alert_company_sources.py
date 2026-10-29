"""Verified publisher feeds and Palantir's public release service."""

from __future__ import annotations

from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence import special_alert_sources as sources
from src.intelligence.special_alert_sources import (
    NY, clean, company_url, parse_feed, source_error, timestamp,
)


OFFICIAL_FEEDS = {
    "NVDA": "https://nvidianews.nvidia.com/releases.xml",
    "MSFT": "https://blogs.microsoft.com/feed/",
    # This is the public service used by the investor site's /bundle.js.
    "PLTR": "https://investors.palantir.com/feed/PressRelease.svc/GetPressReleaseList",
}


class PublicationPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts, self.current = [], None
        self.title, self.dates = "", []
        self.headings, self.heading_parts = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.current = []
        if tag == "h1":
            self.heading_parts = []
        if tag == "meta":
            name = attrs.get("property") or attrs.get("name")
            if name == "og:title":
                self.title = clean(attrs.get("content"), 1001)
            if name == "article:published_time":
                self.dates.append(timestamp(attrs.get("content")))

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)
        if self.heading_parts is not None:
            self.heading_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None
        if tag == "h1" and self.heading_parts is not None:
            self.headings.append(clean("".join(self.heading_parts), 1001))
            self.heading_parts = None


def publication_time(body: bytes, title: str, *, url: str = "") -> datetime:
    """Require an original, zoned publication time for the same release title."""
    page = PublicationPage()
    page.feed(body.decode("utf-8"))
    page.close()
    dates = set(page.dates) if page.title.casefold() == clean(title, 1001).casefold() else set()
    parts = urlsplit(url)
    kratos_url = (parts.scheme == "https" and parts.hostname == "www.kratosdefense.com"
                  and not parts.username and not parts.password and parts.port in (None, 443)
                  and not parts.query and not parts.fragment and re.fullmatch(r"/newsroom/[^/]+/?", parts.path))
    kratos = (kratos_url
              and page.headings.count(clean(title, 1001)) == 1
              and page.title == clean(title + " | Kratos Defense", 1001))

    def walk(value, depth=0):
        if depth > 20:
            return
        if isinstance(value, dict):
            if (clean(value.get("headline"), 1001).casefold() == clean(title, 1001).casefold() and "datePublished" in value
                    and not (kratos_url and value.get("@type") == "WebPage")):
                dates.add(timestamp(value["datePublished"]))
            if (kratos and value.get("@type") == "WebPage" and value.get("name") == page.title
                    and value.get("@id") == url and value.get("url") == url and "datePublished" in value):
                dates.update(page.dates)
                dates.add(timestamp(value["datePublished"]))
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    for script in page.scripts:
        try:
            walk(json.loads(script))
        except ValueError:
            continue
    if len(dates) != 1 or None in dates:
        raise ValueError("Original release publication timezone unavailable or ambiguous")
    return dates.pop()


def palantir_news(now: datetime, config: dict) -> tuple[list[dict], str, list[str]]:
    """Use original release times; the service's naive dates only select candidates."""
    years = {now.astimezone(NY).year, (now - timedelta(hours=config["news_hours"])).astimezone(NY).year}
    rows = []
    for year in sorted(years, reverse=True):
        url = OFFICIAL_FEEDS["PLTR"] + f"?languageId=1&bodyType=1&year={year}&includeTags=true&pressReleaseDateFilter=1"
        values = json.loads(sources.request_bytes(url)).get("GetPressReleaseListResult")
        if not isinstance(values, list):
            raise ValueError("Palantir release service has no release list")
        rows.extend(value for value in values if isinstance(value, dict))
    candidates, dated_rows = [], 0
    today = now.astimezone(NY).date()
    earliest = (now - timedelta(hours=config["news_hours"])).astimezone(NY).date() - timedelta(days=1)
    for row in rows:
        raw_date = row.get("PressReleaseDate", "")
        published = timestamp(raw_date)
        try:
            day = published.astimezone(NY).date() if published else datetime.strptime(raw_date, "%m/%d/%Y %H:%M:%S").date()
        except (ValueError, TypeError):
            continue
        dated_rows += 1
        if earliest <= day <= today + timedelta(days=1):
            candidates.append((day, row, published))
    if rows and not dated_rows:
        raise ValueError("Palantir release index dates unavailable")
    candidates.sort(key=lambda item: item[0], reverse=True)
    items, issues = [], []
    for _, row, published in candidates[:3]:
        try:
            title = clean(row.get("Headline"))
            url = urljoin("https://investors.palantir.com/", str(row.get("LinkToDetailPage") or ""))
            if not title or not company_url("PLTR", url) or "/news-details/" not in url:
                raise ValueError("Palantir release identity unavailable")
            publication_url = ""
            if published is None:
                # The IR service carries the wire's release identifier in its source links.
                # It is only used to locate the exact release and verify its original time.
                ids = set(re.findall(r"newsitemid=(\d{14})(?:&|\b)", str(row.get("Body", ""))))
                if len(ids) != 1:
                    raise ValueError("Original release publication timezone unavailable")
                publication_url = "https://www.businesswire.com/news/home/" + ids.pop() + "/en/"
                published = publication_time(sources.request_bytes(publication_url), title)
            if not 0 <= (now - published).total_seconds() <= config["news_hours"] * 3600:
                continue
            item = {"symbol": "PLTR", "title": title, "url": url.removesuffix("/default.aspx"),
                    "published": published.isoformat(), "official": True,
                    "source": "investors.palantir.com", "publisher_symbol": "PLTR"}
            if publication_url:
                item["publication_url"] = publication_url
            items.append(item)
        except Exception as exc:
            issues.append("PLTR official release: " + source_error(exc) + " (original publication time not verified)")
    detail = f"official release index read; {len(items)} fresh verified releases"
    if issues:
        detail += "; some publication times unavailable"
    return items, detail, issues


def official_company_news(symbol: str, now: datetime, config: dict) -> tuple[list[dict], str, list[str]]:
    try:
        if symbol == "PLTR":
            return palantir_news(now, config)
        items = parse_feed(sources.request_bytes(OFFICIAL_FEEDS[symbol]), [symbol], symbol + " official", publisher_symbol=symbol)
        fresh = [item for item in items if 0 <= (now - timestamp(item["published"])).total_seconds() <= config["news_hours"] * 3600]
        return fresh, f"official feed read; {len(items)} dated items / {len(fresh)} fresh", []
    except Exception as exc:
        return [], "unavailable; headline source remains separate", [symbol + " official: " + source_error(exc) + "; confirmation source unavailable"]
