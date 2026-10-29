"""Explicit publisher clocks and issuer-linked wire references; no inferred zones."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit
import re

from src.intelligence.special_alert_sources import timestamp


TREASURY_INDEX = "https://home.treasury.gov/news/press-releases"


def treasury_release(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "home.treasury.gov"
                and not parts.username and not parts.password and parts.port in (None, 443)
                and not parts.query and not parts.fragment
                and re.fullmatch(r"/news/press-releases/[a-z]{2}\d+/?", parts.path) is not None)
    except (TypeError, ValueError):
        return False


class TreasuryIndex(HTMLParser):
    """Bind each release heading only to the clock inside its own listing row."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.rows, self.heading = [], [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.stack.append({"clocks": [], "links": [], "parts": []})
        if not self.stack:
            return
        if tag == "time":
            self.stack[-1]["clocks"].append(attrs.get("datetime", ""))
        if tag == "h3" and "featured-stories__headline" in attrs.get("class", "").split():
            self.heading = self.stack[-1]
        if tag == "a" and self.heading is not None:
            self.heading["links"].append(urljoin(TREASURY_INDEX, attrs.get("href", "")))

    def handle_data(self, data):
        if self.heading is not None:
            self.heading["parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "h3":
            self.heading = None
        if tag != "div" or not self.stack:
            return
        row = self.stack.pop()
        title = " ".join("".join(row["parts"]).split())
        if not title or len(row["links"]) != 1 or not treasury_release(row["links"][0]):
            return
        clocks = row["clocks"]
        self.rows.append({"title": title, "link": row["links"][0], "description": "",
                          "published": clocks[0] if len(clocks) == 1 and timestamp(clocks[0]) else ""})


def treasury_items(body: str) -> list[dict]:
    parser = TreasuryIndex()
    parser.feed(body)
    rows = {}
    for row in parser.rows:
        key = row["link"].rstrip("/")
        previous = rows.get(key)
        if previous and (previous["title"] != row["title"] or previous["published"] != row["published"]):
            previous["published"] = ""
        else:
            rows.setdefault(key, row)
    return list(rows.values())[:30]


class TreasuryPublication(HTMLParser):
    """Read the publication field, excluding unrelated dates elsewhere on a page."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.clocks = 0, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif "field--name-field-news-publication-date" in attrs.get("class", "").split():
                self.depth = 1
        if self.depth and tag == "time":
            self.clocks.append(timestamp(attrs.get("datetime")))

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1


def treasury_clock(body: str, title: str):
    from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
    page = PublicationPage(); page.feed(body)
    clock = TreasuryPublication(); clock.feed(body)
    dates = set(clock.clocks + page.dates)
    if page.dates or "datePublished" in body:
        dates.add(publication_time(body.encode(), title))
    if page.title != title or len(dates) != 1 or None in dates:
        raise ValueError("Original Treasury release title or publication clock unavailable or ambiguous")
    return dates.pop()


class WireLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        try:
            parts = urlsplit(dict(attrs).get("href", ""))
            if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
                return
            if parts.hostname == "cts.businesswire.com" and parts.path == "/ct/CT":
                ids = parse_qs(parts.query).get("newsitemid", [])
                self.ids.update(value for value in ids if re.fullmatch(r"\d{14}", value))
            elif parts.hostname == "www.businesswire.com":
                match = re.fullmatch(r"/news/home/(\d{14})/en(?:/[^/]*)?/?", parts.path)
                if match:
                    self.ids.add(match[1])
        except (ValueError, TypeError):
            pass


def linked_wire(body: str) -> str:
    """Only an explicit link in this issuer release may supply a wire identity."""
    parser = WireLinks(); parser.feed(body)
    if len(parser.ids) > 1:
        raise ValueError("Issuer release links to conflicting wire identities")
    return "https://www.businesswire.com/news/home/" + next(iter(parser.ids)) + "/en/" if parser.ids else ""


def matching_wire(expected: str, actual: str) -> bool:
    try:
        reference = urlsplit(expected)
        parts = urlsplit(actual)
        match = re.fullmatch(r"/news/home/(\d{14})/en(?:/[^/]*)?/?", parts.path)
        return (parts.scheme == "https" and parts.hostname == "www.businesswire.com"
                and not parts.username and not parts.password and parts.port in (None, 443)
                and bool(match) and expected == "https://www.businesswire.com/news/home/" + match[1] + "/en/"
                and reference.hostname == "www.businesswire.com")
    except (TypeError, ValueError):
        return False


def clock_reference_allowed(symbol: str, article_url: str, clock_url: str) -> bool:
    return clock_url == article_url or symbol == "PLTR" and matching_wire(clock_url, clock_url)
