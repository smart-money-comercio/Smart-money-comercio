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
from src.intelligence.special_alert_sources import clean, company_url
from src.intelligence.special_alert_engine import company_event
from src.intelligence.market_brief import story_topics
from src.intelligence.story_analysis import build_evidence, checked_evidence, event_type
from src.intelligence.policy_analysis import is_fomc_statement


MAX_STORIES = 3
MAX_CANDIDATES = 180
MAX_CACHE_BYTES = feeds.MAX_CACHE_BYTES
MAX_CACHE_AGE = 6 * 3600
MAX_NEWS_AGE = 24 * 3600
MAX_HEADLINE_CHARS = 1000
OFFICIAL_HOSTS = {"Federal Reserve": "federalreserve.gov", "U.S. Treasury": "treasury.gov", "EIA": "eia.gov", "DARPA": "darpa.mil"}
ALIASES = {**feeds.TICKER_TERMS, "TSM": ["TSM", "TSMC", "Taiwan Semiconductor"],
           "NOC": ["NOC", "Northrop Grumman"], "LMT": ["LMT", "Lockheed Martin"],
           "AVAV": ["AVAV", "AeroVironment"], "KTOS": ["KTOS", "Kratos"], "CRWD": ["CRWD", "CrowdStrike"],
           "CACI": ["CACI"], "GOOG": ["GOOG", "Google", "Alphabet"]}
STAGE_NAMES = ("Scan", "Source Check", "Relevance", "Selection", "Editorial Review", "Decision Log")


def primary_source(story: dict) -> str:
    """Require both publisher provenance and an original issuer/agency link."""
    if story.get("sec_filing"):
        from src.intelligence.sec_research import checked
        try:
            return checked(story)["issuer"]
        except (ValueError, KeyError, TypeError, AttributeError):
            return ""
    if story.get("discovery_evidence"):
        from src.intelligence.hourly_research import check_proof
        try:
            return check_proof(story)["name"]
        except (ValueError, KeyError, TypeError, AttributeError):
            return ""
    if story.get("ipo"):
        from src.intelligence.ipo_monitor import checked
        try:
            return checked(story)["name"]
        except (ValueError, KeyError, TypeError, AttributeError):
            return ""
    if not story["official"]:
        return ""
    url = story.get("canonical_url", story["url"])
    host = urlsplit(url).hostname or ""
    if story["kind"] == "company":
        publisher = story.get("publisher_symbol")
        return publisher if publisher in story["symbols"] and company_url(publisher, url) else ""
    domain = OFFICIAL_HOSTS.get(story["source"])
    return story["source"] if domain and (host == domain or host.endswith("." + domain)) else ""


