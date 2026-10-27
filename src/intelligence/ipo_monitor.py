"""Original-source IPO milestones, including issuers without a trading ticker."""

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from urllib.parse import urlsplit

from src.intelligence.special_alert_sources import clean, timestamp
from src.intelligence.story_analysis import VisibleText


ROOT = Path(__file__).resolve().parents[2]
LOCK = RLock()
DEFAULT_ISSUERS = {
    "anthropic": {"name": "Anthropic", "domain": "anthropic.com", "cik": "2130357", "index": "https://www.anthropic.com/news"},
    "openai": {"name": "OpenAI", "domain": "openai.com", "feed": "https://openai.com/news/rss.xml"},
}
STAGES = {"plan": "Company IPO plan announced", "confidential": "Confidential draft submission announced",
          "filing": "Public IPO registration filed", "amendment": "Public IPO registration amended",
          "terms": "Indicative IPO price range announced",
          "prospectus": "Final IPO prospectus filed", "priced": "IPO pricing announced",
          "trading planned": "Trading start planned", "trading": "Trading start reported", "withdrawn": "Offering withdrawn"}
FORMS = {"S-1": "filing", "F-1": "filing", "S-1/A": "amendment", "F-1/A": "amendment", "424B4": "prospectus"}
IPO_WORDS = re.compile(r"\b(initial public offering|IPO|S-1|F-1)\b", re.I)


def issuers() -> dict:
    values = dict(DEFAULT_ISSUERS)
    try:
        extra = json.loads(os.getenv("AI_IPO_ISSUERS_JSON", "{}"))
        if not isinstance(extra, dict):
            raise ValueError("IPO issuers must be an object")
        values.update(extra)
        result = {}
        for key, row in list(values.items())[:10]:
            if not re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", key) or not isinstance(row, dict):
                raise ValueError("Invalid IPO issuer")
            if not isinstance(row.get("name"), str) or not 1 <= len(row["name"]) <= 70 or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", row.get("domain", "")):
                raise ValueError("Invalid IPO issuer identity")
            if row.get("cik") and not re.fullmatch(r"\d{1,10}", str(row["cik"])):
                raise ValueError("Invalid IPO issuer CIK")
            if not any(row.get(field) for field in ("cik", "feed", "index")):
                raise ValueError("IPO issuer has no original reader")
            for field in ("feed", "index"):
                if row.get(field) and not issuer_url(row, row[field]):
                    raise ValueError("IPO reader must belong to its issuer")
            result[key] = row
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("AI_IPO_ISSUERS_JSON is invalid") from exc


def issuer_url(row: dict, url: str) -> bool:
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        return p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and (host == row["domain"] or host.endswith("." + row["domain"]))
    except (ValueError, TypeError):
        return False


def cache_path() -> Path:
    return Path(os.getenv("AI_IPO_CACHE_FILE", str(ROOT / "data/ai_ipo_cache.json")))


