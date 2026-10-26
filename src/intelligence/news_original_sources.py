"""Bounded original-publisher indexes; fetch clocks never become news dates."""

from datetime import datetime, timedelta
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.special_alert_company_sources import publication_time
from src.intelligence.special_alert_sources import company_url, timestamp


MAX_ARTICLES = 30
MAX_DETAIL_PAGES = 3


class ReleaseLinks(HTMLParser):
    def __init__(self, base, pattern):
        super().__init__(convert_charrefs=True)
        self.base, self.pattern = base, pattern
        self.rows, self.current = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = urljoin(self.base, dict(attrs).get("href", ""))
            self.current = [url, []] if re.fullmatch(self.pattern, urlsplit(url).path) else None

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            url, parts = self.current
            title = " ".join(" ".join(parts).split())
            if title:
                self.rows.append({"title": title, "link": url, "published": ""})
            self.current = None


def authorized_response(source: dict, payload: dict) -> bool:
    """Redirects must retain the configured issuer or agency authority."""
    url = payload.get("final_url", payload.get("url", source["url"]))
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            return False
        symbol = source.get("company_symbol")
        if symbol:
            return company_url(symbol, url)
        expected = urlsplit(source["url"]).hostname
        return parts.hostname == expected
    except (ValueError, TypeError):
        return False


def indexed_items(body: str, source: dict) -> list[dict]:
    parser = ReleaseLinks(source["url"], source["article_pattern"])
    parser.feed(body)
    unique = {}
    for row in parser.rows:
        if company_url(source["company_symbol"], row["link"]):
            previous = unique.get(row["link"])
            if previous is None or len(row["title"]) > len(previous["title"]):
                unique[row["link"]] = row
    return list(unique.values())[:MAX_DETAIL_PAGES]


def service_items(body: str, source: dict) -> list[dict]:
    response = json.loads(body)
    if not isinstance(response, dict):
        raise ValueError("Original release service is not an object")
    values = response.get("GetPressReleaseListResult")
    if not isinstance(values, list):
        raise ValueError("Original release service has no release list")
    rows = []
    for value in values[:MAX_ARTICLES]:
        if not isinstance(value, dict):
            continue
        title = value.get("Headline")
        link = urljoin("https://investors.palantir.com/", str(value.get("LinkToDetailPage") or ""))
        if not isinstance(title, str) or not title.strip() or not company_url("PLTR", link) or "/news-details/" not in urlsplit(link).path:
            continue
        # A naive service date remains naive until the exact issuer page verifies it.
        rows.append({"title": " ".join(title.split()), "link": link, "published": value.get("PressReleaseDate", "")})
    return rows


def recent_hint(value: str, now: datetime) -> bool:
    parsed = timestamp(value)
    if parsed is not None:
        return -60 <= (now - parsed).total_seconds() <= 24 * 3600
    try:
        day = datetime.strptime(value, "%m/%d/%Y %H:%M:%S").date()
        # Date hints only bound requests. They are never admitted publication clocks.
        return now.date() - timedelta(days=2) <= day <= now.date() + timedelta(days=1)
    except (ValueError, TypeError):
        return False


def retrieve(source: dict, fetch, now: datetime) -> dict:
    """Read a public index and at most three exact release pages."""
    if source["format"] == "palantir":
        years = {now.year, (now - timedelta(hours=24)).year}
        rows, responses = [], []
        for year in sorted(years, reverse=True):
            url = source["url"] + f"?languageId=1&bodyType=1&year={year}&includeTags=true&pressReleaseDateFilter=1"
            payload = fetch(url)
            if payload.get("status") != "ok" or not authorized_response(source, payload):
                return {**payload, "status": "error", "error": payload.get("error") or "Publisher redirect mismatch"}
            rows.extend(service_items(payload["body"], source))
            responses.append(payload)
        payload = min(responses, key=lambda row: row["fetched_at_epoch"])
        candidates = [row for row in rows if timestamp(row["published"]) is None and recent_hint(row["published"], now)]
    else:
        payload = fetch(source["url"])
        if payload.get("status") != "ok" or not authorized_response(source, payload):
            return {**payload, "status": "error", "error": payload.get("error") or "Publisher redirect mismatch"}
        rows = indexed_items(payload["body"], source)
        if not rows:
            raise ValueError("Publisher index has no recognizable release links")
        candidates = rows
    rows = rows[:MAX_ARTICLES]
    problems = []
    for row in candidates[:MAX_DETAIL_PAGES]:
        try:
            detail = fetch(row["link"])
            if detail.get("status") != "ok":
                raise ValueError(detail.get("error") or "Release page unavailable")
            if not authorized_response(source, detail):
                raise ValueError("Release page redirected outside the issuer")
            published = publication_time(detail["body"].encode(), row["title"])
            row["published"] = published.isoformat()
            row["publication_url"] = row["link"]
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            problems.append(str(exc)[:160])
    return {**payload, "url": source["url"], "final_url": source["url"], "original_profile": 1,
            "articles": rows, "publication_problems": list(dict.fromkeys(problems))[:3]}


def cached_items(payload: dict, source: dict) -> list[dict]:
    if payload.get("original_profile") != 1 or not isinstance(payload.get("articles"), list):
        raise ValueError("Publisher index has not been parsed by the original-source reader")
    rows = []
    for item in payload["articles"][:MAX_ARTICLES]:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not isinstance(item.get("link"), str):
            continue
        if not company_url(source["company_symbol"], item["link"]):
            continue
        rows.append({"title": item["title"], "link": item["link"], "published": item.get("published", ""),
                     "description": "", "source": source["name"], "category": "company"})
    return rows