def materiality(story: dict) -> str:
    title = story["title"]
    if story.get("sec_filing"):
        return story["sec_filing"]["disclosure"]["topic"] if primary_source(story) else ""
    if story.get("ipo"):
        return "IPO" if primary_source(story) else ""
    if story.get("discovery_evidence") and story["discovery_evidence"].get("publisher", {}).get("kind") == "issuer":
        proxy = {key: value for key, value in story.items() if key != "discovery_evidence"}
        return materiality({**proxy, "kind": "company"})
    if story["kind"] == "company":
        if re.search(r"\b(earnings|results) (date|call|webcast)\b|\bannounces? (?:its |the )?date\b|\b(?:will|to) (?:report|release)\b.{0,60}\b(results|earnings)\b", title, re.I):
            return ""
        kind, stage = event_type(title)
        if kind == "restructuring" and re.search(r"\b(no|denies|rules out)\b.{0,30}\b(layoffs?|job cuts|staff reductions?)\b", title, re.I):
            return ""
        if kind in {"acquisition", "divestiture", "restructuring"}:
            return "" if re.search(r"\b(rumou?r\w*|reportedly|could|might|may|considering)\b|\?", title, re.I) else kind
        if kind == "product" and stage in {"test milestone", "planned test"}:
            return "defense innovation"
        if kind in {"capacity expansion", "technology collaboration"}:
            return kind
        if kind == "contract" and stage == "cooperation":
            return "contract"
        event = company_event(title)
        if event:
            return event[0]
        patterns = {
            "product": r"\b(introduces?|launch(?:es)?|unveils?|ships?|rolls? out)\b.{0,100}\b(cloud|tools?|products?|platform|chips?|systems?|software|AI)\b",
            "earnings": r"\breports?\b.{0,80}\b(results|earnings|revenue|EPS)\b",
            "contract": r"\b(contract|partnership|strategic alliance|commercial agreement)\b",
            "capital": r"\b(dividend|share repurchase|buyback|stock split|compensation|pay package|share sales?|stock sales?|stake sales?)\b",
            "leadership": r"\b(appoints?|names?|named|becomes?)\b.{0,60}\b(CEO|CFO|chief executive|chairman|chairperson)\b|\b(steps down|resigns?|retires?)\b",
            "investment": r"\b(invests?|investment|capital spending|capital expenditure|capacity expansion|new factory|new fab)\b",
            "regulation": r"\b(antitrust|lawsuit|court ruling|regulatory approval|export ban|export restrictions|SEC filing|10-K|10-Q|8-K)\b",
            "operations": r"\b(exits?|ceases?|closes?|shuts down|suspends?|resumes?|layoffs?|job cuts)\b|\b(loses?|has lost)\b.{0,70}\b(market|sales|licen[cs]e|contract|business)\b",
            "guidance": r"\b(guidance|revenue outlook|earnings outlook|revenue forecast)\b|\b(forecasts?|projects?|expects?)\b.{0,60}\b(revenue|earnings|EPS|cash flow)\b",
        }
    else:
        if story["source"] == "DARPA" and re.search(r"\b(demonstrat\w*|tests?|prototype|autonomous|quantum|hypersonic|counter.drone|cybersecurity|research program)\b", title, re.I):
            return "defense innovation"
        patterns = {
            "monetary policy": r"\b(FOMC|interest rates?|monetary policy|policy review|Federal Reserve policy|meeting minutes)\b",
            "economic data": r"\b(inflation|CPI|PCE|payrolls?|employment|jobless|GDP|gross domestic product)\b",
            "energy": r"\b(oil|crude|gasoline|energy|petroleum|inventories)\b",
            "public finance": r"\b(Treasury|borrowing|debt|bond auction|buybacks?|tariffs?|sanctions|financial stability|enforcement)\b",
        }
        if story["symbols"] and re.search(r"\b(contract|agreement|regulatory approval|investigation)\b", title, re.I):
            return "government company report"
    topic = next((category for category, pattern in patterns.items() if re.search(pattern, title, re.I)), "")
    if not topic and story.get("research_review") and story.get("discovery_evidence") and primary_source(story):
        return "reviewed company development" if story["kind"] == "company" else "reviewed policy development"
    return topic


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
    title = story["title"]
    if (re.search(r"\b(would bet|bets? that|betting|price target|target price|price prediction)\b", title, re.I)
            or re.search(r"\b(stock|shares|bitcoin|price)\b.{0,50}\b(could|will|may|might)\b.{0,25}\b(rise|rally|surge|soar|hit|reach|double|triple)\b", title, re.I)):
        return "speculation"
    capital_event = re.search(
        r"\b(?:compensation|pay package|shareholder vote|share sales?|stock sales?|stake sales?|margin call)\b", title, re.I)
    corporate_event = re.search(
        r"\b(?:appoints?|names? .{0,30}(?:CEO|chief executive)|steps down|resigns?|retires?|"
        r"launch(?:es)?|announces?|signs? .{0,30}(?:contract|deal)|wins? .{0,30}contract)\b", title, re.I)
    corporate_event = corporate_event or capital_event
    if re.search(r"\b(?:net worth|richest (?:person|man|woman)|trillionaire)\b", title, re.I) and not capital_event:
        return "personal wealth"
    retrospective = re.search(r"\b(?:a look back|looking back|years? as (?:CEO|chief executive))\b", title, re.I)
    metric_history = re.search(r"\b(?:market cap|market value).{0,30}(?:grew|grown|growth).{0,30}from\b", title, re.I)
    analysis_cue = re.search(r"\bhere['’]s (?:why|what|how)\b|\bstill matters\b|\bgrowth curve\b", title, re.I)
    if (retrospective or (metric_history and analysis_cue)) and not corporate_event:
        return "retrospective"
    roundup = (
        r"^(?:here are\s+)?(?:\d+|three|five|ten)\b.{0,65}\b(?:stocks|etfs|funds|picks)\b",
        r"\b(?:stocks|etfs|funds)\s+(?:to|you should)\s+(?:buy|watch|own|sell)\b",
        r"^(?:dow jones|s&p 500|nasdaq|stock market|wall street|market)\s+(?:futures|today|outlook|preview|week ahead)\b",
    )
    if any(re.search(pattern, title, re.I) for pattern in roundup):
        return "roundup"
    if len(story["symbols"]) > 1 and re.search(r"\b(?:week ahead|earnings preview|market outlook)\b", title, re.I):
        return "roundup"
    if (re.search(r"^(?:why|how)\b|\b(?:opinion|analysis)\s*:", title, re.I) or title.endswith("?")
            or (analysis_cue and not corporate_event)):
        return "commentary"
    return ("announcement" if story["official"] else "reported development") if materiality(story) else "context"


