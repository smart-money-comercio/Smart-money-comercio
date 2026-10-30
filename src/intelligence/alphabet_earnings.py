"""Bounded Alphabet earnings context, with an independently checked SEC route.

The regular source refresh owns network reads. Narration reads cached evidence,
keeps release dates separate from SEC acceptance clocks, and never infers why a
share price moved. The SEC route is an earnings-context reader, not a new hourly
search or an expansion of the general publisher-authority rules.
"""

from copy import deepcopy
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
import os
import re
from urllib.parse import urljoin, urlsplit

from src.intelligence.alphabet_source import FEED, document_reference, results_facts
from src.intelligence.sec_research import Identity, entity_key, location
from src.intelligence.special_alert_sources import timestamp
from src.intelligence.story_analysis import VisibleText

CIK = "1652044"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK0001652044.json"
MAX_AGE = 72 * 3600
TITLE = r"Alphabet (?:Announces|Reports) (?:First|Second|Third|Fourth) Quarter 20\d{2} Results"


class AmendedResults(ValueError):
    """Do not reuse an earlier results version after a known amendment."""


def digest(text):
    return sha256(text.encode()).hexdigest()


def visible(body):
    parser = VisibleText(); parser.feed(body)
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())


def summary(text):
    normalized = " ".join(text.split())
    match = re.search(TITLE, normalized[:1000])
    if not match:
        raise ValueError("Alphabet earnings-release heading unavailable")
    title = match[0]
    start = text.find(title)
    if start < 0:
        # A heading may be split over native HTML text nodes.
        text, start = normalized, match.start()
    text = re.split(r"Sundar Pichai|Financial Highlights", text[start:], maxsplit=1, flags=re.I)[0].strip()
    if not 80 <= len(text) <= 6000:
        raise ValueError("Alphabet earnings summary exceeds its text bound")
    dateline = re.search(r"\b([A-Z][a-z]+ \d{1,2}, 20\d{2})\b.{0,30}\bAlphabet Inc\.", " ".join(text.split())[:900])
    if not dateline:
        raise ValueError("Alphabet earnings-release date or issuer unavailable")
    released = datetime.strptime(dateline[1], "%B %d, %Y").date().isoformat()
    period = re.search(r"(First|Second|Third|Fourth) Quarter (20\d{2})", title)
    end = {"First": "March 31", "Second": "June 30", "Third": "September 30", "Fourth": "December 31"}[period[1]]
    if not re.search(r"\bquarter ended " + re.escape(end) + r",? " + period[2] + r"\b", " ".join(text.split()), re.I):
        raise ValueError("Alphabet earnings heading and stated results period disagree")
    if not results_facts(text, title):
        raise ValueError("No unambiguous period-specific Alphabet earnings facts")
    return title, text, released


