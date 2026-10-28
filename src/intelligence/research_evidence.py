"""Terminal source outcomes and read-only, dated original-publisher evidence."""

from datetime import datetime
import hashlib

from src.intelligence.special_alert_sources import timestamp
from src.intelligence.story_analysis import release_text


class SourceRejected(ValueError):
    def __init__(self, reason: str, *, status: str, published: str = ""):
        if status not in {"expired", "rejected"}:
            raise ValueError("Invalid terminal source outcome")
        super().__init__(reason)
        self.status, self.published = status, published


def publisher_reports(now: datetime, symbols: list[str], latest: dict, identity, key_for, *, include_unread=False, cache=None) -> tuple[list[dict], dict]:
    """Reuse the brief's validated publisher cache without network or cache writes."""
    from src.intelligence import news_editor as editor, news_live_sources as feeds
    health = []
    items, issues = editor.cache_candidates(now, symbols, health=health, **({"cache": cache} if cache is not None else {}))
    available = sum(row["status"] == "available" for row in health)
    coverage = {"available": available, "limited": len(health)-available, "issues": len(issues)}
    result, seen = [], set()
    for raw in items:
        try:
            if raw.get("official") is not True or raw.get("authority_mismatch") or not raw.get("relevant"):
                continue
            url = editor.canonical_url(raw["url"])
            publisher = identity(url)
            if publisher is None or publisher["symbol"] != raw.get("publisher_symbol", ""):
                continue
            source = next((source for source in feeds.NEWS_SOURCES if source["name"] == raw["source"] and feeds.is_original_source(source)), None)
            if source is None:
                continue
            published, observed = timestamp(raw["published"]), timestamp(raw["source_checked_at"])
            excerpt_at = timestamp(raw.get("evidence_checked_at")) or observed
            if (published is None or observed is None or excerpt_at is None or not 0 <= (now-published).total_seconds() <= 86400
                    or not -60 <= (now-observed).total_seconds() <= 21600 or not -60 <= (now-excerpt_at).total_seconds() <= 21600):
                continue
            observed = min(observed, excerpt_at)
            if (published-observed).total_seconds() > 60 or not isinstance(raw.get("title"), str) or not 1 <= len(raw["title"]) <= 1000:
                continue
            scope = raw.get("excerpt_scope", "headline only")
            text = " ".join(release_text(raw.get("source_excerpt", "")).split())
            kind = editor.story_type(raw)
            usable = scope in {"publisher feed excerpt", "original release excerpt"} and len(text) >= 80
            if (not include_unread and (not usable or kind != "announcement")) or (include_unread and kind not in {"announcement", "context"}):
                continue
            key = key_for(url)
            previous = latest.get(key)
            if previous and previous.get("review", {}).get("final") in {"approved", "skip"}:
                prior = previous.get("verified") or {}
                if not prior or timestamp(prior.get("published")) == published:
                    continue
            if key in seen:
                continue
            proof = {"schema": 1, "url": url, "title": raw["title"], "published": published.isoformat(), "observed": observed.isoformat(),
                "publisher": publisher, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "feed_url": source["url"], "scope": scope}
            value = {"title": raw["title"], "original_title": raw["title"], "url": url, "published": published.isoformat(), "source_checked_at": observed.isoformat(),
                "source": source["name"], "official": True, "publisher_symbol": publisher["symbol"], "symbol": publisher["symbol"],
                "symbols": [publisher["symbol"]] if publisher["symbol"] else [], "kind": "company" if publisher["symbol"] else "macro", "relevant": True,
                "source_excerpt": text if usable else "", "excerpt_scope": scope if usable else "headline only"}
            value["publisher_reference"] = {key: proof[key] for key in ("url", "title", "published", "observed", "feed_url")}
            value["publisher_reference"]["publisher_clock"] = raw["published"]
            if usable:
                value["discovery_evidence"] = proof
            result.append(value); seen.add(key)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    result.sort(key=lambda value: timestamp(value["published"]), reverse=True)
    diverse, rest, publishers = [], [], set()
    for value in result:
        if value["source"] in publishers:
            rest.append(value)
        else:
            diverse.append(value); publishers.add(value["source"])
    return (diverse+rest)[:20], coverage