def cache_candidates(now: datetime, symbols: list[str], *, health: list | None = None, cache: dict | None = None) -> tuple[list[dict], list[str]]:
    path = Path(os.getenv("NEWS_LIVE_SOURCE_CACHE_FILE", str(feeds.CACHE_FILE)))
    try:
        if cache is None:
            if path.stat().st_size > MAX_CACHE_BYTES:
                raise ValueError("News cache exceeds the size limit")
            cache = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(cache, dict):
            raise ValueError("News cache is not an object")
    except (OSError, ValueError, UnicodeError) as exc:
        if health is not None:
            health.extend(feeds.describe_source(source, None, now) for source in feeds.NEWS_SOURCES if feeds.is_original_source(source))
        return [], ["News feed cache unavailable (" + type(exc).__name__ + ")"]
    candidates, issues = [], []
    for source in feeds.NEWS_SOURCES:
        payload = cache.get(source["url"])
        source_health = feeds.describe_source(source, payload, now)
        if health is not None and feeds.is_original_source(source):
            health.append(source_health)
        try:
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ValueError(source_health["reason"])
            fetched = payload["fetched_at_epoch"]
            if type(fetched) not in (float, int) or not math.isfinite(fetched) or not -60 <= now.timestamp() - fetched <= MAX_CACHE_AGE:
                raise ValueError("stale or invalid fetch time")
            body = payload["body"]
            if not isinstance(body, str) or len(body.encode()) > MAX_CACHE_BYTES:
                raise ValueError("invalid feed body")
            if feeds.is_original_source(source) and not feeds.originals.authorized_response(source, payload):
                raise ValueError("Publisher redirect mismatch")
            # HTML titles and fetch times are never substituted for original RSS dates.
            items = feeds.parse_article_items(payload, source, full_titles=True, full_text=True)[:30]
            if not items:
                if source_health["status"] == "available":
                    continue
                raise ValueError("no dated RSS article candidates")
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(source["name"] + ": " + str(exc))
            continue
        for item in items:
            company_symbols = matched_symbols(item["title"], symbols)
            publisher = source.get("company_symbol")
            if publisher in symbols:
                company_symbols = [publisher]
            themes = feeds.detect_item_themes(item)
            try:
                host = urlsplit(item["link"]).hostname or ""
            except ValueError:
                host = ""
            official_host = OFFICIAL_HOSTS.get(source["name"])
            official = bool(official_host and (host == official_host or host.endswith("." + official_host)))
            if publisher:
                official = bool(publisher in symbols and company_url(publisher, item["link"]))
            evidence_stamp = item.get("evidence_checked_at", fetched)
            usable_excerpt = (type(evidence_stamp) in (int, float) and math.isfinite(evidence_stamp)
                              and -60 <= now.timestamp() - evidence_stamp <= MAX_CACHE_AGE)
            candidates.append({"kind": "company" if publisher or (company_symbols and not official_host) else "macro", "symbols": company_symbols,
                "title": item["title"], "url": item["link"], "published": item["published"],
                "source": source["name"], "source_checked_at": datetime.fromtimestamp(fetched, timezone.utc).isoformat(),
                "publisher_symbol": publisher if official and publisher else "",
                "official": official, "origin": "cached RSS", "themes": themes,
                "source_excerpt": item.get("description", "") if usable_excerpt else "",
                "excerpt_scope": item.get("evidence_scope", "publisher feed excerpt") if usable_excerpt else "headline only",
                "evidence_checked_at": datetime.fromtimestamp(evidence_stamp, timezone.utc).isoformat() if usable_excerpt else "",
                "relevant": bool(company_symbols or themes or official_host), "authority_mismatch": bool(official_host and not official)})
    return candidates, issues


