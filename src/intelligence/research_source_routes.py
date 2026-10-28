"""Resolve web leads to dated original releases without widening source budgets."""

from datetime import datetime
import hashlib
import re
from urllib.parse import unquote, urlsplit

from src.intelligence.research_evidence import SourceRejected, publisher_reports
from src.intelligence.special_alert_sources import timestamp


def background_reason(url: str) -> str:
    path = urlsplit(url).path.lower().rstrip("/")
    host = urlsplit(url).hostname or ""
    if re.search(r"/(?:faq|faqs|topics)(?:/|$)", path):
        return "FAQ or topic index; a specific dated original report is required"
    if host.endswith("federalreserve.gov") and (re.fullmatch(r"/newsevents/\d{4}-[a-z]+\.htm", path) or "/monetarypolicy/fomccalendars" in path):
        return "Scheduled-event background; use the calendar evidence rather than treating it as a fresh policy release"
    if host.endswith("eia.gov") and path in {"/petroleum/gasdiesel", "/todayinenergy/prices.php"}:
        return "Recurring data dashboard; a dated report with a discrete development is required for the news desk"
    return ""


def news_index(url: str) -> bool:
    return urlsplit(url).path.lower().rstrip("/") in {"", "/news", "/newsroom", "/news-releases", "/press-releases", "/releases"}


def matching_release(lead: dict, values: list[dict], identity) -> dict | None:
    publisher = identity(lead["url"])
    if not publisher:
        return None
    stop = {"the", "and", "for", "with", "from", "this", "that", "will", "its", "are", "was", "has", "have", "new", "news", "release", "press", "details", "default", "aspx", "html", "http", "https", "www", "com"}
    def words(text):
        return {word for word in re.findall(r"[a-z0-9]+", unquote(text).lower()) if len(word) > 2 and word not in stop and not word.isdigit()}
    clues = [words(lead["title"]), words(urlsplit(lead["url"]).path)]
    scores = []
    for value in values:
        if identity(value["url"]) != publisher:
            continue
        if value["url"] == lead["url"]:
            return value
        target = words(value["title"])
        # A generic issuer name or one shared topic cannot establish identity.
        score = max((len(clue & target) / max(len(clue), len(target)) for clue in clues if len(clue & target) >= 4), default=0)
        if score >= .65:
            scores.append((score, value))
    scores.sort(key=lambda row: row[0], reverse=True)
    return scores[0][1] if scores and (len(scores) == 1 or scores[0][0]-scores[1][0] >= .15) else None


class SourceResolver:
    def __init__(self, now: datetime, values, fetch, identity, key_for, symbols, latest):
        self.now, self.values, self.fetch, self.identity, self.key_for = now, list(values), fetch, identity, key_for
        self.symbols, self.latest, self.feeds_read, self.failures, self.verified_values = symbols, latest, set(), {}, {}

    def reference(self, lead: dict, *, read_feed=False) -> dict | None:
        match = matching_release(lead, self.values, self.identity)
        if match or not read_feed:
            return match
        from src.intelligence import news_live_sources as feeds
        publisher = self.identity(lead["url"])
        if not publisher:
            return None
        source = next((row for row in feeds.NEWS_SOURCES if feeds.is_original_source(row) and not row.get("format") and
            (row.get("company_symbol") == publisher["symbol"] if publisher["symbol"] else row["name"] == publisher["name"])), None)
        if not source:
            return None
        if source["url"] not in self.feeds_read:
            self.feeds_read.add(source["url"])
            try:
                body = self.fetch(source["url"])
                if not isinstance(body, bytes) or len(body) > feeds.MAX_FEED_BYTES:
                    raise ValueError("Invalid original publisher feed")
                payload = {"status": "ok", "body": body.decode("utf-8"), "url": source["url"], "final_url": source["url"], "fetched_at_epoch": self.now.timestamp()}
                values, _ = publisher_reports(self.now, self.symbols, {}, self.identity, self.key_for,
                    include_unread=True, cache={source["url"]: payload})
                self.values.extend(values)
            except Exception as exc:
                self.failures[source["url"]] = exc
        if source["url"] in self.failures:
            raise self.failures[source["url"]]
        return matching_release(lead, self.values, self.identity)

    def verify(self, value: dict) -> dict:
        from src.intelligence.news_original_sources import article_excerpt
        from src.intelligence.hourly_research import check_proof
        if value.get("discovery_evidence"):
            check_proof(value, self.now)
            return value
        if value["url"] in self.verified_values:
            return self.verified_values[value["url"]]
        reference = value["publisher_reference"]
        published, observed = timestamp(reference["published"]), timestamp(reference["observed"])
        if published is None or observed is None or not -60 <= (self.now-observed).total_seconds() <= 21600 or (published-observed).total_seconds() > 60:
            raise ValueError("Publisher reference clocks unavailable or stale")
        age = (self.now-published).total_seconds()
        if age > 86400:
            raise SourceRejected("Original release is older than the 24-hour news window", status="expired", published=published.isoformat())
        if age < 0:
            raise ValueError("Original publisher release is future-dated")
        body = self.fetch(value["url"])
        if not isinstance(body, bytes) or len(body) > 2_000_000:
            raise ValueError("Invalid original release body")
        clock = reference.get("publisher_clock", value["published"])
        if timestamp(clock) != published:
            raise ValueError("Publisher reference clock does not match the release")
        text = " ".join(article_excerpt(body.decode("utf-8"), value["title"], clock,
                                        publisher=self.identity(value["url"])["name"]).split())
        if len(text) < 80:
            raise ValueError("Usable original release text unavailable")
        proof = {"schema": 1, "url": value["url"], "title": value["title"], "published": value["published"],
            "observed": value["source_checked_at"], "publisher": self.identity(value["url"]), "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(), "feed_url": reference["feed_url"], "scope": "original release excerpt"}
        result = {**value, "source_excerpt": text, "excerpt_scope": "original release excerpt", "discovery_evidence": proof}
        check_proof(result, self.now)
        self.verified_values[value["url"]] = result
        return result

    def pre_resolve(self, lead: dict) -> bool:
        """Prefer the publisher's canonical release before reading known IR mirrors."""
        host = urlsplit(lead["url"]).hostname or ""
        return news_index(lead["url"]) or host.split(".")[0] in {"investor", "investors", "ir"}
