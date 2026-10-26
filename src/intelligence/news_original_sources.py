"""Bounded original-publisher indexes; fetch clocks never become news dates."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
from src.intelligence.special_alert_sources import company_url, timestamp
from src.intelligence.story_analysis import VisibleText, event_type, release_text


MAX_ARTICLES = 30
MAX_DETAIL_PAGES = 3


class ArticleBody(VisibleText):
    """Read identified release bodies, without treating site navigation as news."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.heading_tag, self.heading_parts, self.headings = None, [], []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        if tag == "h1" or "wd_title" in classes:
            self.heading_tag, self.heading_parts = tag, []
        if not self.depth and (tag == "article" or classes & {"wd_news_body", "article-body", "release-body"}):
            self.depth = 1
        elif self.depth and tag not in self.VOID:
            self.depth += 1
        if self.depth:
            super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == self.heading_tag:
            self.headings.append(" ".join("".join(self.heading_parts).split()))
            self.heading_tag = None
        if self.depth and tag not in self.VOID:
            super().handle_endtag(tag)
            self.depth -= 1

    def handle_data(self, data):
        if self.heading_tag:
            self.heading_parts.append(data)
        if self.depth:
            super().handle_data(data)


def article_excerpt(body: str, title: str, published: str) -> str:
    """Bind extra facts to the same complete headline and original publication."""
    expected = timestamp(published)
    if expected is None:
        raise ValueError("Original article needs the admitted feed publication clock")
    parser = ArticleBody()
    parser.feed(body)
    text = release_text("".join(parser.parts))
    if not text:
        raise ValueError("Recognizable original release body unavailable")
    try:
        actual = publication_time(body.encode(), title)
    except ValueError:
        metadata = PublicationPage()
        metadata.feed(body)
        # Some publisher pages omit time metadata. A zoned original RSS clock
        # may still bind an exact heading and the same explicit release date.
        if metadata.dates or 'datePublished' in body or sum(value.casefold() == title.casefold() for value in parser.headings) != 1:
            raise ValueError("Original article identity or publication clock unavailable")
        try:
            original = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            original = parsedate_to_datetime(published)
        month = f"(?:{original:%B}|{original:%b})"
        if not re.search(r"\b" + month + rf"\.?\s+{original.day},\s+{original.year}\b", text):
            raise ValueError("Original article release date does not match its feed")
    else:
        if actual != expected:
            raise ValueError("Original article publication does not match the admitted feed")
    return text


def enrich_feed(source: dict, payload: dict, parse_feed, fetch, now: datetime) -> dict:
    """At most one fresh company release per publisher, during refresh only."""
    if not source.get("company_symbol") or source.get("format") or payload.get("status") != "ok" or payload.get("release_excerpt_schema") == 1:
        return payload
    observed = payload.get("fetched_at_epoch")
    if not authorized_response(source, payload) or type(observed) not in (int, float) or not math.isfinite(observed) or not -60 <= now.timestamp() - observed <= 6 * 3600:
        return payload
    candidates = []
    for row in parse_feed(payload.get("body", ""), source, full_titles=True):
        published = timestamp(row["published"])
        if (published and 0 <= (now - published).total_seconds() <= 24 * 3600
                and company_url(source["company_symbol"], row["link"])
                and event_type(row["title"])[0] in {"acquisition", "divestiture", "contract", "product", "guidance", "earnings"}):
            candidates.append((published, row))
    candidates.sort(key=lambda value: value[0], reverse=True)
    details, issues = [], []
    for _, row in candidates[:1]:
        try:
            detail = fetch(row["link"])
            if detail.get("status") != "ok" or not authorized_response(source, detail):
                raise ValueError(detail.get("error") or "Original release redirect mismatch")
            excerpt = article_excerpt(detail["body"], row["title"], row["published"])
            details.append({"title": row["title"], "url": row["link"], "published": row["published"],
                            "text": excerpt, "checked_at_epoch": detail["fetched_at_epoch"]})
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            issues.append(str(exc)[:160])
    return {**payload, "release_excerpt_schema": 1, "release_evidence": details, "release_evidence_issues": issues}


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
        rows.append({"title": " ".join(title.split()), "link": link, "published": value.get("PressReleaseDate", ""),
                     "description": release_text(value.get("Body", ""))})
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
            try:
                row["description"] = article_excerpt(detail["body"], row["title"], row["published"])
            except ValueError:
                pass
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
                     "description": release_text(item.get("description", "")), "source": source["name"], "category": "company",
                     "evidence_scope": "original release excerpt" if item.get("publication_url") == item["link"] else "publisher feed excerpt"})
    return rows