def build_editorial_plan(brief: dict, now: datetime, extra_candidates: list[dict] | None = None) -> dict:
    if now.tzinfo is None:
        raise ValueError("News editor clock needs a timezone")
    symbols = [row["symbol"] for row in brief["rows"]]
    health = []
    cached, issues = cache_candidates(now, symbols, health=health) if extra_candidates is None else (deepcopy(extra_candidates), [])
    if extra_candidates is None:
        from src.config.special_alerts import settings
        from src.intelligence.ipo_monitor import cached_items
        if settings().get("ipo_enabled"):
            cached += [{**value, "kind": "macro", "origin": "IPO original-source cache", "relevant": True} for value in cached_items(now)]
        from src.intelligence.hourly_research import approved
        cached += approved(now)
    if health:
        configured = {row["symbol"] for row in health}
        for symbol in symbols:
            if symbol not in configured:
                health.append({"name": symbol, "symbol": symbol, "status": "limited", "checked_at": "", "entries": 0, "dated": 0,
                               "fresh": 0, "undated": 0, "latest_publication": "", "reason": "Direct publisher reader not configured"})
    candidates = []
    for row in brief["rows"]:
        for event in row["events"]:
            candidates.append({**event, "kind": "company", "symbols": event.get("symbols", [row["symbol"]]),
                "origin": "special-alert evidence", "relevant": True,
                "source_checked_at": event.get("source_checked_at"), "themes": []})
    candidates += cached
    # Preserve room for original reports before logging unconfirmed headline leads.
    def scan_priority(item):
        published = timestamp_for_priority(item.get("published"))
        fresh = published is not None and -60 <= (now - published).total_seconds() <= MAX_NEWS_AGE
        return (item.get("official") is not True, not fresh, -published.timestamp() if published else 0)
    candidates.sort(key=scan_priority)
    ledger, excerpts = [], {}
    for raw in candidates[:MAX_CANDIDATES]:
        raw_title = raw.get("title")
        title = clean(raw_title, MAX_HEADLINE_CHARS + 1)
        incomplete = bool(raw.get("title_truncated")) or len(title) > MAX_HEADLINE_CHARS or title.endswith(("...", "…"))
        story = {"title": title[:MAX_HEADLINE_CHARS], "title_truncated": incomplete,
                 "url": clean(raw.get("url"), 2048), "source": clean(raw.get("source"), 65),
                 "symbols": [symbol for symbol in raw.get("symbols", []) if symbol in symbols],
                 "kind": raw.get("kind", "macro"), "origin": raw.get("origin", "cached RSS"),
                 "official": raw.get("official") is True, "published": clean(raw.get("published"), 100),
                 "publisher_symbol": raw.get("publisher_symbol", ""),
                 "source_checked_at": raw.get("source_checked_at"), "decision": "wait", "reason": "Source checks pending"}
        story["id"] = hashlib.sha256(json.dumps([story["title"], story["url"], story["published"]]).encode()).hexdigest()[:16]
        if raw.get("ipo") is not None:
            story["ipo"] = deepcopy(raw["ipo"])
        if raw.get("sec_filing") is not None:
            story["sec_filing"] = deepcopy(raw["sec_filing"])
        if raw.get("discovery_evidence") is not None:
            story["discovery_evidence"] = deepcopy(raw["discovery_evidence"])
        if raw.get("research_review") is not None:
            story["research_review"] = deepcopy(raw["research_review"])
        try:
            if not isinstance(raw_title, str) or not title or not story["source"]:
                raise ValueError("Headline or source missing")
            story["canonical_url"] = canonical_url(raw.get("url"))
            published = dated(raw.get("published"))
            if (now - published).total_seconds() < -60:
                raise ValueError("Original publication time is future-dated")
            if (now - published).total_seconds() > MAX_NEWS_AGE:
                raise ValueError("Original publication time is older than 24 hours")
            checked = dated(raw.get("source_checked_at"))
            if not -60 <= (now - checked).total_seconds() <= MAX_CACHE_AGE:
                raise ValueError("Original source observation is stale or future-dated")
            if raw.get("authority_mismatch"):
                raise ValueError("Publisher-feed link does not match the original publisher")
            if incomplete:
                raise ValueError("Complete original headline unavailable or longer than the editorial limit; shortened wording withheld")
            if story["official"] and not primary_source(story):
                raise ValueError("Original publisher identity does not match the company or agency source")
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
        elif story["story_type"] in {"personal wealth", "retrospective"}:
            story.update(decision="skip", reason="Personal-wealth profile or retrospective; a current company development is not established by the headline")
        elif story["story_type"] in {"commentary", "speculation", "context"}:
            story.update(decision="skip", reason="Opinion, forecast or general context; no material sourced development admitted to the news brief")
        elif not primary_source(story):
            story.update(decision="wait", confirmation_check="hold", reason="Original company or agency report required; unconfirmed headlines are excluded from the news brief")
        else:
            story.update(confirmation_check="pass", confirmed_by=primary_source(story), materiality=materiality(story))
            rank = min((symbols.index(symbol) for symbol in story["symbols"]), default=len(symbols))
            story["priority"] = (100 if story["official"] else 70) + (10 if story["symbols"] else 5) + max(0, 10 - rank)
            story.update(decision="eligible", reason="Dated source and research relevance checks passed")
            if not story.get("ipo") and not story.get("sec_filing"):
                scope = raw.get("excerpt_scope", "headline only")
                text = raw.get("source_excerpt", "")
                if scope not in {"headline only", "publisher feed excerpt", "original release excerpt"}:
                    text, scope = "", "headline only"
                observed = raw.get("evidence_checked_at") or story["source_checked_at"]
                excerpts[story["id"]] = (text, scope, observed)
                if is_fomc_statement(story):
                    try:
                        evidence_clock = dated(observed)
                        fresh = -60 <= (now-evidence_clock).total_seconds() <= MAX_CACHE_AGE and (published-evidence_clock).total_seconds() <= 60
                    except (ValueError, TypeError, OverflowError):
                        fresh = False
                    profile = build_evidence(story, text, scope)
                    if not fresh or scope == "headline only" or not profile["facts"]:
                        story.update(decision="wait", confirmation_check="hold",
                                     reason="Original Fed decision text and a current source observation are required; the announcement headline alone is insufficient")
        ledger.append(story)
    selected, urls, titles, companies = [], set(), set(), set()
    company_eligible = any(story["decision"] == "eligible" and story["kind"] == "company" for story in ledger)
    for story in coverage_order([item for item in ledger if item["decision"] == "eligible"]):
        key = title_key(story["title"])
        # Alphabet share classes represent the same issuer for coverage diversity.
        issuers = {"GOOGL" if symbol == "GOOG" else symbol for symbol in story["symbols"]}
        if story.get("ipo"):
            issuers.add("IPO:" + story["ipo"]["issuer_id"])
        if story["canonical_url"] in urls or key in titles:
            story.update(decision="skip", reason="Duplicate article URL or headline; retained higher-priority evidence")
        elif issuers & companies:
            story.update(decision="skip", reason="Company already represented; preserve coverage diversity")
        elif company_eligible and story["kind"] == "macro" and not story.get("ipo") and any(item["kind"] == "macro" and not item.get("ipo") and
                ("defense" in story_topics(item)) == ("defense" in story_topics(story)) for item in selected):
            story.update(decision="skip", reason="Macro story already represented; preserve company coverage")
        elif len(selected) >= MAX_STORIES:
            story.update(decision="skip", reason="Edition story limit; higher-priority sourced stories selected")
        else:
            story.update(decision="selected", reason=f"Original {story['confirmed_by']} report; material {story['materiality']} development within the edition budget")
            selected.append(story)
            urls.add(story["canonical_url"]); titles.add(key); companies.update(issuers)
    for story in selected:
        if not story.get("ipo") and not story.get("sec_filing"):
            text, scope, observed = excerpts.get(story["id"], ("", "headline only", story["source_checked_at"]))
            story["evidence_checked_at"] = observed
            story["event_evidence"] = build_evidence(story, text, scope)
    return {"schema": 1, "generated_at": now.astimezone(timezone.utc).isoformat(), "candidates": ledger,
            "issues": list(dict.fromkeys(brief.get("issues", []) + issues)), "ranking_date": brief.get("ranking_date"),
            "rules_version": 14, "source_health": health, "stages": [], "truncated_candidates": max(0, len(candidates) - MAX_CANDIDATES)}


