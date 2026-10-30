"""Original Alphabet releases: native RSS clocks and issuer-linked documents."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import math
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.special_alert_sources import timestamp

FEED = "https://abc.xyz/rss/pressrelease.aspx?LanguageId=1"


def release_url(url):
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname in {"abc.xyz", "www.abc.xyz"} and not p.username and not p.password
                and p.port in (None, 443) and not p.query and not p.fragment
                and re.fullmatch(r"/investor/news/news-details/20\d{2}/[A-Za-z0-9-]+/default\.aspx", p.path) is not None)
    except (TypeError, ValueError):
        return False


def attachment_url(url):
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.hostname == "s206.q4cdn.com" and not p.username and not p.password
                and p.port in (None, 443) and not p.query and not p.fragment
                and re.fullmatch(r"/479360582/files/doc_news/20\d{2}/[A-Za-z]{3}/\d{1,2}/attachments/[A-Za-z0-9_-]+\.pdf", p.path) is not None)
    except (TypeError, ValueError):
        return False


def aliases(symbols):
    result = list(symbols)
    if {"GOOG", "GOOGL"} & set(result):
        result += ["GOOG", "GOOGL"]
    return list(dict.fromkeys(result))


class Attachments(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.urls = base, set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = urljoin(self.base, dict(attrs).get("href", ""))
            if attachment_url(url):
                self.urls.add(url)


def observation(payload, now):
    at = payload.get("fetched_at_epoch")
    if payload.get("status") != "ok" or type(at) not in (int, float) or not math.isfinite(at) or not -60 <= now.timestamp()-at <= 21600:
        raise ValueError(payload.get("error") or "Alphabet source observation unavailable or stale")
    return at


def release_document(body, title, published, url, fetch, now):
    from src.intelligence.news_original_sources import ArticleBody, article_excerpt
    from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
    from src.intelligence.story_analysis import release_text
    if not release_url(url) or not isinstance(body, str):
        raise ValueError("Alphabet original release URL or body unavailable")
    page = ArticleBody("Alphabet Investor Relations", url); page.feed(body)
    if sum(value.casefold() == title.casefold() for value in page.headings) != 1:
        raise ValueError("Alphabet release heading does not match its feed")
    native = timestamp(published)
    try: original = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError: original = parsedate_to_datetime(published)
    date = rf"\b{original:%B}\s+{original.day},\s+{original.year}\b"
    if native is None or not re.search(date, " ".join(page.date_parts)):
        raise ValueError("Alphabet release date does not match its original feed")
    metadata = PublicationPage(); metadata.feed(body)
    if metadata.dates or 'datePublished' in body:
        if publication_time(body.encode(), title, url=url) != native:
            raise ValueError("Alphabet release publication conflicts with its feed")
    # HTML notices use their identified article body. Empty release pages must
    # resolve a unique attachment from this issuer's exact public CDN tenant.
    if "".join(page.parts).strip():
        return article_excerpt(body, title, published, publisher="Alphabet Investor Relations", url=url), url, None
    links = Attachments(url); links.feed(body)
    if len(links.urls) != 1:
        raise ValueError("Unique issuer-linked Alphabet results document unavailable")
    document = next(iter(links.urls))
    if not document_reference(url, document):
        raise ValueError("Alphabet document period does not match the release URL")
    value = fetch(document)
    observed = observation(value, now)
    if value.get("final_url", value.get("url")) != document:
        raise ValueError("Alphabet document redirected outside its linked attachment")
    raw = value.get("body")
    if not isinstance(raw, bytes) or not raw.startswith(b"%PDF-") or len(raw) > 2_000_000:
        raise ValueError("Alphabet document is not a bounded original PDF")
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(raw))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 16:
        raise ValueError("Alphabet results document cannot be read within its page bound")
    pages = [page.extract_text() or "" for page in reader.pages[:2]]
    if any(len(page) > 60_000 for page in pages):
        raise ValueError("Alphabet results document text exceeds its read bound")
    text = "\n".join(pages)
    normalized = " ".join(text.split())
    if (not re.match(r"Alphabet (?:Announces|Reports) .{0,70}Results$", title, re.I)
            or " ".join(title.split()).casefold() not in " ".join(pages[0].split()).casefold()[:300]
            or not re.search(date, normalized[:900]) or not re.search(r"\bAlphabet Inc\.", normalized[:900])):
        raise ValueError("Alphabet PDF title, issuer or release date does not match the original announcement")
    return release_text(text), document, observed


def retrieve(source, fetch, now, *, feed_payload=None):
    from src.intelligence.news_live_sources import parse_rss_items
    from src.intelligence.news_original_sources import authorized_response
    payload = feed_payload if feed_payload is not None else fetch(FEED)
    first = observation(payload, now)
    if source["url"] != FEED or payload.get("final_url", payload.get("url")) != FEED or not authorized_response(source, payload):
        raise ValueError("Alphabet original feed authority mismatch")
    rows = parse_rss_items(payload["body"], source, full_titles=True, full_text=True)[:30]
    if not rows:
        raise ValueError("Alphabet original feed has no dated release candidates")
    for row in rows:
        row["description"] = ""
        row["release_body_verified"] = False
    fresh = [row for row in rows if release_url(row["link"]) and timestamp(row["published"]) is not None
             and 0 <= (now-timestamp(row["published"])).total_seconds() <= (
                 72*3600 if re.fullmatch(r"Alphabet (?:Announces|Reports) (?:First|Second|Third|Fourth) Quarter 20\d{2} Results", row["title"], re.I) else 86400)
             and timestamp(row["published"]).timestamp()-first <= 60]
    fresh.sort(key=lambda row: timestamp(row["published"]), reverse=True)
    problems = []
    for row in fresh[:1]:
        try:
            detail = fetch(row["link"]); checked = observation(detail, now)
            if detail.get("final_url", detail.get("url")) != row["link"]:
                raise ValueError("Alphabet release redirect does not match the feed link")
            text, document, document_at = release_document(detail["body"], row["title"], row["published"], row["link"], fetch, now)
            if len(text) < 80:
                raise ValueError("Alphabet original release text is insufficient")
            checked = min(first, checked, document_at if document_at is not None else checked)
            if timestamp(row["published"]).timestamp()-checked > 60:
                raise ValueError("Alphabet body observation predates its purported publication")
            row.update(description=text, release_body_verified=True, evidence_checked_at=checked,
                       publication_url=row["link"], document_url=document, document_sha256=sha256(text.encode()).hexdigest())
        except Exception as exc:
            problems.append(str(exc)[:160])
    return {**payload, "url": FEED, "final_url": FEED, "original_profile": 2, "articles": rows,
            "publication_problems": list(dict.fromkeys(problems))[:3]}


def document_reference(url, document):
    if not release_url(url):
        return False
    if url == document:
        return True
    if not attachment_url(document):
        return False
    period = re.search(r"/Alphabet-(?:Announces|Reports)-(First|Second|Third|Fourth)-Quarter-(20\d{2})-Results(?:-|/)", urlsplit(url).path, re.I)
    if not period:
        return False
    quarter = {"first": 1, "second": 2, "third": 3, "fourth": 4}[period[1].lower()]
    filename = urlsplit(document).path.rsplit("/", 1)[-1].lower()
    return (re.search(rf"(?:^|[-_]){period[2]}q{quarter}(?:[-_]|$)", filename) is not None
            and all(value in filename for value in ("alphabet", "earnings", "release")))


def results_facts(text, title):
    """Read only the dated release's opening summary, never mixed-period tables."""
    match = re.fullmatch(r"Alphabet (?:Announces|Reports) (First|Second|Third|Fourth) Quarter (20\d{2}) Results", title, re.I)
    if not match or not " ".join(text.split()).casefold().startswith(title.casefold()):
        return []
    period = match[1].lower() + " quarter " + match[2]
    summary = re.split(r"Sundar Pichai|Financial Highlights", text, maxsplit=1, flags=re.I)[0][:2200]
    starts = r"[•]?\s*(?:Consolidated Alphabet|Google (?:Cloud|Services)|Net income)"
    blocks = re.split(r"\n(?=" + starts + r")|(?<=[.!?])\s+(?=" + starts + r")", summary, flags=re.I)
    fields = {"reported_revenue": r"\bConsolidated Alphabet revenues\b.{0,90}?\bto\s+(\$[\d,.]+\s+(?:billion|million))\b",
              "reported_operating_margin": r"\boperating margin was\s+(\d+(?:\.\d+)?%)",
              "reported_eps": r"\bEPS was\s+(\$\d+(?:\.\d+)?)\b"}
    facts = []
    for field, pattern in fields.items():
        values = []
        for block in blocks:
            if re.search(r"\b(?:adjusted|non.GAAP|expect\w*|guidance|forecast\w*|project\w*|could|may|might|will|would|not|previously|prior|last year)\b", block, re.I):
                continue
            for found in re.finditer(pattern, block, re.I | re.S):
                values.append((" ".join(found[1].split()), block.strip()))
        if len(values) == 1 and len(values[0][1]) <= 500:
            value, quote = values[0]
            facts.append({"field": field, "value": value + " (" + period + ")", "evidence": quote})
    return facts
