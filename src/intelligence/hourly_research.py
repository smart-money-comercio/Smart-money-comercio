"""Hourly discovery/review handoff, original-source verification and durable audit."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.agents import research_agents
from src.intelligence.special_alert_sources import OFFICIAL_DOMAINS, timestamp
from src.intelligence.special_alert_company_sources import PublicationPage, publication_time
from src.intelligence.story_analysis import VisibleText
from src.intelligence import sec_research


ROOT = Path(__file__).resolve().parents[2]
AGENCIES = {"Federal Reserve": "federalreserve.gov", "U.S. Treasury": "treasury.gov", "EIA": "eia.gov", "DARPA": "darpa.mil",
            "BLS": "bls.gov", "BEA": "bea.gov", "DOL": "dol.gov"}
MAX_HELD_RETRIES = 3
MAX_RETRIES_PER_RUN = 2


def settings() -> dict:
    return {"enabled": os.getenv("HOURLY_RESEARCH_ENABLED", "true").lower().strip() not in {"0", "false", "no", "off"} and not paused(),
            "discovery_model": os.getenv("RESEARCH_DISCOVERY_MODEL", "gpt-5"),
            "review_model": os.getenv("RESEARCH_REVIEW_MODEL", "gpt-5")}


def state_path() -> Path:
    return Path(os.getenv("HOURLY_RESEARCH_STATE_FILE", str(ROOT / "data/hourly_research.sqlite3")))


def paused() -> bool:
    if not state_path().is_file(): return False
    try:
        with closing(sqlite3.connect(state_path().resolve().as_uri()+"?mode=ro", uri=True, timeout=2)) as db:
            row = db.execute("SELECT value FROM controls WHERE name='enabled'").fetchone()
        return bool(row and row[0] == "0")
    except sqlite3.Error:
        return True


def set_enabled(enabled: bool):
    with closing(connect()) as db, db:
        db.execute("INSERT OR REPLACE INTO controls VALUES ('enabled',?)", ("1" if enabled else "0",))


def identities() -> list[dict]:
    from src.intelligence.ipo_monitor import issuers
    values = [{"name": symbol, "symbol": symbol, "domain": domain, "kind": "company"}
              for symbol, domains in OFFICIAL_DOMAINS.items() for domain in domains]
    values += [{"name": name, "symbol": "", "domain": domain, "kind": "macro"} for name, domain in AGENCIES.items()]
    values += [{"name": row["name"], "symbol": "", "domain": row["domain"], "kind": "issuer"} for row in issuers().values()]
    return values


def identity(url: str) -> dict | None:
    url = research_agents.url_key(url)
    host = urlsplit(url).hostname
    return next((row for row in identities() if host == row["domain"] or host.endswith("." + row["domain"])), None)


def fetch_original(url: str) -> bytes:
    expected = identity(url)
    sec = sec_research.authority(url)
    if expected is None and not sec:
        raise ValueError("Original publisher is not configured")
    class Redirects(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            if (sec and (not sec_research.authority(newurl) or urlsplit(newurl).hostname != urlsplit(url).hostname)) or (not sec and identity(newurl) != expected):
                raise ValueError("Research source redirected outside its original publisher")
            return super().redirect_request(request, fp, code, msg, headers, newurl)
    agent = os.getenv("SEC_USER_AGENT", "SmartMoneyAI/1.7 public filing research") if sec else "SmartMoneyAI/1.7 original-source research"
    request = Request(url, headers={"User-Agent": agent, "Accept": "text/html,application/xhtml+xml,application/json"})
    with build_opener(Redirects()).open(request, timeout=10) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Original report exceeds research read limit")
    return body


def verified(lead: dict, now: datetime, fetch=fetch_original) -> dict:
    from src.intelligence import ipo_monitor
    url = research_agents.url_key(lead["url"])
    ipo = next((item for item in ipo_monitor.cached_items(now) if research_agents.url_key(item["url"]) == url), None)
    if ipo:
        return {**ipo, "kind": "macro", "publisher_symbol": "", "source_excerpt": ipo["ipo"]["excerpt"], "relevant": True}
    if urlsplit(url).hostname == "www.sec.gov":
        return sec_research.verify(url, now, fetch)
    publisher = identity(url)
    if publisher is None:
        raise ValueError("Lead requires an original configured publisher")
    body = fetch(url)
    if not isinstance(body, bytes) or len(body) > 2_000_000:
        raise ValueError("Invalid original report body")
    text = body.decode("utf-8", "replace")
    page = PublicationPage(); page.feed(text)
    if not page.title or len(page.title) > 1000:
        raise ValueError("Original report title unavailable")
    published = publication_time(body, page.title)
    if not 0 <= (now - published).total_seconds() <= 86400:
        raise ValueError("Original report outside the 24-hour publication window")
    if published.hour == published.minute == published.second == 0 and re.search(rb'<time[^>]+datetime=[\"\']\d{4}-\d{2}-\d{2}[\"\']', body):
        raise ValueError("Original report has a date-only clock")
    parser = VisibleText(); parser.feed(text)
    visible = " ".join("".join(parser.parts).split())[:6000]
    if not visible:
        raise ValueError("Original report text unavailable")
    proof = {"schema": 1, "url": url, "title": page.title, "published": published.isoformat(), "observed": now.isoformat(),
             "publisher": publisher, "text": visible, "sha256": hashlib.sha256(visible.encode()).hexdigest()}
    return {"title": page.title, "original_title": page.title, "url": url, "published": published.isoformat(),
            "source_checked_at": now.isoformat(), "source": publisher["name"], "official": True,
            "publisher_symbol": publisher["symbol"], "symbol": publisher["symbol"],
            "symbols": [publisher["symbol"]] if publisher["symbol"] else [],
            "kind": "company" if publisher["symbol"] else "macro", "relevant": True,
            "source_excerpt": visible, "excerpt_scope": "original release excerpt", "discovery_evidence": proof}


def check_proof(value: dict, now: datetime | None = None) -> dict:
    if value.get("ipo"):
        from src.intelligence.ipo_monitor import checked
        return checked(value, now)
    if value.get("sec_filing"):
        return sec_research.checked(value, now)
    proof = value["discovery_evidence"]
    publisher = identity(value["url"])
    if (not isinstance(proof, dict) or publisher is None or proof.get("schema") != 1 or proof.get("publisher") != publisher
            or value.get("official") is not True or value["source"] != publisher["name"]
            or proof.get("url") != value["url"] or proof.get("title") != value["title"]
            or proof.get("published") != value["published"] or proof.get("observed") != value["source_checked_at"]
            or ("source_excerpt" in value and value["source_excerpt"] != proof.get("text"))
            or value.get("publisher_symbol") != publisher["symbol"]
            or not isinstance(proof.get("text"), str) or len(proof["text"]) > 6000
            or proof.get("sha256") != hashlib.sha256(proof["text"].encode()).hexdigest()):
        raise ValueError("Original research proof does not match the candidate")
    published, observed = timestamp(proof["published"]), timestamp(proof["observed"])
    if published is None or observed is None or (now and (not 0 <= (now-published).total_seconds() <= 86400 or not -60 <= (now-observed).total_seconds() <= 21600)):
        raise ValueError("Original research clocks unavailable or stale")
    return publisher


def connect():
    path = state_path(); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=3)
    db.execute("CREATE TABLE IF NOT EXISTS runs (slot INTEGER PRIMARY KEY, started REAL, finished REAL, status TEXT, details TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS findings (slot INTEGER, candidate TEXT, payload TEXT, digest TEXT, PRIMARY KEY(slot,candidate))")
    db.execute("CREATE TABLE IF NOT EXISTS controls (name TEXT PRIMARY KEY,value TEXT)")
    return db


def claim(now: datetime) -> bool:
    slot = int(now.timestamp() // 3600)
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM runs WHERE slot=? OR (status='running' AND started>?)", (slot, now.timestamp()-600)).fetchone():
            return False
        db.execute("INSERT INTO runs VALUES (?,?,NULL,'running','{}')", (slot, now.timestamp()))
        db.execute("DELETE FROM findings WHERE slot<?", (slot-24*30,))
        db.execute("DELETE FROM runs WHERE slot<?", (slot-24*30,))
    return True


def finish(now: datetime, status: str, records: list[dict], details: dict):
    slot = int(now.timestamp() // 3600)
    with closing(connect()) as db, db:
        for record in records:
            raw = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False)
            if len(raw.encode()) > 80_000:
                raise ValueError("Research finding exceeds storage bound")
            db.execute("INSERT OR REPLACE INTO findings VALUES (?,?,?,?)", (slot, record["id"], raw, hashlib.sha256(raw.encode()).hexdigest()))
        db.execute("UPDATE runs SET finished=?,status=?,details=? WHERE slot=?", (datetime.now(timezone.utc).timestamp(), status, json.dumps(details), slot))


def read_history(limit: int = 40) -> list[dict]:
    path = state_path()
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=2)) as db:
        rows = db.execute("SELECT payload,digest FROM findings ORDER BY slot DESC LIMIT ?", (min(max(limit, 1), 80),)).fetchall()
    result = []
    for raw, digest in rows:
        if len(raw.encode()) > 80_000 or hashlib.sha256(raw.encode()).hexdigest() != digest:
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def latest_findings(records: list[dict]) -> dict[str, dict]:
    """Use the latest dated decision for each source, including SEC URL aliases."""
    result = {}
    for row in records:
        try:
            lead = row["lead"]
            url = research_agents.url_key(lead["url"])
            if (not isinstance(lead["title"], str) or not 1 <= len(lead["title"]) <= 1000
                    or lead["topic"] not in research_agents.TOPICS or row["id"] != hashlib.sha256(url.encode()).hexdigest()[:20]):
                continue
            result.setdefault(finding_key(url), row)
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return result


def retry_candidates(now: datetime, fresh: list[dict], history: list[dict]) -> list[dict]:
    """Read-only bounded follow-up queue; rechecks never change the first-seen clock."""
    current = {finding_key(lead["url"]) for lead in fresh}
    eligible = []
    for key, row in latest_findings(history).items():
        try:
            discovered = timestamp(row["discovered_at"])
            attempted = timestamp(row.get("last_attempt_at", row["discovered_at"]))
            retries = row.get("retry_count", 0)
            if (key in current or row["review"]["final"] != "hold" or discovered is None or attempted is None
                    or not 0 <= (now-discovered).total_seconds() <= 86400
                    or int(attempted.timestamp() // 3600) >= int(now.timestamp() // 3600)
                    or type(retries) is not int or not 0 <= retries < MAX_HELD_RETRIES):
                continue
            if row.get("verified"):
                published = timestamp(row["verified"].get("published"))
                if published is None or not 0 <= (now-published).total_seconds() <= 86400:
                    continue
            eligible.append((attempted, row))
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError, OSError):
            continue
    eligible.sort(key=lambda item: item[0])
    room = min(MAX_RETRIES_PER_RUN, max(0, 8-len(fresh)))
    return [row for _, row in eligible[:room]]


def approved(now: datetime) -> list[dict]:
    if not settings()["enabled"]:
        return []
    try:
        records = read_history()
    except (OSError, sqlite3.Error, ValueError):
        return []
    result, seen = [], set()
    for record in records:
        try:
            value, decision = record["verified"], record["review"]
            url = record["lead"]["url"]
            key = finding_key(url)
            if key in seen:
                continue
            seen.add(key)
            if decision["final"] != "approved" or not value:
                continue
            check_proof(value, now)
            canonical = finding_key(value["url"])
            if canonical != key and canonical in seen:
                continue
            quote = decision["evidence_quote"]
            source_text = value.get("source_excerpt", "")
            if len(quote) < 20 or quote not in source_text or not record.get("review_response_id"):
                continue
            result.append({**value, "origin": "Hourly AI research review"})
            seen.add(canonical)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return result[:8]


def status() -> dict:
    path = state_path()
    if not path.is_file():
        return {"status": "not run", "details": {}}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=2)) as db:
            row = db.execute("SELECT started,status,details FROM runs ORDER BY slot DESC LIMIT 1").fetchone()
        return {"started": datetime.fromtimestamp(row[0], timezone.utc).isoformat(), "status": row[1], "details": json.loads(row[2])} if row else {"status": "not run", "details": {}}
    except (OSError, sqlite3.Error, ValueError):
        return {"status": "unavailable", "details": {}}


def run(now: datetime | None = None, *, client=None, fetch=fetch_original) -> dict:
    now = now or datetime.now(timezone.utc)
    config = settings()
    if not config["enabled"]:
        return {"status": "disabled"}
    previous = status().get("started", "")
    if not claim(now):
        return {"status": "already attempted this hour"}
    details, records, owned = {"agents": [], "candidates": 0, "approved": 0}, [], False
    try:
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is unavailable")
            from openai import OpenAI
            client = OpenAI(timeout=45, max_retries=0); owned = True
        from src.config.special_alerts import settings as alert_settings
        from src.intelligence.special_alert_universe import company_universe
        symbols = company_universe(alert_settings(), now)["symbols"]
        domains = list(dict.fromkeys(row["domain"] for row in identities())) + ["reuters.com", "apnews.com", "sec.gov"]
        history = read_history(80)
        latest = latest_findings(history)
        seen_urls = [row["lead"]["url"] for row in latest.values() if row.get("review", {}).get("final") in {"approved", "skip"}][:16]
        leads, metadata = research_agents.discover(client, config["discovery_model"], now.isoformat(), symbols, domains, previous, seen_urls)
        details["agents"].append(metadata)
        fresh = {}
        for lead in leads:
            fresh.setdefault(finding_key(lead["url"]), lead)
        leads = list(fresh.values())
        pending = retry_candidates(now, leads, history)
        work = [(row["lead"], row, True) for row in pending] + [(lead, latest.get(finding_key(lead["url"])), False) for lead in leads]
        details.update(candidates=len(work), search_leads=len(leads), retried=len(pending))
        reads = 0
        def bounded_fetch(url):
            nonlocal reads
            if reads >= 6:
                raise ValueError("Original-source read budget reached")
            reads += 1
            return fetch(url)
        for lead, parent, retry in work:
            first_seen = timestamp(parent.get("discovered_at")) if parent else None
            count = parent.get("retry_count", 0) if parent else 0
            count = count if type(count) is int and 0 <= count <= MAX_HELD_RETRIES else 0
            record = {"id": hashlib.sha256(lead["url"].encode()).hexdigest()[:20],
                      "discovered_at": first_seen.isoformat() if first_seen is not None and first_seen <= now else now.isoformat(),
                      "last_attempt_at": now.isoformat(), "retry_count": count + int(retry), "origin": "held retry" if retry else "discovery",
                      "discovery_response_id": (parent or {}).get("discovery_response_id", "") if retry else details["agents"][0]["response_id"],
                      "prior_review_response_id": (parent or {}).get("review_response_id", ""), "lead": lead,
                      "verified": None, "verification": "Original source not verified", "review": {"final": "hold"}}
            excluded = routine_page(lead["url"])
            if excluded:
                record["verification"] = excluded
                record["review"] = {"final": "skip", "reason": excluded}
                record["screened_out"] = True
            else:
                try:
                    record["verified"] = verified(lead, now, bounded_fetch); record["verification"] = "Original source verified"
                except Exception as exc:
                    from urllib.error import HTTPError
                    reason = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else str(exc)[:180] if isinstance(exc, ValueError) else type(exc).__name__
                    record["verification"] = "Original source unavailable: " + reason
            records.append(record)
        details["original_reads"] = reads
        reviewable = [row for row in records if not row.get("screened_out")]
        if reviewable:
            handoff = [{"id": row["id"], "title": (row["verified"] or row["lead"])["title"], "topic": row["lead"]["topic"],
                        "url": row["lead"]["url"], "published": (row["verified"] or {}).get("published", "unverified"),
                        "verification": row["verification"], "lead_origin": row["origin"],
                        "source_text": (row["verified"] or {}).get("source_excerpt", "")} for row in reviewable]
            decisions, metadata = research_agents.review(client, config["review_model"], handoff, symbols)
            details["agents"].append(metadata)
            by_id = {row["id"]: row for row in records}
            for decision in decisions:
                record = by_id[decision["id"]]
                evidence = (record["verified"] or {}).get("source_excerpt", "")
                eligible = bool(record["verified"] and 20 <= len(decision["evidence_quote"]) <= 500 and decision["evidence_quote"] in evidence)
                final = "approved" if decision["decision"] == "accept" and decision["score"] >= 65 and eligible else "skip" if decision["decision"] == "skip" else "hold"
                record["review"] = {**decision, "final": final}
                record["review_response_id"] = metadata["response_id"]
        details.update(approved=sum(row["review"]["final"] == "approved" for row in records),
            source_verified=sum(row["verified"] is not None for row in records),
            held=sum(row["review"]["final"] == "hold" for row in records), skipped=sum(row["review"]["final"] == "skip" for row in records))
        final_status = "complete" if settings()["enabled"] else "paused"
        finish(now, final_status, records, details)
    except Exception as exc:
        details["error"] = type(exc).__name__
        for record in records:
            if not record.get("screened_out"):
                record["review"] = {"final": "hold", "reason": "AI review incomplete; publication withheld"}
        finish(now, "limited", records, details)
    finally:
        if owned:
            client.close()
    return status()


def summary() -> str:
    value = status()
    details = value.get("details", {})
    return (f"Hourly Research Desk: {value['status']}; {details.get('search_leads', details.get('candidates', 0))} search leads, "
            f"{details.get('retried', 0)} held leads revisited, {details.get('approved', 0)} approved, "
            f"{details.get('source_verified', 0)} source-verified. Cached review only.")


def routine_page(url: str) -> str:
    p = urlsplit(url)
    if (p.hostname or "").split(".")[0] in {"help", "support", "docs", "developers"} or re.match(r"^/(?:help|docs|documentation|support|careers|jobs|pricing)(?:/|$)", p.path, re.I):
        return "Routine help, documentation or service page; no investor report established"
    return ""


def finding_key(url: str) -> str:
    try:
        cik, accession, _ = sec_research.location(url)
        return "sec:" + cik + ":" + accession
    except (ValueError, TypeError):
        return url


def context_provider():
    from src.intelligence.intelligence_context_registry import IntelligenceContextBlock
    items = approved(datetime.now(timezone.utc))
    if not items: return None
    return IntelligenceContextBlock(feature="Hourly AI Research", priority=106,
        signal="; ".join(value["title"] for value in items[:2])[:500],
        implication="A separate AI relevance review approved these original-source findings for research.",
        validation="Confirm the original disclosures and current price/volume before changing conviction.",
        symbols=list(dict.fromkeys(symbol for value in items for symbol in value.get("symbols", []))),
        commands=["/researchdesk history", "/storylog"], metadata={"score_changes": False, "findings": len(items), "model_roles": 2})