def timestamp_for_priority(value):
    try:
        return dated(value)
    except (ValueError, TypeError, OverflowError):
        return None


def selected_stories(plan: dict) -> list[dict]:
    return coverage_order([story for story in plan["candidates"] if story["decision"] == "selected"])


def news_order(story: dict) -> tuple:
    """Editorial categories set reading order, without asserting price impact."""
    topic = materiality(story)
    tier = {"IPO": 4, "monetary policy": 4, "economic data": 4, "guidance": 3, "regulation": 3,
            "AI infrastructure financing": 3, "financing disclosure": 2,
            "earnings": 2, "acquisition": 2, "divestiture": 2, "restructuring": 2,
            "contract": 1, "product": 1, "defense innovation": 1}.get(topic, 0)
    return (-tier, -story.get("priority", 0), -dated(story["published"]).timestamp(), story["id"])


def coverage_order(stories: list[dict]) -> list[dict]:
    ordered = sorted(stories, key=news_order)
    preferred = []
    for predicate in (lambda row: bool(row.get("ipo")),
                      lambda row: row["kind"] == "macro" and not row.get("ipo") and "defense" not in story_topics(row),
                      lambda row: "defense" in story_topics(row)):
        found = next((row for row in ordered if predicate(row) and row not in preferred), None)
        if found:
            preferred.append(found)
    return preferred + [row for row in ordered if row not in preferred]


