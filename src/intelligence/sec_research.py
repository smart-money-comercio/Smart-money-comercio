"""Bounded, identity-checked SEC current reports discovered by the hourly desk."""

from datetime import datetime
from html.parser import HTMLParser
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

from src.intelligence.special_alert_sources import timestamp
from src.intelligence.story_analysis import VisibleText
from src.intelligence.research_evidence import SourceRejected


ARCHIVE = re.compile(r"/Archives/edgar/data/(\d{1,10})/(\d{18})/([A-Za-z0-9_.-]+\.html?)")


def location(url: str) -> tuple[str, str, str]:
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != "www.sec.gov" or p.username or p.password or p.port not in (None, 443) or p.fragment:
        raise ValueError("SEC lead must use the original HTTPS archive")
    if p.path == "/ix" and p.query:
        query = parse_qs(p.query)
        if set(query) != {"doc"} or len(query["doc"]) != 1:
            raise ValueError("SEC viewer has an ambiguous document")
        p = urlsplit("https://www.sec.gov" + query["doc"][0])
    match = ARCHIVE.fullmatch(p.path)
    if not match or p.query or ".." in match[3]:
        raise ValueError("SEC archive path unavailable or unsupported")
    return str(int(match[1])), match[2], match[3]


def authority(url: str) -> bool:
    p = urlsplit(url)
    if (p.scheme == "https" and p.hostname == "data.sec.gov" and not p.username and not p.password
            and p.port in (None, 443) and not p.query and not p.fragment
            and re.fullmatch(r"/submissions/CIK\d{10}\.json", p.path)):
        return True
    try:
        location(url)
        return True
    except (ValueError, TypeError):
        return False


