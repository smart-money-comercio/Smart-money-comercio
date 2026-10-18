"""Dated, public research records. Raw PDFs and private account data stay outside this store."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
CLAIM_TYPES = {"observation", "estimate", "forecast", "opinion"}
EVIDENCE_STATES = {"source_reported", "corroborated", "ambiguous", "contradicted", "superseded"}
KINDS = {"quarterly_report", "research_note", "newsletter", "article_preview"}
BLOCKED_STATES = {"ambiguous", "contradicted", "superseded"}
PRIVATE_PATTERN = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b(?:account\s*(?:number|#)|dividends received|trades made|your portfolio balance)\b",
    re.I,
)


class ResearchError(ValueError):
    """Invalid input; messages deliberately omit source text and personal values."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str | datetime | date) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, datetime.min.time())
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise ResearchError("Invalid research date.") from None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def clean_text(value, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ResearchError("Missing or oversized research text field.")
    result = " ".join(value.split())
    if PRIVATE_PATTERN.search(result):
        raise ResearchError("Personal account or contact data cannot enter public research.")
    return result


def store_path() -> Path:
    return Path(os.getenv("RESEARCH_STORE_FILE", str(PROJECT_ROOT / "data/research/public_store.json")))


def seed_directory() -> Path:
    return Path(os.getenv("RESEARCH_SEED_DIR", str(PROJECT_ROOT / "resources/research")))


def validate_document(value: dict, now: datetime | None = None) -> dict:
    """Allowlisted fields prevent arbitrary raw/private fields from being persisted."""
    now = parse_time(now or utc_now())
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ResearchError("Unsupported research manifest schema.")
    if value.get("visibility") != "public_research" or value.get("reviewed") is not True:
        raise ResearchError("Only reviewed public-research manifests are supported.")
    source = value.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or source["kind"] not in KINDS:
        raise ResearchError("Unsupported or private research source kind.")
    digest = source.get("sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ResearchError("Research source requires its SHA-256 content hash.")
    completeness = source.get("completeness")
    if not isinstance(completeness, str) or completeness not in {"full", "partial"}:
        raise ResearchError("Research source completeness must be full or partial.")
    pages = source.get("page_count")
    if type(pages) is not int or not 1 <= pages <= 500:
        raise ResearchError("Invalid research page count.")
    source_out = {
        "sha256": digest,
        "label": clean_text(source.get("label"), 80),
        "title": clean_text(source.get("title"), 220),
        "publisher": clean_text(source.get("publisher"), 100),
        "kind": source["kind"], "completeness": completeness, "page_count": pages,
    }
    published = source.get("published_at")
    source_out["published_at"] = parse_time(published).isoformat() if published else None
    period = source.get("period")
    if period is not None and not re.fullmatch(r"Q[1-4] \d{4}", str(period)):
        raise ResearchError("Invalid research reporting period.")
    source_out["period"] = period
    issues = []
    blocked_pages = set()
    raw_issues = value.get("issues", [])
    if not isinstance(raw_issues, list) or len(raw_issues) > 100:
        raise ResearchError("Invalid research issue collection.")
    for issue in raw_issues:
        if not isinstance(issue, dict):
            raise ResearchError("Invalid research issue.")
        issue_pages = issue.get("pages", [])
        if not isinstance(issue_pages, list) or any(type(p) is not int or not 1 <= p <= pages for p in issue_pages):
            raise ResearchError("Invalid research issue pages.")
        code = issue.get("code")
        if not isinstance(code, str) or code not in {"period_conflict", "incomplete_source", "date_ambiguity"}:
            raise ResearchError("Unsupported research issue code.")
        normalized_issue = {"code": code, "pages": sorted(set(issue_pages))}
        if normalized_issue not in issues:
            issues.append(normalized_issue)
        if code == "period_conflict":
            blocked_pages.update(issue_pages)
    claims = value.get("claims", [])
    if not isinstance(claims, list) or len(claims) > 100:
        raise ResearchError("Invalid research claim collection.")
    normalized = []
    seen = set()
    for claim in claims:
        if not isinstance(claim, dict):
            raise ResearchError("Invalid research claim.")
        kind = claim.get("type")
        state = claim.get("evidence_status")
        if not isinstance(kind, str) or kind not in CLAIM_TYPES or not isinstance(state, str) or state not in EVIDENCE_STATES:
            raise ResearchError("Research claims require a type and evidence status.")
        text = clean_text(claim.get("text"), 340)
        claim_pages = claim.get("pages")
        if not isinstance(claim_pages, list) or not claim_pages or any(type(p) is not int or not 1 <= p <= pages for p in claim_pages):
            raise ResearchError("Research claims require valid source pages.")
        as_of = parse_time(claim.get("as_of", ""))
        expires = parse_time(claim.get("expires_at", ""))
        maximum_days = 90 if source["kind"] == "quarterly_report" else 14
        if kind == "forecast":
            maximum_days = min(maximum_days, 14)
        if expires <= as_of or expires > as_of + timedelta(days=maximum_days):
            raise ResearchError("Research expiry must fit its source and claim horizon.")
        event_id = clean_text(claim.get("event_id"), 100)
        symbols = claim.get("symbols", [])
        themes = claim.get("themes", [])
        if not isinstance(symbols, list) or len(symbols) > 30 or any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,7}", s) for s in symbols):
            raise ResearchError("Invalid research symbols.")
        if not isinstance(themes, list) or len(themes) > 8:
            raise ResearchError("Invalid research themes.")
        themes = [clean_text(t, 60) for t in themes]
        scope = claim.get("scope", "symbols")
        if not isinstance(scope, str) or scope not in {"market", "symbols"} or (scope == "symbols" and not symbols):
            raise ResearchError("Research requires an explicit market or symbol scope.")
        # No numeric metric enters this explanatory v1 store, especially from previews.
        if any(claim.get(k) is not None for k in ("value", "return_percent", "metric")):
            raise ResearchError("Quantitative metrics are outside the v1 explanatory import.")
        if set(claim_pages) & blocked_pages:
            state = "ambiguous"
        if completeness != "full" or source["kind"] == "article_preview":
            state = "ambiguous"
        known_at = parse_time(claim.get("known_at") or value.get("known_at") or now)
        # The publication date also gates availability; an earlier supplied known_at cannot bypass it.
        if published:
            known_at = max(known_at, parse_time(published))
        key = hashlib.sha256((digest + "|" + event_id + "|" + text).encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "id": key, "text": text, "type": kind, "evidence_status": state,
            "pages": sorted(set(claim_pages)), "as_of": as_of.isoformat(),
            "expires_at": expires.isoformat(), "known_at": known_at.isoformat(),
            "event_id": event_id, "symbols": sorted(set(symbols)), "themes": themes, "scope": scope,
        })
    return {"schema_version": SCHEMA_VERSION, "id": digest, "visibility": "public_research",
            "reviewed": True, "source": source_out, "issues": issues, "claims": normalized,
            "known_at": parse_time(value.get("known_at") or now).isoformat()}


