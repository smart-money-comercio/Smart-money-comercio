"""Northrop's public newsroom cards and explicit original-publication field."""

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.special_alert_sources import timestamp


HOME = "https://news.northropgrumman.com/"


def article_url(value):
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname == "news.northropgrumman.com"
                and not p.username and not p.password and p.port in (None, 443) and not p.query and not p.fragment
                and bool(re.fullmatch(r"/(?:news/releases/|releases/)[^/]+/?|/(?:[a-z0-9]+(?:-[a-z0-9]+)*/)?[a-z0-9]+(?:-[a-z0-9]+){2,}/?", p.path)))
    except (TypeError, ValueError):
        return False


def same_page(value, expected):
    """The publisher currently duplicates the leading slash in og:url."""
    try:
        p, reference = urlsplit(value), urlsplit(expected)
        return (p.scheme == "https" and p.hostname == "news.northropgrumman.com"
                and not p.username and not p.password and p.port in (None, 443) and not p.query and not p.fragment
                and ("/" + p.path.lstrip("/")).rstrip("/") == reference.path.rstrip("/"))
    except (TypeError, ValueError):
        return False


class HomeCards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current, self.rows = None, []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        url = urljoin(HOME, attrs.get("href", ""))
        classes = attrs.get("class", "").split()
        label = attrs.get("aria-label", "")
        headline = any(value.startswith("NewsroomHeroCarousel_headline__") for value in classes)
        supplied = label.removeprefix("Read More about ") if label.startswith("Read More about ") else ""
        self.current = [url, [], supplied] if article_url(url) and (headline or supplied) else None

    def handle_data(self, value):
        if self.current is not None:
            self.current[1].append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            url, parts, supplied = self.current
            title = " ".join((supplied or "".join(parts)).split())
            if title and not title.endswith(("...", "…")) and len(title) <= 1000:
                self.rows.append({"title": title, "link": url, "published": ""})
            self.current = None


def home_items(body):
    parser = HomeCards(); parser.feed(body)
    rows = {}
    for row in parser.rows:
        previous = rows.get(row["link"])
        if previous is not None and previous["title"] != row["title"]:
            raise ValueError("Northrop homepage has conflicting titles for one release")
        rows[row["link"]] = row
    return list(rows.values())[:3]


class PublicationFields(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.clocks, self.urls = [], []

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        attrs = dict(attrs)
        if attrs.get("property") == "og:publishDate":
            self.clocks.append(timestamp(attrs.get("content")))
        if attrs.get("property") == "og:url":
            self.urls.append(attrs.get("content", ""))


def publication_dates(body, title, url, page):
    if not article_url(url):
        return []
    fields = PublicationFields(); fields.feed(body)
    if not fields.clocks:
        return []
    if (page.title.casefold() != title.casefold() or sum(value.casefold() == title.casefold() for value in page.headings) != 1
            or not fields.urls or not all(same_page(value, url) for value in fields.urls)):
        raise ValueError("Original Northrop release title or canonical URL does not match")
    return fields.clocks