def research_focus(story: dict) -> str:
    if story["kind"] == "company":
        return "Research focus: check company guidance, commercial timing, demand and execution costs."
    return "Research focus: check the published details and rate-sensitive, energy or sector exposure; the headline does not establish a market cause."


def render_story(story: dict, zone, company_names: dict) -> str:
    published = dated(story["published"]).astimezone(zone)
    at = f"{published:%B} {published.day} at {published.strftime('%I:%M').lstrip('0')} {published:%p %Z}"
    headline = "“" + story["title"].rstrip(".") + "”"
    punctuation = "" if story["title"].endswith(("?", "!")) else "."
    if story.get("sec_filing"):
        from src.intelligence.sec_research import checked, narration
        filing = checked(story)
        return f"{filing['issuer']} filed Form {filing['form']}, accepted {at} according to SEC EDGAR. " + narration(story)
    if story.get("ipo"):
        from src.intelligence.ipo_monitor import checked, interpretation, STAGES
        issuer = checked(story)
        stage = STAGES[story["ipo"]["stage"]]
        clock = "accepted" if story["ipo"]["form"] else "published"
        text = (f"{issuer['name']}: {stage}, accepted {at} on Form {story['ipo']['form']}, according to SEC EDGAR." if story["ipo"]["form"] else
                f"{issuer['name']}: {stage}. The original company announcement, published {at}, is headlined {headline}{punctuation}")
        if story["ipo"]["proposed_symbol"]:
            text += " The symbol described in the source is " + story["ipo"]["proposed_symbol"] + "; trading status requires separate confirmation."
        return text + " Our analysis: " + interpretation(story)
    if story["kind"] == "company":
        issuer = story.get("confirmed_by") or story["symbols"][0]
        company = company_names.get(issuer, issuer)
        if story["official"]:
            from src.agents.analyst_agent import review_sourced_development
            review = review_sourced_development(story)
            text = f"{company}'s company announcement, published {at} via {story['source']}, is headlined {headline}{punctuation}"
            if review["facts"]:
                text += " " + review["facts"]
            if "defense" not in story_topics(story):
                text += " Our analysis: " + review["why"] + " Watch next: " + review["watch"]
            return text
        if story.get("story_type") == "commentary":
            return (f"In commentary on {company}, {story['source']}'s headline, published {at}, reads {headline}{punctuation} "
                    "This is headline-only commentary, unconfirmed by the company.")
        return (f"{story['source']}'s report on {company}, published {at}, carries the headline {headline}{punctuation} "
                "This is a headline-only report, unconfirmed by the company.")
    else:
        if story["official"]:
            if is_fomc_statement(story):
                from src.intelligence.story_analysis import investor_read
                review = investor_read(story)
                if not review["facts"]:
                    raise ValueError("Original Fed decision facts are required for narration")
                return (f"According to the Federal Reserve's original statement, published {at}, "
                        + review["facts"][0].lower() + review["facts"][1:]
                        + " Our analysis: " + review["why"] + " Watch next: " + review["watch"])
            return (f"A publisher announcement from {story['source']}, published {at}, is headlined {headline}{punctuation} "
                    "Review the original release for scope and context.")
        return (f"In market news, {story['source']}'s headline, published {at}, reads {headline}{punctuation} "
                "This headline-only account is unconfirmed; it does not establish the cause of market moves.")


