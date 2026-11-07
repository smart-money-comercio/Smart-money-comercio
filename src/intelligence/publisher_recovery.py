"""Bounded corporate newsroom reads with article-specific original clocks."""

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.special_alert_company_sources import PublicationPage
from src.intelligence.story_analysis import release_text


SOURCES = {
    "ETN": ("https://www.eaton.com/us/en-us/company/news-insights.html", "www.eaton.com",
            r"/us/en-us/company/news-insights/news-releases/20\d{2}/[A-Za-z0-9_-]+\.html"),
    "CRWD": ("https://www.crowdstrike.com/en-us/press-releases/", "www.crowdstrike.com",
             r"/en-us/press-releases/[a-z0-9-]+/"),
}
MAX_DETAILS = 3


def heading_name(symbol, value):
    # The corporate template adds this exact site suffix to metadata titles.
    return value.removesuffix(" | CrowdStrike") if symbol == "CRWD" and isinstance(value, str) else value


def article_url(symbol, url):
    try:
        parts = urlsplit(url)
        route = SOURCES[symbol]
        return (parts.scheme == "https" and parts.hostname == route[1] and parts.port in (None, 443)
                and not parts.username and not parts.password and not parts.query and not parts.fragment
                and re.fullmatch(route[2], parts.path) is not None)
    except (ValueError, TypeError, KeyError):
        return False


def original_clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Original publication needs an explicit time and timezone")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class Links(HTMLParser):
    def __init__(self, symbol):
        super().__init__(convert_charrefs=True)
        self.symbol, self.urls = symbol, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = urljoin(SOURCES[self.symbol][0], dict(attrs).get("href", ""))
            if article_url(self.symbol, url) and url not in self.urls and len(self.urls) < 30:
                self.urls.append(url)


class Page(PublicationPage):
    def __init__(self):
        super().__init__()
        self.canonicals, self.urls = [], []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))
        if tag == "meta" and (attrs.get("property") or attrs.get("name")) == "og:url":
            self.urls.append(attrs.get("content", ""))


def objects(value, depth=0):
    if depth > 16:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child, depth+1)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child, depth+1)


def page_article(symbol, url, body, now, observed):
    from src.intelligence.news_original_sources import ArticleBody
    if not article_url(symbol, url) or not isinstance(body, str) or len(body.encode()) > 2_000_000:
        raise ValueError("Corporate release URL or response is outside its bounded reader")
    page = Page(); page.feed(body)
    if len(page.headings) != 1 or not 15 <= len(page.headings[0]) <= 1000:
        raise ValueError("Corporate release needs one complete original headline")
    title = page.headings[0]
    if not page.urls or set(page.urls) != {url} or page.canonicals and set(page.canonicals) != {url}:
        raise ValueError("Corporate release canonical identity does not match its discovered URL")
    metadata = []
    for script in page.scripts:
        try:
            for node in objects(json.loads(script)):
                if symbol == "ETN" and node.get("@type") == "Article":
                    identity = node.get("mainEntityOfPage", {})
                    identity = identity.get("@id") if isinstance(identity, dict) else identity
                    if isinstance(identity, str) and identity.startswith("www.eaton.com/"):
                        identity = "https://" + identity
                    if identity == url and node.get("headline") == title and page.title == title:
                        metadata.append({"identity": identity, "name": title, "clock": node.get("datePublished")})
                elif (symbol == "CRWD" and node.get("@type") == "WebPage" and node.get("@id") == url+"#webpage"
                      and node.get("url", url) == url and node.get("name") == page.title
                      and (title == heading_name(symbol, page.title) or title.startswith(heading_name(symbol, page.title)+" "))):
                    metadata.append({"identity": url+"#webpage", "name": page.title, "clock": node.get("datePublished")})
        except (ValueError, TypeError, RecursionError):
            continue
    if not metadata or len({json.dumps(value, sort_keys=True) for value in metadata}) != 1:
        raise ValueError("Corporate release original publication metadata is missing or ambiguous")
    clock = original_clock(metadata[0]["clock"])
    if page.dates and (None in page.dates or set(page.dates) != {clock}):
        raise ValueError("Corporate release original publication fields disagree")
    if not clock <= now or type(observed) not in (int, float) or not math.isfinite(observed) or not -60 <= now.timestamp()-observed <= 21600 or observed < clock.timestamp()-60:
        raise ValueError("Corporate release publication or observation clock is future-dated or stale")
    parser = ArticleBody(symbol, url); parser.feed(body)
    text = release_text("".join(parser.parts))
    if parser.corporate_roots != 1 or not 80 <= len(text) <= 6000:
        raise ValueError("Corporate release needs one identified original article body")
    # Preserve a source-native original clock, not a fetch time or CMS update.
    row = {"title": title, "link": url, "published": clock.isoformat(), "description": text,
           "publication_url": url, "evidence_checked_at": observed, "release_body_verified": True}
    row["corporate_evidence"] = {"schema": 1, "symbol": symbol, "url": url, "title": title,
        "published": row["published"], "observed": observed, "metadata": metadata[0],
        "scope": "original release excerpt", "sha256": sha256(text.encode()).hexdigest()}
    checked_article(symbol, row, now)
    return row


