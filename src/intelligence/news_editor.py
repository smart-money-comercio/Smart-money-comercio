"""Inspect source facts, select diverse stories and preserve editorial decisions."""

from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.intelligence import news_live_sources as feeds, news_editor_store as store
from src.intelligence.special_alert_sources import clean


MAX_STORIES = 3
MAX_CANDIDATES = 180
MAX_CACHE_BYTES = 3_000_000
MAX_CACHE_AGE = 6 * 3600
MAX_NEWS_AGE = 24 * 3600
OFFICIAL_HOSTS = {"Federal Reserve": "federalreserve.gov", "U.S. Treasury": "treasury.gov", "EIA": "eia.gov"}
ALIASES = {**feeds.TICKER_TERMS, "TSM": ["TSM", "TSMC", "Taiwan Semiconductor"],
           "NOC": ["NOC", "Northrop Grumman"], "LMT": ["LMT", "Lockheed Martin"],
           "AVAV": ["AVAV", "AeroVironment"], "KTOS": ["KTOS", "Kratos"], "CRWD": ["CRWD", "CrowdStrike"],
           "CACI": ["CACI"], "GOOG": ["GOOG", "Google", "Alphabet"]}
STAGE_NAMES = ("Scan", "Source Check", "Relevance", "Selection", "Editorial Review", "Decision Log")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def dated(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Original publication time unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise ValueError("Original publication time needs a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_url(value) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
        raise ValueError("Source URL unavailable or too long")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Source URL must be HTTPS without credentials")
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {".tsrc", "guccounter", "guce_referrer", "guce_referrer_sig"}]
    return urlunsplit(("https", parts.hostname.lower(), parts.path or "/", urlencode(sorted(query)), ""))


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def matched_symbols(title: str, symbols: list[str]) -> list[str]:
    result = []
    for symbol in symbols:
        terms = ALIASES.get(symbol, [symbol])
        for term in terms:
            pattern = (r"\$" + re.escape(term) + r"\b") if term == symbol and len(term) < 3 else r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
            if re.search(pattern, title, re.I):
                result.append(symbol)
                break
    return result


def story_type(story: dict) -> str:
    """Classify the headline's format without claiming the article was read."""
    if story["official"]:
        return "announcement"
    title = story["title"]
    roundup = (
        r"^(?:here are\s+)?(?:\d+|three|five|ten)\b.{0,65}\b(?:stocks|etfs|funds|picks)\b",
        r"\b(?:stocks|etfs|funds)\s+(?:to|you should)\s+(?:buy|watch|own|sell)\b",
        r"^(?:dow jones|s&p 500|nasdaq|stock market|wall street|market)\s+(?:futures|today|outlook|preview|week ahead)\b",
    )
    if any(re.search(pattern, title, re.I) for pattern in roundup):
        return "roundup"
    if len(story["symbols"]) > 1 and re.search(r"\b(?:week ahead|earnings preview|market outlook)\b", title, re.I):
        return "roundup"
    if re.search(r"^(?:why|how)\b|\b(?:opinion|analysis)\s*:", title, re.I) or title.endswith("?"):
        return "commentary"
    return "reported development"


def cache_candidates(now: datetime, symbols: list[str]) -> tuple[list[dict], list[str]]:
    path = Path(os.getenv("NEWS_LIVE_SOURCE_CACHE_FILE", str(feeds.CACHE_FILE)))
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            raise ValueError("News cache exceeds the size limit")
        cache = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(cache, dict):
            raise ValueError("News cache is not an object")
    except (OSError, ValueError, UnicodeError) as exc:
        return [], ["News feed cache unavailable (" + type(exc).__name__ + ")"]
    candidates, issues = [], []
    for source in feeds.NEWS_SOURCES:
        payload = cache.get(source["url"])
        try:
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ValueError("missing or failed fetch")
            fetched = payload["fetched_at_epoch"]
            if type(fetched) not in (float, int) or not math.isfinite(fetched) or not -60 <= now.timestamp() - fetched <= MAX_CACHE_AGE:
                raise ValueError("stale or invalid fetch time")
            body = payload["body"]
            if not isinstance(body, str) or len(body.encode()) > MAX_CACHE_BYTES:
                raise ValueError("invalid feed body")
            # HTML titles and fetch times are never substituted for original RSS dates.
            items = feeds.parse_rss_items(body, source)[:30]
            if not items:
                raise ValueError("no dated RSS article candidates")
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(source["name"] + ": " + str(exc))
            continue
        for item in items:
            company_symbols = matched_symbols(item["title"], symbols)
            themes = feeds.detect_item_themes(item)
            try:
                host = urlsplit(item["link"]).hostname or ""
            except ValueError:
                host = ""
            official_host = OFFICIAL_HOSTS.get(source["name"])
            official = bool(official_host and (host == official_host or host.endswith("." + official_host)))
            candidates.append({"kind": "company" if company_symbols and not official_host else "macro", "symbols": company_symbols,
                "title": item["title"], "url": item["link"], "published": item["published"],
                "source": source["name"], "source_checked_at": datetime.fromtimestamp(fetched, timezone.utc).isoformat(),
                "official": official, "origin": "cached RSS", "themes": themes,
                "relevant": bool(company_symbols or themes or official_host), "authority_mismatch": bool(official_host and not official)})
    return candidates, issues


def build_editorial_plan(brief: dict, now: datetime, extra_candidates: list[dict] | None = None) -> dict:
    if now.tzinfo is None:
        raise ValueError("News editor clock needs a timezone")
    symbols = [row["symbol"] for row in brief["rows"]]
    cached, issues = cache_candidates(now, symbols) if extra_candidates is None else (deepcopy(extra_candidates), [])
    candidates = []
    for row in brief["rows"]:
        for event in row["events"]:
            candidates.append({**event, "kind": "company", "symbols": event.get("symbols", [row["symbol"]]),
                "origin": "special-alert evidence", "relevant": True,
                "source_checked_at": event.get("source_checked_at"), "themes": []})
    candidates += cached
    ledger = []
    for raw in candidates[:MAX_CANDIDATES]:
        title = clean(raw.get("title"), 160)
        story = {"title": title, "url": clean(raw.get("url"), 2048), "source": clean(raw.get("source"), 65),
                 "symbols": [symbol for symbol in raw.get("symbols", []) if symbol in symbols],
                 "kind": raw.get("kind", "macro"), "origin": raw.get("origin", "cached RSS"),
                 "official": raw.get("official") is True, "published": clean(raw.get("published"), 100),
                 "source_checked_at": raw.get("source_checked_at"), "decision": "wait", "reason": "Source checks pending"}
        story["id"] = hashlib.sha256(json.dumps([story["title"], story["url"], story["published"]]).encode()).hexdigest()[:16]
        try:
            if not title or not story["source"]:
                raise ValueError("Headline or source missing")
            story["canonical_url"] = canonical_url(raw.get("url"))
            published = dated(raw.get("published"))
            if not -60 <= (now - published).total_seconds() <= MAX_NEWS_AGE:
                raise ValueError("Original publication time is future-dated or older than 24 hours")
            if raw.get("authority_mismatch"):
                raise ValueError("Publisher-feed link does not match the original publisher")
            story["published"] = published.isoformat()
            story["source_check"] = "pass"
        except (ValueError, TypeError, OverflowError) as exc:
            story.update(source_check="hold", reason=str(exc))
            ledger.append(story)
            continue
        story["story_type"] = story_type(story)
        if not raw.get("relevant", True) or (story["kind"] == "company" and not story["symbols"]):
            story.update(decision="skip", reason="Outside monitored companies and market themes")
        elif story["story_type"] == "roundup":
            story.update(decision="skip", reason="Broad market preview or stock-pick roundup; no discrete company development established by the headline")
        else:
            rank = min((symbols.index(symbol) for symbol in story["symbols"]), default=len(symbols))
            story["priority"] = (100 if story["official"] else 70) + (10 if story["symbols"] else 5) + max(0, 10 - rank)
            if story["story_type"] == "commentary":
                story["priority"] -= 12
            story.update(decision="eligible", reason="Dated source and research relevance checks passed")
        ledger.append(story)
    selected, urls, titles, companies = [], set(), set(), set()
    company_eligible = any(story["decision"] == "eligible" and story["kind"] == "company" for story in ledger)
    for story in sorted([item for item in ledger if item["decision"] == "eligible"], key=lambda item: (-item["priority"], -dated(item["published"]).timestamp(), item["id"])):
        key = title_key(story["title"])
        # Alphabet share classes represent the same issuer for coverage diversity.
        issuers = {"GOOGL" if symbol == "GOOG" else symbol for symbol in story["symbols"]}
        if story["canonical_url"] in urls or key in titles:
            story.update(decision="skip", reason="Duplicate article URL or headline; retained higher-priority evidence")
        elif issuers & companies:
            story.update(decision="skip", reason="Company already represented; preserve coverage diversity")
        elif company_eligible and story["kind"] == "macro" and any(item["kind"] == "macro" for item in selected):
            story.update(decision="skip", reason="Macro story already represented; preserve company coverage")
        elif len(selected) >= MAX_STORIES:
            story.update(decision="skip", reason="Edition story limit; higher-priority sourced stories selected")
        else:
            story.update(decision="selected", reason="Dated, relevant source; selected within the diverse edition budget")
            selected.append(story)
            urls.add(story["canonical_url"]); titles.add(key); companies.update(issuers)
    return {"schema": 1, "generated_at": now.astimezone(timezone.utc).isoformat(), "candidates": ledger,
            "issues": list(dict.fromkeys(brief.get("issues", []) + issues)), "ranking_date": brief.get("ranking_date"),
            "rules_version": 2, "stages": [], "truncated_candidates": max(0, len(candidates) - MAX_CANDIDATES)}


def selected_stories(plan: dict) -> list[dict]:
    return sorted([story for story in plan["candidates"] if story["decision"] == "selected"], key=lambda item: (-item["priority"], -dated(item["published"]).timestamp(), item["id"]))


def research_focus(story: dict) -> str:
    if story["kind"] == "company":
        return "Research focus: check company guidance, commercial timing, demand and execution costs."
    return "Research focus: check the published details and rate-sensitive, energy or sector exposure; the headline does not establish a market cause."


def render_story(story: dict, zone, company_names: dict) -> str:
    published = dated(story["published"]).astimezone(zone)
    at = f"{published:%B} {published.day} at {published.strftime('%I:%M').lstrip('0')} {published:%p %Z}"
    headline = "“" + story["title"].rstrip(".") + "”"
    punctuation = "" if story["title"].endswith(("?", "!")) else "."
    if story["kind"] == "company":
        company = company_names.get(story["symbols"][0], story["symbols"][0])
        if story["official"]:
            return (f"{company}'s company announcement, published {at} via {story['source']}, is headlined {headline}{punctuation} "
                    "Commercial timing and impact still require review.")
        if story.get("story_type") == "commentary":
            return (f"In commentary on {company}, {story['source']}'s headline, published {at}, reads {headline}{punctuation} "
                    "This is headline-only commentary, unconfirmed by the company.")
        return (f"{story['source']}'s report on {company}, published {at}, carries the headline {headline}{punctuation} "
                "This is a headline-only report, unconfirmed by the company.")
    else:
        if story["official"]:
            return (f"A publisher announcement from {story['source']}, published {at}, is headlined {headline}{punctuation} "
                    "Review the original release for scope and context.")
        return (f"In market news, {story['source']}'s headline, published {at}, reads {headline}{punctuation} "
                "This headline-only account is unconfirmed; it does not establish the cause of market moves.")


def review_and_record(plan: dict, report: str, paragraphs: dict[str, str], research_report: str) -> str:
    selected = selected_stories(plan)
    for story in selected:
        if report.count(paragraphs[story["id"]]) != 1:
            raise ValueError("Selected story evidence or qualification changed during narration")
    if len(selected) > MAX_STORIES:
        raise ValueError("News story budget exceeded")
    value = deepcopy(plan)
    counts = {decision: sum(story["decision"] == decision for story in value["candidates"]) for decision in ("selected", "skip", "wait")}
    value["research_sha256"] = hashlib.sha256(research_report.encode()).hexdigest()
    snapshot = re.search(r"\nMarket Snapshot\n(.*?)\n\n", research_report, re.S)
    moves = re.search(r"^[-•] Market moves: (.+)$", research_report, re.M)
    value["market_evidence"] = {"snapshot": snapshot[1][:900] if snapshot else "Unavailable", "moves": moves[1][:600] if moves else "Unavailable"}
    value["stages"] = [
        {"name": "Scan", "status": "pass", "detail": f"{len(value['candidates'])} candidates from cached public evidence"},
        {"name": "Source Check", "status": "limited" if counts["wait"] or value["issues"] else "pass", "detail": f"{counts['wait']} held; original publication dates and HTTPS URLs checked"},
        {"name": "Relevance", "status": "pass", "detail": "Core companies, dated top opportunities and market themes"},
        {"name": "Selection", "status": "pass", "detail": f"{counts['selected']} selected / {counts['skip']} skipped; one story per represented company"},
        {"name": "Editorial Review", "status": "pass", "detail": "Selected source facts, dates, attribution and confidence labels retained"},
        {"name": "Decision Log", "status": "pass", "detail": "Built edition and source decisions recorded; this is not a delivery receipt"}]
    return store.save_edition(value, report)


def review_daily_edition(report: str) -> str:
    rows = store.read_editions(limit=1, report=report)
    if not rows:
        raise RuntimeError("No editorial decision record matches this report")
    record = rows[0]
    if not any(step["name"] == "Editorial Review" and step["status"] == "pass" for step in record["stages"]):
        raise RuntimeError("Editorial review did not pass")
    counts = {decision: sum(story["decision"] == decision for story in record["candidates"]) for decision in ("selected", "skip", "wait")}
    return f"{counts['selected']} sourced stories selected; {counts['skip']} skipped; {counts['wait']} held. Editorial facts and qualifications checked; edition {record['id']}."


def build_editor_status(symbol: str = "", history: bool = False) -> str:
    try:
        records = store.read_editions(limit=3 if history else 1)
    except (OSError, sqlite3.Error) as exc:
        return "Smart Money News Editor\nDecision log unavailable (" + type(exc).__name__ + ")."
    if not records:
        return "Smart Money News Editor\nNo recorded news edition yet. Run /report or /rundailyagent."
    lines = ["Smart Money News Editor" if not history else "News Story Decision Log"]
    for record in records:
        lines += ["", "Edition: " + record["id"], "Built: " + record["generated_at"]]
        if not history:
            lines += [step["name"] + ": " + step["status"].upper() + " — " + step["detail"] for step in record["stages"]]
            if record["issues"]:
                lines.append("Coverage: " + "; ".join(clean(issue, 120) for issue in record["issues"][:3]))
            lines += ["", "Market evidence: " + clean(record["market_evidence"]["moves"], 400)]
        else:
            stories = [story for story in record["candidates"] if not symbol or symbol in story["symbols"]]
            for story in stories[:12]:
                lines += ["", story["decision"].upper() + " — " + story["title"], "Reason: " + story["reason"],
                          "Source: " + story["source"] + " | Published: " + story["published"],
                          "Evidence: " + ("publisher/company announcement" if story["official"] else "headline only; confirmation pending"),
                          "Source check: " + story.get("source_check", "hold") + " | Cached at: " + str(story.get("source_checked_at") or "unavailable")]
                if story.get("story_type"):
                    lines.append("Story type: " + story["story_type"])
                if story.get("source_check") == "pass":
                    lines.append(story["url"])
                if story["decision"] == "selected":
                    lines.append(research_focus(story))
            if not stories:
                lines.append("No matching story decisions for " + symbol + " in this edition.")
            elif len(stories) > 12:
                lines.append(f"Showing 12 of {len(stories)} decisions; use /storylog SYMBOL to narrow coverage.")
    lines += ["", "Built-edition records; publication, orders and investment returns are not inferred.", "/editorstatus · /storylog [SYMBOL] · /fullreport"]
    return "\n".join(lines)
