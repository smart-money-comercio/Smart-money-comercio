"""Bounded original-publisher indexes; fetch clocks never become news dates."""

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import hashlib
import json
import math
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
from src.intelligence.special_alert_sources import company_url, timestamp
from src.intelligence.story_analysis import VisibleText, release_text
from src.intelligence import publisher_publication as publication


MAX_ARTICLES = 30
MAX_DETAIL_PAGES = 3


class ArticleBody(VisibleText):
    """Read identified release bodies, without treating site navigation as news."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, publisher="", url=""):
        super().__init__()
        self.publisher = publisher
        parts = urlsplit(url)
        self.kratos = (publisher in {"KTOS", "Kratos Newsroom"} and parts.hostname == "www.kratosdefense.com"
                       and re.fullmatch(r"/newsroom/[^/]+/?", parts.path) is not None)
        self.alphabet = publisher in {"GOOG", "GOOGL", "Alphabet Investor Relations"} and parts.hostname in {"abc.xyz", "www.abc.xyz"}
        self.depth = 0
        self.heading_tag, self.heading_parts, self.headings = None, [], []
        self.date_depth, self.date_parts = 0, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if classes & {"article-date", "wd_date"} or self.alphabet and "evergreen-news-date-text" in classes:
            self.date_depth = 1
        elif self.date_depth and tag not in self.VOID:
            self.date_depth += 1
        if tag in {"h1", "h2", "h3"} or "wd_title" in classes:
            self.heading_tag, self.heading_parts = tag, []
        fed_body = (self.publisher == "Federal Reserve" and tag == "div" and
                    (attrs.get("id") in {"article", "article-body"} or
                     {"col-xs-12", "col-sm-8", "col-md-8"} <= classes))
        treasury = self.publisher == "U.S. Treasury"
        treasury_body = treasury and "field--name-field-news-body" in classes
        kratos = self.kratos
        kratos_body = kratos and tag == "section" and "wysiwyg-section" in classes
        alphabet_body = self.alphabet and tag == "div" and "evergreen-news-body" in classes
        if not self.depth and (tag == "article" and not treasury and not kratos or classes & {"wd_news_body", "article-body", "release-body"} or fed_body or treasury_body or kratos_body or alphabet_body):
            self.depth = 1
        elif self.depth and tag not in self.VOID:
            self.depth += 1
        if self.depth:
            super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.date_depth and tag not in self.VOID:
            self.date_depth -= 1
        if tag == self.heading_tag:
            self.headings.append(" ".join("".join(self.heading_parts).split()))
            self.heading_tag = None
        if self.depth and tag not in self.VOID:
            super().handle_endtag(tag)
            self.depth -= 1

    def handle_data(self, data):
        if self.date_depth:
            self.date_parts.append(data)
        if self.heading_tag:
            self.heading_parts.append(data)
        if self.depth:
            super().handle_data(data)


def article_excerpt(body: str, title: str, published: str, *, publisher: str = "", url: str = "") -> str:
    """Bind extra facts to the same complete headline and original publication."""
    expected = timestamp(published)
    if expected is None:
        raise ValueError("Original article needs the admitted feed publication clock")
    parser = ArticleBody(publisher, url)
    parser.feed(body)
    text = release_text("".join(parser.parts))
    if not text:
        raise ValueError("Recognizable original release body unavailable")
    from src.intelligence.policy_analysis import is_fomc_statement, release_clock
    fed_statement = is_fomc_statement({"source": publisher, "title": title})
    if fed_statement and (sum(value.casefold() == title.casefold() for value in parser.headings) != 1
                          or release_clock(text) != expected):
        raise ValueError("Original Fed statement title or release clock does not match its feed")
    try:
        actual = (publication.treasury_clock(body, title) if publisher == "U.S. Treasury"
                  else publication_time(body.encode(), title, url=url))
    except ValueError:
        if publisher == "U.S. Treasury":
            raise
        metadata = PublicationPage()
        metadata.feed(body)
        # Some publisher pages omit time metadata. A zoned original RSS clock
        # may still bind an exact heading and the same explicit release date.
        if metadata.dates or 'datePublished' in body or sum(value.casefold() == title.casefold() for value in parser.headings) != 1:
            raise ValueError("Original article identity or publication clock unavailable")
        if fed_statement:
            return text
        try:
            original = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            original = parsedate_to_datetime(published)
        month = f"(?:{original:%B}|{original:%b})"
        date_text = " ".join(parser.date_parts) if parser.date_parts else text
        if not re.search(r"\b" + month + rf"\.?\s+{original.day},\s+{original.year}\b", date_text):
            raise ValueError("Original article release date does not match its feed")
    else:
        if actual != expected:
            raise ValueError("Original article publication does not match the admitted feed")
    return text


def enrich_feed(source: dict, payload: dict, parse_feed, fetch, now: datetime) -> dict:
    """At most one fresh company release or Fed statement during refresh only."""
    fed = source.get("name") == "Federal Reserve" and source.get("category") == "fed"
    if (not source.get("company_symbol") and not fed) or source.get("format") or payload.get("status") != "ok" or payload.get("release_excerpt_schema") == 1:
        return payload
    observed = payload.get("fetched_at_epoch")
    if not authorized_response(source, payload) or type(observed) not in (int, float) or not math.isfinite(observed) or not -60 <= now.timestamp() - observed <= 6 * 3600:
        return payload
    candidates = []
    for row in parse_feed(payload.get("body", ""), source, full_titles=True):
        published = timestamp(row["published"])
        from src.intelligence.policy_analysis import is_fomc_statement
        allowed = (is_fomc_statement({"source": source["name"], "title": row["title"]})
                   and authorized_response(source, {"url": row["link"]})) if fed else company_url(source["company_symbol"], row["link"])
        if (published and 0 <= (now - published).total_seconds() <= 24 * 3600
                and allowed):
            candidates.append((published, row))
    candidates.sort(key=lambda value: value[0], reverse=True)
    if source.get("requires_original_body") and source.get("company_symbol"):
        from src.intelligence.news_editor import materiality
        def material(row):
            return bool(materiality({"title": row[1]["title"], "kind":"company", "symbols":[source["company_symbol"]],
                                     "official":True,"source":source["name"],"publisher_symbol":source["company_symbol"],"url":row[1]["link"]}))
        # Keep the single-page budget for a material release when a newer
        # community or calendar notice would otherwise consume that read.
        candidates.sort(key=lambda value: not material(value))
    details, issues = [], []
    for _, row in candidates[:1]:
        try:
            detail = fetch(row["link"])
            if detail.get("status") != "ok" or not authorized_response(source, detail):
                raise ValueError(detail.get("error") or "Original release redirect mismatch")
            excerpt = article_excerpt(detail["body"], row["title"], row["published"], publisher=source["name"], url=row["link"])
            details.append({"title": row["title"], "url": row["link"], "published": row["published"],
                            "text": excerpt, "checked_at_epoch": detail["fetched_at_epoch"]})
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            issues.append(str(exc)[:160])
    return {**payload, "release_excerpt_schema": 1, "release_evidence": details, "release_evidence_issues": issues}


class ReleaseLinks(HTMLParser):
    def __init__(self, base, pattern, anchor_title=False):
        super().__init__(convert_charrefs=True)
        self.base, self.pattern = base, pattern
        self.anchor_title = anchor_title
        self.rows, self.current = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = urljoin(self.base, dict(attrs).get("href", ""))
            self.current = [url, [], dict(attrs).get("title", "") if self.anchor_title else ""] if re.fullmatch(self.pattern, urlsplit(url).path) else None

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            url, parts, supplied_title = self.current
            title = " ".join((supplied_title or " ".join(parts)).split())
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
        if source.get("format") == "alphabet":
            from src.intelligence.alphabet_source import FEED, release_url
            return url == FEED or release_url(url)
        symbol = source.get("company_symbol")
        if symbol:
            return company_url(symbol, url)
        expected = urlsplit(source["url"]).hostname
        return parts.hostname == expected
    except (ValueError, TypeError):
        return False


def indexed_items(body: str, source: dict) -> list[dict]:
    parser = ReleaseLinks(source["url"], source["article_pattern"], source.get("anchor_title", False))
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
        body = value.get("Body", "")
        row = {"title": " ".join(title.split()), "link": link, "published": value.get("PressReleaseDate", ""),
               "description": release_text(body)}
        try:
            row["clock_reference"] = publication.linked_wire(body) if isinstance(body, str) else ""
        except ValueError as exc:
            row["clock_reference_error"] = str(exc)
        rows.append(row)
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
    if source["format"] == "alphabet":
        from src.intelligence.alphabet_source import retrieve as alphabet_retrieve
        return alphabet_retrieve(source, fetch, now)
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
        rows = publication.treasury_items(payload["body"]) if source["format"] == "treasury" else indexed_items(payload["body"], source)
        if not rows:
            raise ValueError("Publisher index has no recognizable release links")
        candidates = ([row for row in rows if recent_hint(row["published"], now)]
                      if source["format"] == "treasury" else rows)
    rows = rows[:MAX_ARTICLES]
    problems = []
    for row in candidates[:MAX_DETAIL_PAGES]:
        try:
            if row.get("clock_reference_error"):
                raise ValueError(row["clock_reference_error"])
            clock_url = row.get("clock_reference") or row["link"]
            detail = fetch(clock_url)
            if detail.get("status") != "ok":
                raise ValueError(detail.get("error") or "Release page unavailable")
            wire = bool(row.get("clock_reference"))
            if wire and not publication.matching_wire(clock_url, detail.get("final_url", detail.get("url", clock_url))):
                raise ValueError("Publication page redirected outside the issuer-linked wire release")
            if not wire and not authorized_response(source, detail):
                raise ValueError("Release page redirected outside the issuer")
            if source["format"] == "treasury":
                if detail.get("final_url", detail.get("url", row["link"])).rstrip("/") != row["link"].rstrip("/"):
                    raise ValueError("Original Treasury release redirect does not match its listing")
                excerpt = article_excerpt(detail["body"], row["title"], row["published"], publisher=source["name"])
                row.update(description=excerpt, publication_url=row["link"], evidence_checked_at=detail["fetched_at_epoch"])
                continue
            published = publication_time(detail["body"].encode(), row["title"], url=row["link"])
            row["published"] = published.isoformat()
            row["publication_url"] = clock_url
            row["evidence_checked_at"] = detail["fetched_at_epoch"]
            try:
                if not wire:
                    row["description"] = article_excerpt(detail["body"], row["title"], row["published"], publisher=source["name"], url=row["link"])
                    row["release_body_verified"] = True
            except ValueError as exc:
                if source.get("requires_original_body"):
                    problems.append(str(exc)[:160])
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            problems.append(str(exc)[:160])
            if source["format"] == "treasury":
                row["published"] = ""
    return {**payload, "url": source["url"], "final_url": source["url"], "original_profile": 2,
            "articles": rows, "publication_problems": list(dict.fromkeys(problems))[:3]}


def cached_items(payload: dict, source: dict) -> list[dict]:
    if type(payload.get("original_profile")) is not int or payload.get("original_profile") not in (1, 2) or not isinstance(payload.get("articles"), list):
        raise ValueError("Publisher index has not been parsed by the original-source reader")
    rows = []
    for item in payload["articles"][:MAX_ARTICLES]:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not isinstance(item.get("link"), str):
            continue
        if not authorized_response(source, {"url": item["link"]}):
            continue
        required = source.get("requires_original_body") is True
        body_verified = not required or item.get("release_body_verified") is True
        if source.get("format") == "alphabet" and body_verified:
            from src.intelligence.alphabet_source import document_reference
            body_verified = (document_reference(item["link"], item.get("document_url", ""))
                             and item.get("document_sha256") == hashlib.sha256(release_text(item.get("description", "")).encode()).hexdigest())
        rows.append({"title": item["title"], "link": item["link"], "published": item.get("published", ""),
                     "description": release_text(item.get("description", "")) if body_verified else "", "source": source["name"], "category": source["category"],
                     **({"publication_url": item["publication_url"]} if item.get("publication_url") else {}),
                     **({"evidence_checked_at": item["evidence_checked_at"]} if "evidence_checked_at" in item else {}),
                     **({"document_url": item["document_url"]} if body_verified and item.get("document_url") else {}),
                     **({"requires_original_body": True} if source.get("format") == "treasury" or required else {}),
                     "evidence_scope": "headline only" if not body_verified else "original release excerpt" if item.get("publication_url") == item["link"] else "publisher feed excerpt"})
    return rows