def checked_article(symbol, row, now=None):
    proof = row.get("corporate_evidence", {})
    text, url, title = row.get("description"), row.get("link"), row.get("title")
    meta = proof.get("metadata", {})
    if (proof.get("schema") != 1 or proof.get("symbol") != symbol or not article_url(symbol, url)
            or proof.get("url") != url or proof.get("title") != title or not isinstance(title, str)
            or not 15 <= len(title) <= 1000 or not isinstance(text, str) or not 80 <= len(text) <= 6000
            or proof.get("sha256") != sha256(text.encode()).hexdigest() or proof.get("scope") != "original release excerpt"
            or proof.get("published") != row.get("published") or proof.get("observed") != row.get("evidence_checked_at")
            or row.get("publication_url") != url or row.get("release_body_verified") is not True):
        raise ValueError("Corporate article proof does not bind its text, title, URL and clocks")
    identity = url if symbol == "ETN" else url+"#webpage"
    name = meta.get("name", "")
    if (meta.get("identity") != identity or not isinstance(name, str) or not name
            or not (title == heading_name(symbol, name) or symbol == "CRWD" and title.startswith(heading_name(symbol, name)+" "))
            or original_clock(meta.get("clock")).isoformat() != row["published"]):
        raise ValueError("Corporate publication proof does not bind the original metadata")
    observed = row["evidence_checked_at"]
    if type(observed) not in (int, float) or not math.isfinite(observed) or observed < original_clock(meta["clock"]).timestamp()-60:
        raise ValueError("Corporate article observation is invalid")
    if now is not None and (not -60 <= now.timestamp()-observed <= 21600 or original_clock(meta["clock"]) > now):
        raise ValueError("Corporate article observation is stale or publication is future-dated")
    return proof


def retrieve(source, fetch, now):
    symbol = source["company_symbol"]
    if source["url"] != SOURCES[symbol][0]:
        raise ValueError("Corporate newsroom index is not configured")
    payload = fetch(source["url"])
    if payload.get("status") != "ok":
        return payload
    if payload.get("final_url", payload.get("url")) != source["url"]:
        raise ValueError("Corporate newsroom index redirected outside its configured route")
    stamp = payload.get("fetched_at_epoch")
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or not -60 <= now.timestamp()-stamp <= 21600:
        raise ValueError("Corporate newsroom index observation is stale")
    links = Links(symbol); links.feed(payload["body"])
    if not links.urls:
        raise ValueError("Corporate newsroom index has no recognized release links")
    rows, reviews, problems = [], [], []
    for url in links.urls[:MAX_DETAILS]:
        try:
            detail = fetch(url)
            if detail.get("status") != "ok" or detail.get("final_url", detail.get("url")) != url:
                raise ValueError(detail.get("error") or "Corporate release redirect mismatch")
            row = page_article(symbol, url, detail["body"], now, detail.get("fetched_at_epoch"))
            rows.append(row)
            reviews.append({"url": url, "status": "read", "reason": "Original article title, body, canonical URL and zoned publication matched"})
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError) as error:
            reason = str(error)[:160]
            problems.append(reason)
            rows.append({"title": "Original corporate release awaiting verification", "link": url, "published": "", "description": ""})
            reviews.append({"url": url, "status": "limited", "reason": reason})
    return {**payload, "url": source["url"], "final_url": source["url"], "original_profile": 5,
            "articles": rows, "publication_problems": list(dict.fromkeys(problems))[:3], "release_read_reviews": reviews}