def review_and_record(plan: dict, report: str, paragraphs: dict[str, str], research_report: str, analyst_review: dict | None = None) -> str:
    selected = selected_stories(plan)
    for story in selected:
        if story.get("title_truncated"):
            raise ValueError("Selected story headline is incomplete")
        if not primary_source(story) or story.get("story_type") != "announcement" or not materiality(story):
            raise ValueError("Selected story needs a material original-source report")
        if story["kind"] == "company" or story.get("event_evidence") is not None:
            checked_evidence(story)
        if report.count(paragraphs[story["id"]]) != 1:
            raise ValueError("Selected story evidence or qualification changed during narration")
    if len(selected) > MAX_STORIES:
        raise ValueError("News story budget exceeded")
    value = deepcopy(plan)
    counts = {decision: sum(story["decision"] == decision for story in value["candidates"]) for decision in ("selected", "skip", "wait")}
    value["research_sha256"] = hashlib.sha256(research_report.encode()).hexdigest()
    if analyst_review is not None:
        from src.intelligence.daily_brief_analysis import validate_review
        validate_review(analyst_review, research_report, report, selected)
        value["analyst_review"] = deepcopy(analyst_review)
    snapshot = re.search(r"\nMarket Snapshot\n(.*?)\n\n", research_report, re.S)
    moves = re.search(r"^[-•] Market moves: (.+)$", research_report, re.M)
    value["market_evidence"] = {"snapshot": snapshot[1][:900] if snapshot else "Unavailable", "moves": moves[1][:600] if moves else "Unavailable"}
    value["stages"] = [
        {"name": "Scan", "status": "pass", "detail": f"{len(value['candidates'])} candidates from cached public evidence"},
        {"name": "Source Check", "status": "limited" if counts["wait"] or value["issues"] else "pass", "detail": f"{counts['wait']} held; original publication dates and HTTPS URLs checked"},
        {"name": "Relevance", "status": "pass", "detail": "Material company developments and macro releases; original-source reports required"},
        {"name": "Selection", "status": "pass", "detail": f"{counts['selected']} selected / {counts['skip']} skipped; one story per represented company"},
        {"name": "Editorial Review", "status": "pass", "detail": "Original publisher, materiality, dates and complete selected wording checked"
         + f"; {sum(story['kind'] == 'company' for story in selected)} event-specific company reviews and {sum(len(story.get('event_evidence', {}).get('facts', [])) for story in selected)} sourced fact fields"
         + (f"; {len(analyst_review['insights'])} analyst insights matched to this edition's market, ranking and trade-plan evidence" if analyst_review is not None else "")},
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
    analysis = record.get("analyst_review", {})
    detail = f" {len(analysis['insights'])} analyst insights grounded in this research edition." if analysis else ""
    return f"{counts['selected']} sourced stories selected; {counts['skip']} skipped; {counts['wait']} held.{detail} Source wording and qualifications checked; edition {record['id']}."


def hold_reasons(candidates: list[dict]) -> list[tuple[str, int]]:
    """Summarize actual recorded decisions without inferring a quiet news day."""
    counts = {}
    for story in candidates:
        if story["decision"] != "wait":
            continue
        reason = story["reason"].lower()
        if "original company or agency report required" in reason:
            label = "Original-source confirmation needed"
        elif "older than 24 hours" in reason and "future-dated or" not in reason:
            label = "Publication older than 24 hours"
        elif "observation" in reason or "source" in reason and "stale" in reason:
            label = "Source observation stale or invalid"
        elif "future-dated" in reason:
            label = "Publication outside allowed time window"
        elif "headline" in reason and ("complete" in reason or "shortened" in reason):
            label = "Complete headline unavailable"
        elif "publisher" in reason or "authority" in reason:
            label = "Publisher identity mismatch"
        elif "publication" in reason or "timezone" in reason or "invalid date" in reason:
            label = "Original publication time unavailable"
        elif "url" in reason or "https" in reason:
            label = "Original link invalid"
        else:
            label = "Other evidence gaps"
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))


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
            reasons = hold_reasons(record["candidates"])
            if reasons:
                lines.append("Hold reasons: " + "; ".join(f"{label}: {count}" for label, count in reasons))
            if record.get("source_health"):
                lines += ["", feeds.coverage_summary(record["source_health"])]
                for row in record["source_health"]:
                    label = row["symbol"] or row["name"]
                    latest = " | newest " + row["latest_publication"][:10] if row["latest_publication"] else ""
                    lines.append(f"{label}: {row['status']} | {row['fresh']} fresh / {row['dated']} dated{latest} | {row['reason']}")
            lines += ["", "Market evidence: " + clean(record["market_evidence"]["moves"], 400)]
            analysis = record.get("analyst_review")
            if analysis:
                lines.append("Analyst inputs: " + ", ".join(analysis["evidence"]["source_sections"]) + ". Numerical scores retained.")
                focus = analysis["evidence"].get("company_focus")
                if focus:
                    lines.append("Companies in focus: " + ", ".join(focus["featured_symbols"]) + ". " + focus["rule"] + ".")
                    for company in focus["selected"]:
                        lines.append("Focus decision: " + company["symbol"] + " — " + company["role"] + ". " + company["why"])
        else:
            for row in record.get("source_health", []):
                if symbol and row["symbol"] == symbol:
                    lines.append(f"Publisher coverage: {row['name']} — {row['status']}; {row['reason']}; checked {row['checked_at'] or 'not checked'}")
            stories = [story for story in record["candidates"] if not symbol or symbol in story["symbols"] or symbol.casefold() == story.get("ipo", {}).get("issuer_id", "").casefold()]
            reasons = hold_reasons(stories)
            if reasons:
                lines.append("Hold reasons: " + "; ".join(f"{label}: {count}" for label, count in reasons))
            for story in stories[:12]:
                lines += ["", story["decision"].upper() + " — " + story["title"], "Reason: " + story["reason"],
                          "Source: " + story["source"] + " | Published: " + story["published"],
                          "Evidence: " + ("public SEC filing" if story.get("ipo", {}).get("form") or story.get("sec_filing") else "publisher/company announcement" if story["official"] else "headline only; confirmation pending"),
                          "Source check: " + story.get("source_check", "hold") + " | Cached at: " + str(story.get("source_checked_at") or "unavailable")]
                if story.get("story_type"):
                    lines.append("Story type: " + story["story_type"])
                if story.get("confirmed_by"):
                    lines.append("Original publisher verified: " + story["confirmed_by"])
                    lines.append("Investor topic: " + story["materiality"])
                if story.get("research_review"):
                    lines += ["Independent relevance review: " + story["research_review"]["reason"],
                              "Supporting source quote: " + story["research_review"]["quote"]]
                if story.get("event_evidence"):
                    from src.agents.analyst_agent import review_sourced_development
                    review = review_sourced_development(story)
                    event = review["evidence"]
                    lines.append("Event: " + event["event"] + " | Stage: " + event["stage"] + " | Evidence read: " + event["scope"])
                    if review["facts"]:
                        lines.append("Disclosed excerpt facts: " + review["facts"])
                    lines += ["Agent interpretation: " + review["why"], "Watch next: " + review["watch"]]
                if story.get("ipo"):
                    from src.intelligence.ipo_monitor import STAGES
                    lines.append("IPO stage: " + STAGES[story["ipo"]["stage"]])
                    for fact in story["ipo"].get("filing_analysis", {}).get("facts", [])[:10]:
                        lines.append(f"Filing fact: {fact['field']} | {fact['period']} | {fact['source_value']} {fact['unit']}")
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