class ExhibitLinks(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.links, self.current, self.row = base, [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = [[], []]
        if tag == "a":
            self.current = [urljoin(self.base, dict(attrs).get("href", "")), []]
            if self.row is not None:
                self.row[1].append(self.current[0])

    def handle_data(self, data):
        if self.row is not None:
            self.row[0].append(data)
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self.row is not None:
            if re.search(r"(?<!\d)99\.1(?!\d)", " ".join(self.row[0])):
                self.links.extend(self.row[1])
            self.row = None
        if tag == "a" and self.current is not None:
            url, parts = self.current
            if " ".join("".join(parts).split()) == "99.1":
                self.links.append(url)
            self.current = None


def _read(url, fetch, now):
    payload = fetch(url)
    stamp = payload.get("fetched_at_epoch")
    if (payload.get("status") != "ok" or payload.get("final_url", payload.get("url")) != url
            or type(stamp) not in (int, float) or not math.isfinite(stamp)
            or not -60 <= now.timestamp()-stamp <= 21600
            or not isinstance(payload.get("body"), str) or len(payload["body"].encode()) > 2_000_000):
        raise ValueError(payload.get("error") or "Alphabet SEC response authority, clock or size invalid")
    return payload, stamp


def retrieve(now, fetch):
    """Read submissions, one 8-K and its uniquely linked Exhibit 99.1: <=3 reads."""
    payload, first = _read(SUBMISSIONS, fetch, now)
    metadata = json.loads(payload["body"])
    if (str(int(metadata["cik"])) != CIK or entity_key(metadata.get("name", "")) != "alphabetinc"
            or not {"GOOG", "GOOGL"} <= set(metadata.get("tickers", []))):
        raise ValueError("Alphabet SEC submissions issuer mismatch")
    recent = metadata["filings"]["recent"]
    fields = ("accessionNumber", "form", "acceptanceDateTime", "primaryDocument", "reportDate", "items")
    if (any(not isinstance(recent.get(key), list) or len(recent[key]) > 2000 for key in fields)
            or len({len(recent[key]) for key in fields}) != 1):
        raise ValueError("Alphabet SEC submission columns are malformed")
    rows = [dict(zip(fields, row)) for row in zip(*(recent[key] for key in fields))
            if row[1] in {"8-K", "8-K/A"} and "2.02" in {value.strip() for value in str(row[5]).split(",")}]
    for row in rows:
        if timestamp(row["acceptanceDateTime"]) is None:
            raise ValueError("Alphabet SEC acceptance needs its original zoned timestamp")
    rows.sort(key=lambda row: timestamp(row["acceptanceDateTime"]), reverse=True)
    result = {"url": SUBMISSIONS, "final_url": SUBMISSIONS, "status": "ok", "body": "",
              "fetched_at_epoch": first, "cache_hit": payload.get("cache_hit", False),
              "earnings_backup_profile": 1, "record": None}
    if not rows:
        return result
    row = rows[0]; filed = timestamp(row["acceptanceDateTime"])
    if filed > now:
        raise ValueError("Alphabet SEC acceptance is future-dated")
    if (now-filed).total_seconds() > MAX_AGE:
        return result
    if row["form"] == "8-K/A":
        raise AmendedResults("Alphabet amended earnings filing requires reviewed replacement context")
    if sum(value["accessionNumber"] == row["accessionNumber"] for value in rows) != 1:
        raise ValueError("Alphabet SEC earnings accession is ambiguous")
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", row["accessionNumber"]):
        raise ValueError("Alphabet SEC accession invalid")
    compact = row["accessionNumber"].replace("-", "")
    primary = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{compact}/{row['primaryDocument']}"
    if location(primary)[:2] != (CIK, compact):
        raise ValueError("Alphabet SEC primary URL invalid")
    report, second = _read(primary, fetch, now)
    parser = Identity(); parser.feed(report["body"])
    identity = {key: sorted(values) for key, values in parser.values.items()}
    report_text = visible(report["body"])
    item = re.search(r"\bItem\s+2\.02\b", report_text, re.I)
    if item is None:
        raise ValueError("Alphabet 8-K results item unavailable")
    item_text = re.split(r"\bItem\s+\d{1,2}\.\d{2}\b", report_text[item.end():], maxsplit=1, flags=re.I)[0]
    if not re.search(r"\bpress release\b", item_text, re.I) or not re.search(r"\b99\.1\b", item_text):
        raise ValueError("Alphabet results item does not identify its earnings exhibit")
    links = ExhibitLinks(primary); links.feed(report["body"])
    exhibits = sorted(set(links.links))
    if len(exhibits) != 1 or location(exhibits[0])[:2] != (CIK, compact) or exhibits[0] == primary:
        raise ValueError("Alphabet Exhibit 99.1 link is not unique within its accession")
    # Check the primary issuer before requesting any linked document.
    _identity(identity)
    document, third = _read(exhibits[0], fetch, now)
    title, text, released = summary(visible(document["body"]))
    checked_at = min(first, second, third)
    record = {"schema": 1, "route": "sec", "symbol": "GOOG", "source": "SEC EDGAR",
              "title": title, "text": text, "sha256": digest(text), "release_date": released,
              "published": filed.isoformat(), "observed": datetime.fromtimestamp(checked_at, timezone.utc).isoformat(),
              "url": exhibits[0], "primary_url": primary, "metadata_url": SUBMISSIONS,
              "filing": {**row, "cik": CIK, "issuer": metadata["name"], "identity": identity,
                         "item_text": item_text.strip()[:3000], "exhibit_links": exhibits}}
    checked(record, now)
    result.update(fetched_at_epoch=checked_at, record=record)
    return result


def _identity(identity):
    if (identity.get("EntityCentralIndexKey") not in ([CIK], [CIK.zfill(10)]) or identity.get("DocumentType") != ["8-K"]
            or len(identity.get("EntityRegistrantName", [])) != 1
            or entity_key(identity["EntityRegistrantName"][0]) != "alphabetinc"
            or not {"GOOG", "GOOGL"} <= set(identity.get("TradingSymbol", []))):
        raise ValueError("Alphabet SEC primary issuer, form or share-class identity mismatch")


def checked(record, now):
    if (record.get("schema") != 1 or record.get("symbol") != "GOOG" or not isinstance(record.get("text"), str)
            or not 80 <= len(record["text"]) <= 6000 or record.get("sha256") != digest(record["text"])):
        raise ValueError("Alphabet earnings-context text changed")
    title, text, released = summary(record["text"])
    if (record.get("title") != title or text != record["text"] or record.get("release_date") != released):
        raise ValueError("Alphabet earnings-context heading or release date changed")
    published, observed = timestamp(record.get("published")), timestamp(record.get("observed"))
    if (published is None or observed is None or not 0 <= (now-published).total_seconds() <= MAX_AGE
            or not -60 <= (now-observed).total_seconds() <= 21600 or (published-observed).total_seconds() > 60):
        raise ValueError("Alphabet earnings context is unavailable, future-dated or stale")
    if record.get("route") == "sec":
        p = record["filing"]
        cik, compact, primary = location(record["primary_url"])
        if (cik != CIK or location(record["url"])[:2] != (cik, compact) or record["url"] == record["primary_url"]
                or record.get("source") != "SEC EDGAR" or record.get("metadata_url") != SUBMISSIONS
                or p.get("cik") != CIK or entity_key(p.get("issuer", "")) != "alphabetinc" or p.get("form") != "8-K"
                or p.get("primaryDocument") != primary or p.get("accessionNumber", "").replace("-", "") != compact
                or timestamp(p.get("acceptanceDateTime")) != published or p.get("reportDate") != released
                or not 0 <= (published.date()-date.fromisoformat(released)).days <= 1
                or "2.02" not in str(p.get("items", "")).split(",") or p.get("exhibit_links") != [record["url"]]
                or not re.search(r"\bpress release\b", p.get("item_text", ""), re.I)
                or not re.search(r"\b99\.1\b", p.get("item_text", ""))):
            raise ValueError("Alphabet SEC earnings proof does not bind the issuer, filing and exhibit")
        _identity(p["identity"])
    elif record.get("route") == "issuer":
        native = record.get("publisher_clock", "")
        try:
            original = datetime.fromisoformat(native.replace("Z", "+00:00"))
        except ValueError:
            original = parsedate_to_datetime(native)
        if (record.get("source") != "Alphabet Investor Relations" or original.tzinfo is None
                or timestamp(native) != published or original.date().isoformat() != released
                or not document_reference(record["url"], record.get("document_url", ""))
                or ("/" + title.replace(" ", "-")).casefold() not in urlsplit(record["url"]).path.casefold()):
            raise ValueError("Alphabet issuer earnings proof does not bind its native publication")
    else:
        raise ValueError("Unknown Alphabet earnings-context source")
    return deepcopy(record)


def refresh(force_refresh=False):
    from src.intelligence import news_live_sources as feeds
    cached = feeds.get_cached_source(SUBMISSIONS)
    if cached and (cached.get("status") == "error" or not force_refresh and cached.get("earnings_backup_profile") == 1):
        return {**cached, "cache_hit": True}
    previous = cached or feeds.load_cache().get(SUBMISSIONS) or {}
    agents = (os.getenv("SEC_USER_AGENT", ""), os.getenv("SEC_API_USER_AGENT", ""))
    agent = next((value for value in agents if "@" in value and "example.com" not in value.casefold()
                  and "your name" not in value.casefold() and "\r" not in value and "\n" not in value), "")
    try:
        if not agent:
            raise ValueError("Configure the existing SEC_USER_AGENT with an administrative contact")
        payload = retrieve(datetime.now(timezone.utc), lambda url: feeds.fetch_url(
            url, force_refresh, cache_result=False, user_agent=agent))
    except Exception as error:
        failure = feeds.get_cached_source(SUBMISSIONS)
        payload = failure if failure and failure.get("status") == "error" else {
            "url": SUBMISSIONS, "status": "error", "body": "", "error": str(error)[:160],
            "fetched_at_epoch": feeds.time.time(), "retry_after_epoch": feeds.time.time()+300}
        if isinstance(error, AmendedResults) or previous.get("withhold_context"):
            payload = {**payload, "withhold_context": True}
        prior_record = None if payload.get("withhold_context") else previous.get("record") or previous.get("retained_record")
        if prior_record:
            try:
                payload = {**payload, "retained_record": checked(prior_record, datetime.now(timezone.utc))}
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
    feeds.set_cached_source(SUBMISSIONS, payload)
    return payload


def health(payload, now):
    try:
        if not isinstance(payload, dict) or payload.get("status") != "ok" or payload.get("earnings_backup_profile") != 1:
            raise ValueError((payload or {}).get("error") or "No cached SEC earnings check")
        stamp = payload["fetched_at_epoch"]
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not -60 <= now.timestamp()-stamp <= 21600:
            raise ValueError("SEC earnings observation unavailable or stale")
        if payload.get("record") is not None:
            checked(payload["record"], now)
        return {"status": "available", "reason": "Dated earnings context available" if payload.get("record") else "No earnings filing within 72 hours"}
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        return {"status": "limited", "reason": str(error)[:160]}


def from_issuer(raw, now):
    if (raw.get("source") != "Alphabet Investor Relations" or raw.get("publisher_symbol") != "GOOG"
            or raw.get("official") is not True or raw.get("excerpt_scope") != "original release excerpt"):
        raise ValueError("Original Alphabet release excerpt required")
    title, text, released = summary(raw.get("source_excerpt", ""))
    if title != raw["title"]:
        raise ValueError("Alphabet issuer context heading mismatch")
    record = {"schema": 1, "route": "issuer", "symbol": "GOOG", "source": raw["source"],
              "title": title, "text": text, "sha256": digest(text), "release_date": released,
              "publisher_clock": raw["published"], "published": timestamp(raw["published"]).isoformat(),
              "observed": raw.get("evidence_checked_at") or raw["source_checked_at"],
              "url": raw["url"], "document_url": raw.get("document_url", "")}
    return checked(record, now)


def candidates(raw, cache, now, events):
    movers = {row["symbol"] for row in events if row.get("status") == "rechecked" and abs(row["reported_move"]) >= 5}
    payload = cache.get(SUBMISSIONS)
    coverage = health(payload, now)
    if isinstance(payload, dict) and payload.get("withhold_context"):
        return [], coverage
    if not {"GOOG", "GOOGL"} & movers:
        return [], coverage
    values = []
    for item in raw:
        try: values.append(from_issuer(item, now))
        except (ValueError, TypeError, KeyError, AttributeError): pass
    try:
        if coverage["status"] == "available" and payload.get("record"):
            values.append(checked(payload["record"], now))
        elif isinstance(payload, dict) and payload.get("status") == "error" and payload.get("retained_record"):
            values.append({**checked(payload["retained_record"], now), "cached_after_failure": True})
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    # Use the most recent results day; prefer the original publisher on that day.
    values.sort(key=lambda row: (row["release_date"], row["route"] == "issuer"), reverse=True)
    if values:
        same_day = [row for row in values if row["release_date"] == values[0]["release_date"]]
        disclosed = {}
        for row in same_day:
            for fact in results_facts(row["text"], row["title"]):
                if fact["field"] in disclosed and disclosed[fact["field"]] != fact["value"]:
                    return [], {"status": "limited", "reason": "Conflicting original earnings figures; context withheld"}
                disclosed[fact["field"]] = fact["value"]
    return values[:1], coverage


def retain(values, now, events, stories, focus):
    if not isinstance(values, list) or len(values) > 1:
        raise ValueError("Alphabet earnings context exceeds its edition bound")
    movers = {row["symbol"] for row in events if row.get("status") == "rechecked" and abs(row["reported_move"]) >= 5}
    if values and not {"GOOG", "GOOGL"} & movers:
        raise ValueError("Earnings context needs a matching rechecked major move")
    checked_values = [checked(row, now) for row in values]
    fresh = any({"GOOG", "GOOGL"} & set(story.get("symbols", []))
                and story.get("event_evidence", {}).get("event") == "earnings" for story in stories)
    featured = {row["symbol"] for row in (focus or {}).get("selected", [])}
    return [] if fresh or not {"GOOG", "GOOGL"} & featured else checked_values


def cached_context(raw, now, events):
    from pathlib import Path
    from src.intelligence import news_live_sources as feeds
    path = Path(os.getenv("NEWS_LIVE_SOURCE_CACHE_FILE", str(feeds.CACHE_FILE)))
    try:
        if path.stat().st_size > feeds.MAX_CACHE_BYTES:
            raise ValueError("Source cache exceeds its read bound")
        cache = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(cache, dict):
            raise ValueError("Source cache is not an object")
    except (OSError, ValueError, UnicodeError):
        cache = {}
    return candidates(raw, cache, now, events)


def narration(record, event):
    facts = results_facts(record["text"], record["title"])
    labels = {"reported_revenue": "revenue", "reported_operating_margin": "operating margin", "reported_eps": "earnings per share"}
    details = "; ".join(labels[row["field"]] + " of " + row["value"] for row in facts[:2])
    day = date.fromisoformat(record["release_date"]).strftime("%B %d").replace(" 0", " ")
    provenance = ("The release is attached to its SEC 8-K accepted " + timestamp(record["published"]).strftime("%B %d").replace(" 0", " ") + " UTC. "
                  if record["route"] == "sec" else "The figures come from its original investor-relations release. ")
    if record.get("cached_after_failure"):
        provenance += "This is previously verified cached context; the latest source fetch was limited. "
    move = f"Shares {'fell' if event['reported_move'] < 0 else 'rose'} {abs(event['reported_move']):.1f} percent in the quoted regular session. "
    return (f"Alphabet — recent earnings context: " + move + f"Its {day} results release reported {details}. " + provenance
            + "Investor focus: compare growth with profitability and the cost of expansion. These dated results do not establish the cause of the price move.")


def audit(record):
    facts = results_facts(record["text"], record["title"])
    lines = ["DATED EARNINGS CONTEXT — Alphabet", "Release: " + record["title"],
             "Release date: " + record["release_date"],
             ("SEC acceptance: " if record["route"] == "sec" else "Original publisher clock: ") + record["published"],
             "Source: " + record["source"] + " | Checked: " + record["observed"],
             "Purpose: dated context for a rechecked move; not counted as a fresh news story or proof of its cause."]
    lines.extend("Retained fact: " + row["field"] + " | " + row["value"] for row in facts[:2])
    if record.get("cached_after_failure"):
        lines.append("Source access: latest fetch limited; the original verification clock above has not been reset")
    if record.get("primary_url"):
        lines.append("Filing: " + record["primary_url"])
    lines.append("Release document: " + record.get("document_url", record["url"]))
    return lines