def visible(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    parser = VisibleText()
    parser.feed(raw[:1_000_000])
    return " ".join("".join(parser.parts).split())[:100_000]


def company_stage(title: str) -> str | None:
    if not IPO_WORDS.search(title) or re.search(r"\b(rumou?r\w*|reportedly|might|could|may|expected to|considering|denies|not|no|how|why)\b|\?", title, re.I):
        return None
    if re.search(r"\b(funding round|private funding|private placement|venture round|pre-IPO funding)\b", title, re.I):
        return None
    if re.search(r"\b(withdraw\w*|cancel\w*)\b", title, re.I):
        return "withdrawn"
    if re.search(r"\b(confidential\w*)\b", title, re.I) and re.search(r"\b(submit\w*|fil\w*)\b", title, re.I):
        return "confidential"
    if re.search(r"\bprice range\b", title, re.I):
        return "terms"
    if re.search(r"\b(pric(?:es|ed|ing))\b", title, re.I):
        return "priced"
    if re.search(r"\b(begins? trading|starts? trading|trading begins|trading starts)\b", title, re.I):
        return "trading planned" if re.search(r"\b(will|to|plans?|scheduled)\b", title, re.I) else "trading"
    if re.search(r"\b(fil(?:es|ed|ing)|submits?|submitted)\b", title, re.I):
        return "filing"
    if re.search(r"\b(announc\w*|plans?|proposed)\b", title, re.I):
        return "plan"
    return None


def item(issuer_id: str, row: dict, title: str, url: str, published: str, excerpt: str,
         observed: str, *, form: str = "", accession: str = "") -> dict | None:
    publication, observation = timestamp(published), timestamp(observed)
    if publication is None or observation is None:
        return None
    published, observed = publication.isoformat(), observation.isoformat()
    excerpt = clean(excerpt, 6000)
    stage = company_stage(title)
    if not form:
        if (not re.search(r"\b" + re.escape(row["name"]) + r"\b|\bour\b", title, re.I)
                or re.search(r"\b(invests?|investing|investment in|participat\w*|customer|portfolio company)\b", title, re.I)
                or any(other["name"] != row["name"] and re.search(r"\b" + re.escape(other["name"]) + r"\b", title, re.I) for other in issuers().values())):
            return None
    if form:
        # S-1/F-1 alone can also register resale securities. Require the IPO face.
        if form not in FORMS or not re.search(r"\bthis is (?:an|the) initial public offering\b", excerpt, re.I):
            return None
        stage = FORMS[form]
        if form == "424B4" and re.search(r"\binitial public offering price is \$\d+(?:\.\d+)? per share\b", excerpt, re.I):
            stage = "priced"
    if stage is None:
        return None
    symbol = re.search(r"\bunder (?:the )?(?:trading )?symbol\s+[\"“']([A-Z][A-Z0-9.\-]{0,9})[\"”']", excerpt)
    profile = {"schema": 1, "issuer_id": issuer_id, "stage": stage, "form": form, "accession": accession,
               "source_url": url, "published": published, "observed": observed, "title": title,
               "excerpt": excerpt, "sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
               "proposed_symbol": symbol[1].rstrip(".") if symbol else ""}
    return {"title": title, "original_title": title, "url": url, "published": published,
            "source_checked_at": observed, "official": True, "source": "SEC EDGAR" if form else row["name"],
            "kind": "ipo", "symbols": [], "ipo": profile}


def checked(value: dict, now: datetime | None = None, hours: float = 24) -> dict:
    p = value["ipo"]
    row = issuers()[p["issuer_id"]]
    if p.get("schema") != 1 or p.get("stage") not in STAGES or not isinstance(value.get("title"), str) or len(value["title"]) > 1000:
        raise ValueError("Invalid IPO evidence")
    published, observed = timestamp(value["published"]), timestamp(value["source_checked_at"])
    if published is None or observed is None:
        raise ValueError("Original IPO publication clock unavailable")
    if now and (not 0 <= (now - published).total_seconds() <= hours * 3600 or not -60 <= (now - observed).total_seconds() <= 6 * 3600):
        raise ValueError("IPO evidence is stale or future-dated")
    form, accession = p["form"], p["accession"]
    if form:
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not row.get("cik"):
            raise ValueError("SEC accession unavailable")
        parts = urlsplit(value["url"])
        prefix = f"/Archives/edgar/data/{int(row['cik'])}/{accession.replace('-', '')}/"
        if parts.scheme != "https" or parts.netloc != "www.sec.gov" or not parts.path.startswith(prefix) or parts.query or parts.fragment or "/../" in parts.path:
            raise ValueError("IPO filing does not belong to the configured issuer")
    elif not issuer_url(row, value["url"]):
        raise ValueError("IPO announcement is not an original issuer source")
    expected = item(p["issuer_id"], row, value["title"], value["url"], value["published"], p["excerpt"], value["source_checked_at"], form=form, accession=accession)
    if expected is None or expected["ipo"] != p or value.get("official") is not True or value.get("source") != expected["source"]:
        raise ValueError("IPO stage or terms changed from the original evidence")
    return row


def sec_items(issuer_id: str, row: dict, raw: bytes, request, now: datetime, hours: float) -> list[dict]:
    payload = json.loads(raw)
    if int(payload["cik"]) != int(row["cik"]):
        raise ValueError("SEC issuer identity mismatch")
    recent = payload["filings"]["recent"]
    records = zip(recent["form"], recent["acceptanceDateTime"], recent["accessionNumber"], recent["primaryDocument"])
    result, reads = [], 0
    for form, accepted, accession, document in list(records)[:100]:
        published = timestamp(accepted)
        if form not in FORMS or published is None or not 0 <= (now - published).total_seconds() <= hours * 3600:
            continue
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[A-Za-z0-9._-]+\.html?", document):
            raise ValueError("Invalid SEC filing location")
        if reads >= 2:
            break
        url = f"https://www.sec.gov/Archives/edgar/data/{int(row['cik'])}/{accession.replace('-', '')}/{document}"
        body = visible(request(url, prefix=True))
        reads += 1
        match = re.search(r"\bthis is (?:an|the) initial public offering\b", body[:20_000], re.I)
        if match is None:
            continue
        excerpt = body[max(0, match.start() - 500):match.start() + 4500]
        title = f"{row['name']}: Form {form} filed for a proposed initial public offering"
        record = item(issuer_id, row, title, url, published.isoformat(), excerpt, now.isoformat(), form=form, accession=accession)
        if record:
            result.append(record)
    return result


def company_items(issuer_id: str, row: dict, request, now: datetime, hours: float) -> list[dict]:
    from src.intelligence.news_live_sources import parse_rss_items
    from src.intelligence.news_original_sources import ReleaseLinks
    from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
    result, undated = [], 0
    if row.get("feed"):
        entries = parse_rss_items(request(row["feed"]).decode("utf-8"), {"name": row["name"]}, full_titles=True, full_text=True)
        for entry in entries[:30]:
            if not issuer_url(row, entry["link"]):
                continue
            record = item(issuer_id, row, entry["title"], entry["link"], entry["published"], entry["description"], now.isoformat())
            if record:
                result.append(record)
    elif row.get("index"):
        parser = ReleaseLinks(row["index"], r"/news/[a-z0-9-]+")
        parser.feed(request(row["index"]).decode("utf-8"))
        links = list(dict.fromkeys(entry["link"] for entry in parser.rows if IPO_WORDS.search(entry["title"]) or re.search(r"(?:ipo|s1|public-offering)", entry["link"])))[:2]
        for url in links:
            body = request(url)
            page = PublicationPage(); page.feed(body.decode("utf-8"))
            try:
                published = publication_time(body, page.title)
            except ValueError:
                undated += 1
                continue
            # Do not promote a publisher's date-only midnight placeholder to a clock.
            if published.hour == published.minute == published.second == 0 and re.search(rb'<time[^>]+datetime="\d{4}-\d{2}-\d{2}"', body):
                undated += 1
                continue
            record = item(issuer_id, row, page.title, url, published.isoformat(), visible(body.decode("utf-8")), now.isoformat())
            if record:
                result.append(record)
    if undated and not result:
        raise ValueError("Original IPO publication clock unverified")
    return [value for value in result if timestamp(value["published"]) and 0 <= (now - timestamp(value["published"])).total_seconds() <= hours * 3600]


def read_cache() -> dict:
    try:
        path = cache_path()
        if path.stat().st_size > 2_000_000:
            return {}
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if (isinstance(value, dict) and value.get("schema") == 1 and isinstance(value.get("items"), list)
                         and isinstance(value.get("status"), str) and isinstance(value.get("issues"), list)
                         and all(isinstance(issue, str) for issue in value["issues"])) else {}
    except (OSError, ValueError):
        return {}


def cached_items(now: datetime, hours: float = 24) -> list[dict]:
    result = []
    values = read_cache().get("items", [])
    for value in (values[:40] if isinstance(values, list) else []):
        try:
            checked(value, now, hours)
            result.append(value)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
    # Keep one current milestone per issuer; older stages remain in delivery/history.
    progression = {stage: index for index, stage in enumerate(("plan", "confidential", "filing", "amendment", "terms", "prospectus", "priced", "trading planned", "trading", "withdrawn"))}
    latest = {}
    for value in result:
        issuer_id = value["ipo"]["issuer_id"]
        key = lambda item: (progression[item["ipo"]["stage"]], timestamp(item["published"]), bool(item["ipo"]["form"]))
        if issuer_id not in latest or key(value) > key(latest[issuer_id]):
            latest[issuer_id] = value
    return list(latest.values())


def collect(now: datetime, config: dict, request) -> tuple[list[dict], str, list[str]]:
    if not config.get("ipo_enabled", False):
        return [], "disabled", []
    with LOCK:
        old = read_cache()
        retry = old.get("retry_at")
        if type(retry) in (int, float) and math.isfinite(retry) and now.timestamp() < retry <= now.timestamp() + 3600:
            return cached_items(now, config["ipo_hours"]), old.get("status", "cached"), old.get("issues", [])
        records, details, issues = [], [], []
        backoff = old.get("backoff", {})
        if not isinstance(backoff, dict):
            backoff = {}
        for issuer_id, row in issuers().items():
            for mode in ("SEC", "company"):
                if mode == "SEC" and not row.get("cik") or mode == "company" and not (row.get("feed") or row.get("index")):
                    continue
                key = issuer_id + ":" + mode
                previous = backoff.get(key, {})
                until = previous.get("until") if isinstance(previous, dict) else None
                if type(until) in (int, float) and math.isfinite(until) and now.timestamp() < until <= now.timestamp() + 3600 and isinstance(previous.get("reason"), str):
                    details.append(previous["reason"] + " (retry pending)")
                    issues.append("AI IPO — " + previous["reason"] + " (retry pending)")
                    continue
                try:
                    if mode == "SEC":
                        raw = request(f"https://data.sec.gov/submissions/CIK{int(row['cik']):010d}.json")
                        values = sec_items(issuer_id, row, raw, request, now, config["ipo_hours"])
                    else:
                        values = company_items(issuer_id, row, request, now, config["ipo_hours"])
                    records += values
                    backoff.pop(key, None)
                    details.append(f"{row['name']} {mode}: {len(values)} qualifying milestones")
                except Exception as exc:
                    code = getattr(exc, "code", None)
                    issue = f"{row['name']} {mode}: HTTP {code}" if code else f"{row['name']} {mode}: {type(exc).__name__} ({clean(str(exc), 100)})"
                    details.append(issue); issues.append("AI IPO — " + issue)
                    backoff[key] = {"until": now.timestamp() + 900, "reason": issue}
        unique = {value["url"]: value for value in cached_items(now, config["ipo_hours"]) + records}
        state = {"schema": 1, "checked_at": now.isoformat(), "retry_at": now.timestamp() + 300, "backoff": backoff,
                 "items": list(unique.values())[-40:], "status": "; ".join(details), "issues": issues}
        path = cache_path(); temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
                temporary = file.name; json.dump(state, file)
            if path.exists():
                os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return cached_items(now, config["ipo_hours"]), state["status"], issues


def interpretation(value: dict) -> str:
    stage = value["ipo"]["stage"]
    if stage == "trading":
        return "Trading has been reported by the issuer. Review liquidity, valuation, dilution and lockup terms before considering a position."
    return "This is an IPO milestone; public trading and an investable entry are not established. Review valuation, losses, cash needs, dilution and governance in the original disclosures."


def alert(value: dict, now: datetime, config: dict) -> dict | None:
    try:
        row = checked(value, now, config.get("ipo_hours", 24))
        stage = value["ipo"]["stage"]
        published = timestamp(value["published"])
        proposed = value["ipo"]["proposed_symbol"]
        text = ["🔔 AI IPO Alert — " + row["name"], "Stage: " + STAGES[stage],
                "Evidence: " + ("Public SEC filing; acceptance timestamp" if value["ipo"]["form"] else "Original company announcement"),
                "Headline: " + value["title"], "Published: " + published.strftime("%Y-%m-%d %H:%M UTC"), value["url"]]
        if proposed:
            text.append("Symbol described in the source: " + proposed + "; trading status requires separate confirmation.")
        text += ["Price, valuation and trading date: verify the latest original offering terms.", "", "Investor lens: " + interpretation(value),
                 "Portfolio lens: Review AI/cloud concentration and competing capital needs; no direct portfolio exposure or market cause is inferred.", "Next: /specialalerts history · /storylog · /fullreport"]
        return {"key": f"ipo:{value['ipo']['issuer_id']}:{published.year}:{stage}", "level": 1, "kind": "ipo", "event_type": "ipo",
                "published": published.isoformat(), "text": "\n".join(text), "ttl": 30 * 86400,
                "symbols": [], "stage": stage, "evidence": value, "expires": published.timestamp() + config.get("ipo_hours", 24) * 3600}
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None