def read_documents(path: Path | None = None, seeds: Path | None = None) -> list[dict]:
    """No network or writes on the Telegram rendering path."""
    path = Path(path) if path is not None else store_path()
    seeds = Path(seeds) if seeds is not None else seed_directory()
    documents = {}
    try:
        if seeds.is_dir():
            for manifest in sorted(seeds.glob("*.json")):
                item = validate_document(json.loads(manifest.read_text(encoding="utf-8-sig")))
                documents[item["id"]] = item
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("documents"), list):
                raise ResearchError("Invalid public research store.")
            for value in data["documents"]:
                item = validate_document(value)
                documents[item["id"]] = item
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ResearchError("Research storage is unreadable; existing records were preserved.") from None
    return list(documents.values())


@contextmanager
def store_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ResearchError("Another research import is running; retry after it completes.") from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def write_documents(documents: list[dict], path: Path) -> None:
    """Atomic replacement preserves the last good file if serialization or writing fails."""
    normalized = [validate_document(document) for document in documents]
    content = json.dumps({"schema_version": SCHEMA_VERSION, "documents": normalized}, indent=2, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".research-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def import_document(value: dict, path: Path | None = None, seeds: Path | None = None) -> dict:
    now = utc_now()
    candidate = validate_document(value, now)
    path = Path(path) if path is not None else store_path()
    with store_lock(path):
        documents = read_documents(path, seeds)
        previous = next((d for d in documents if d["id"] == candidate["id"]), None)
        if previous:
            # Reimport cannot rewrite when existing evidence was first known or add signal weight.
            known = {c["id"]: c["known_at"] for c in previous["claims"]}
            candidate["known_at"] = previous["known_at"]
            for claim in candidate["claims"]:
                claim["known_at"] = known.get(claim["id"], now.isoformat())
            if candidate == previous:
                return {"changed": False, "documents": len(documents), "claims": len(candidate["claims"])}
        # Runtime imports cannot claim to have been known before the import.
        else:
            candidate["known_at"] = now.isoformat()
            for claim in candidate["claims"]:
                claim["known_at"] = max(parse_time(claim["known_at"]), now).isoformat()
        documents = [d for d in documents if d["id"] != candidate["id"]] + [candidate]
        write_documents(documents, path)
        return {"changed": True, "documents": len(documents), "claims": len(candidate["claims"])}


def eligible_claims(documents: list[dict], now: datetime | None = None, symbol: str = "") -> tuple[list[dict], dict]:
    now = parse_time(now or utc_now())
    symbol = str(symbol or "").strip().upper().replace("$", "")
    counts = {"expired": 0, "withheld": 0, "future": 0}
    active = []
    for document in documents:
        document = validate_document(document, now)
        for claim in document["claims"]:
            if claim["evidence_status"] in BLOCKED_STATES:
                counts["withheld"] += 1
                continue
            if parse_time(claim["known_at"]) > now or parse_time(claim["as_of"]) > now:
                counts["future"] += 1
                continue
            if parse_time(claim["expires_at"]) <= now:
                counts["expired"] += 1
                continue
            if symbol and claim["scope"] != "market" and symbol not in claim["symbols"]:
                continue
            row = deepcopy(claim)
            row["source"] = deepcopy(document["source"])
            active.append(row)
    # Several publishers repeating an event do not supply independent signal weight.
    active.sort(key=lambda c: (bool(symbol and symbol in c["symbols"]), c["evidence_status"] == "corroborated", c["as_of"]), reverse=True)
    unique = {}
    for claim in active:
        unique.setdefault(claim["event_id"], claim)
    return list(unique.values()), counts