class Identity(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values, self.field, self.parts = {}, "", []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "ix:nonnumeric":
            name = dict(attrs).get("name", "").split(":")[-1]
            if name in {"EntityRegistrantName", "EntityCentralIndexKey", "DocumentType", "TradingSymbol"}:
                self.field, self.parts = name, []

    def handle_data(self, value):
        if self.field:
            self.parts.append(value)

    def handle_endtag(self, tag):
        if tag.lower() == "ix:nonnumeric" and self.field:
            value = " ".join("".join(self.parts).split())
            self.values.setdefault(self.field, set()).add(value)
            self.field = ""


def entity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def disclosure(text: str) -> dict:
    gpu_lease = bool(re.search(r"\b(?:GPU|graphics processing unit)\b", text, re.I) and re.search(r"\b(?:finance lease|lease financing)\b", text, re.I))
    topic = "AI infrastructure financing" if gpu_lease else "financing disclosure" if re.search(r"\b(?:credit agreement|debt financing|notes offering|finance lease)\b", text, re.I) else ""
    facts = []
    # Keep an expected total over lease terms distinct from annual expense or revenue.
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        match = re.search(r"\bexpects? aggregate principal payments\b.{0,100}\bto total\s+((?:approximately |about )?\$[\d,.]+ (?:billion|million))\b", sentence, re.I)
        if gpu_lease and match and len(sentence) <= 1000:
            facts.append({"field": "expected_lease_principal", "value": match[1], "sentence": sentence})
    return {"topic": topic, "gpu_lease": gpu_lease, "facts": facts[:1],
            "conditional": bool(re.search(r"\b(?:subject to|contemplated|expects?|expected)\b", text, re.I))}


def verify(url: str, now: datetime, fetch) -> dict:
    cik, compact, document = location(url)
    accession = compact[:10] + "-" + compact[10:12] + "-" + compact[12:]
    metadata = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"))
    if str(int(metadata["cik"])) != cik or not isinstance(metadata.get("name"), str) or not 1 <= len(metadata["name"]) <= 160:
        raise ValueError("SEC issuer metadata does not match the archive CIK")
    recent = metadata["filings"]["recent"]
    fields = ("accessionNumber", "form", "acceptanceDateTime", "primaryDocument")
    if any(not isinstance(recent.get(key), list) or len(recent[key]) > 2000 for key in fields) or len({len(recent[key]) for key in fields}) != 1:
        raise ValueError("SEC submission records are malformed")
    rows = [dict(zip(fields, row)) for row in zip(*(recent[key] for key in fields)) if row[0] == accession]
    if len(rows) != 1:
        raise ValueError("SEC accession not found uniquely in issuer submissions")
    row = rows[0]
    if row["form"] not in {"8-K", "8-K/A", "6-K", "6-K/A"}:
        raise ValueError("SEC form needs its own reader; current reports only")
    primary = row["primaryDocument"]
    if not isinstance(primary, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*\.html?", primary) or ".." in primary:
        raise ValueError("SEC primary document path is invalid")
    if document not in {primary, accession+"-index.htm", accession+"-index.html"}:
        raise ValueError("SEC lead is not this accession's primary document or index")
    published = timestamp(row["acceptanceDateTime"])
    if published is None or (now-published).total_seconds() < 0:
        raise ValueError("SEC acceptance timestamp unavailable or future-dated")
    if (now-published).total_seconds() > 86400:
        raise SourceRejected("SEC report is older than the 24-hour news window; retained as dated history", status="expired", published=published.isoformat())
    canonical = f"https://www.sec.gov/Archives/edgar/data/{cik}/{compact}/{primary}"
    raw = fetch(canonical)
    if not isinstance(raw, bytes) or len(raw) > 2_000_000:
        raise ValueError("SEC report exceeds its bounded source read")
    parser = Identity(); parser.feed(raw.decode("utf-8", "replace"))
    identity = {key: sorted(values) for key, values in parser.values.items()}
    if (identity.get("EntityCentralIndexKey") != [str(int(cik)).zfill(10)] and identity.get("EntityCentralIndexKey") != [cik]):
        raise ValueError("SEC primary document CIK mismatch or unavailable")
    if identity.get("DocumentType") != [row["form"]] or len(identity.get("EntityRegistrantName", [])) != 1 or entity_key(identity["EntityRegistrantName"][0]) != entity_key(metadata["name"]):
        raise ValueError("SEC primary document issuer or form mismatch")
    visible = VisibleText(); visible.feed(raw.decode("utf-8", "replace"))
    text = " ".join("".join(visible.parts).split())
    start = re.search(r"\bItem\s+\d{1,2}\.\d{2}\b", text, re.I)
    if start: text = text[start.start():]
    text = re.split(r"\b(?:Forward[- ]Looking Statements|SIGNATURES?)\b", text, maxsplit=1, flags=re.I)[0].strip()[:6000]
    if len(text) < 80:
        raise ValueError("SEC report has insufficient current disclosure text")
    symbols = sorted(set(identity.get("TradingSymbol", [])) & set(metadata.get("tickers") or []))[:10]
    symbols = [symbol for symbol in symbols if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)]
    profile = {"schema": 1, "cik": cik, "accession": accession, "form": row["form"], "issuer": metadata["name"],
               "primary_document": primary, "url": canonical, "published": published.isoformat(), "observed": now.isoformat(),
               "identity": identity, "symbols": symbols, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
               "disclosure": disclosure(text)}
    title = f"{profile['issuer']}: Form {profile['form']} — {profile['disclosure']['topic'] or 'current company report'}"
    return {"title": title, "original_title": title, "url": canonical, "published": profile["published"], "source_checked_at": profile["observed"],
            "source": "SEC EDGAR", "official": True, "publisher_symbol": "", "symbols": symbols, "kind": "macro", "relevant": True,
            "source_excerpt": text, "excerpt_scope": "original release excerpt", "sec_filing": profile}


def checked(value: dict, now: datetime | None = None) -> dict:
    p = value["sec_filing"]
    cik, compact, document = location(value["url"])
    if (p.get("schema") != 1 or p.get("cik") != cik or p.get("accession") != compact[:10]+"-"+compact[10:12]+"-"+compact[12:]
            or p.get("primary_document") != document or p.get("form") not in {"8-K", "8-K/A", "6-K", "6-K/A"}
            or p.get("url") != value["url"] or p.get("published") != value["published"] or p.get("observed") != value["source_checked_at"]
            or not isinstance(p.get("text"), str) or not 80 <= len(p["text"]) <= 6000 or not isinstance(p.get("issuer"), str)
            or p.get("sha256") != hashlib.sha256(p["text"].encode()).hexdigest() or p.get("disclosure") != disclosure(p["text"])
            or value.get("official") is not True or value.get("source") != "SEC EDGAR"
            or ("source_excerpt" in value and value["source_excerpt"] != p["text"])):
        raise ValueError("SEC filing proof does not match the candidate")
    ids = p["identity"]
    if (ids.get("DocumentType") != [p["form"]] or len(ids.get("EntityRegistrantName", [])) != 1
            or entity_key(ids["EntityRegistrantName"][0]) != entity_key(p["issuer"])
            or ids.get("EntityCentralIndexKey") not in ([cik], [cik.zfill(10)])
            or not isinstance(p.get("symbols"), list) or len(p["symbols"]) > 10
            or any(symbol not in ids.get("TradingSymbol", []) for symbol in p["symbols"])
            or not isinstance(value.get("symbols"), list) or any(symbol not in p["symbols"] for symbol in value["symbols"])):
        raise ValueError("SEC filing issuer proof changed")
    expected = f"{p['issuer']}: Form {p['form']} — {p['disclosure']['topic'] or 'current company report'}"
    published, observed = timestamp(p["published"]), timestamp(p["observed"])
    if value["title"] != expected or published is None or observed is None or (now and (not 0 <= (now-published).total_seconds() <= 86400 or not -60 <= (now-observed).total_seconds() <= 21600)):
        raise ValueError("SEC filing title or clocks unavailable or stale")
    return p


def narration(value: dict) -> str:
    p = checked(value)
    detail = p["disclosure"]
    text = ("The filing describes GPU equipment lease financing." if detail["gpu_lease"] else "Review the original current report for the disclosed financing terms.")
    for fact in detail["facts"]:
        text += " It reports expected aggregate principal payments of " + fact["value"] + " over the lease terms, rather than a single year's expense or revenue."
    if detail["conditional"]:
        text += " The disclosed plans include forward-looking or conditional terms; completion and timing require confirmation."
    return text + " Investor focus: review funding costs, contractual commitments, delivery timing and liquidity."
