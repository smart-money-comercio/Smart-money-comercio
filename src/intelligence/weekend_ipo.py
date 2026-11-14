"""Weekly IPO context from original offering terms."""

from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit

from src.intelligence import ipo_monitor, news_live_sources as feeds, sec_contact, weekend_inputs as evidence


PRICE = re.compile(
    r"\binitial public offering price (?:is expected to be between \$(?P<low>[0-9]{1,5}(?:\.[0-9]{2})?) "
    r"and \$(?P<high>[0-9]{1,5}(?:\.[0-9]{2})?) per share\b|"
    r"per share will be between \$(?P<sec_low>[0-9]{1,5}(?:\.[0-9]{2})?) "
    r"and \$(?P<sec_high>[0-9]{1,5}(?:\.[0-9]{2})?)(?!\d|[,.]\d))", re.I,
)
AI_PURPOSE = re.compile(r"\b(?:artificial intelligence|AI|compute|computing|data centers?|Claude)\b", re.I)
COMMITMENTS = re.compile(
    r"\bcommitted spend of approximately \$(?P<total>[0-9]{1,4}(?:\.[0-9]{1,3})?) billion, "
    r"substantially all of which is related to compute and infrastructure\..{0,700}?"
    r"Approximately \$(?P<near>[0-9]{1,4}(?:\.[0-9]{1,3})?) billion of these commitments are due in the "
    r"12 months following (?P<date>[A-Z][a-z]+ \d{1,2}, 20\d{2})\.", re.I,
)
ADVANCED_STAGES = {"prospectus", "priced", "trading planned", "trading", "withdrawn"}


def profile(source, periods, now):
    issuer = ipo_monitor.checked(source)
    published = evidence.clock(source["published"])
    observed = evidence.fresh(source["source_checked_at"], now)
    if not evidence.clock(periods["evidence_start"]) <= published <= now or published > observed + timedelta(minutes=1):
        return None
    filing = source["ipo"]
    if filing["stage"] not in {"plan", "filing", "amendment", "terms"} or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 .&'()-]{1,69}", issuer["name"]):
        return None
    if filing["issuer_id"] not in ipo_monitor.DEFAULT_ISSUERS and not AI_PURPOSE.search(filing["excerpt"]):
        return None
    ranges = {(Decimal(low or sec_low), Decimal(high or sec_high))
              for low, high, sec_low, sec_high in PRICE.findall(filing["excerpt"])}
    symbol = filing["proposed_symbol"]
    if not symbol:
        # Some prospectus covers put the sentence period inside the quotation marks.
        match = re.search(r"\bunder (?:the )?(?:trading )?symbol\s+[\"“']([A-Z][A-Z0-9.-]{0,8})\.[\"”']", filing["excerpt"])
        symbol = match[1] if match else ""
    if len(ranges) != 1 or not symbol:
        return None
    low, high = next(iter(ranges))
    if not 0 < low < high:
        return None

    name = issuer["name"]
    local = published.astimezone(evidence.NY)
    day = f"{local:%B} {local.day}"
    if filing["form"]:
        summary = f"In a {day} filing, {name} gave an indicative IPO price range of "
    else:
        summary = f"On {day}, {name} announced an indicative IPO price range of "
    summary += f"${low.normalize():f} to ${high.normalize():f} per share. The proposed ticker is {symbol}."
    # The filing's opening pages may also provide the scale and timing of
    # compute commitments. Both amounts must come from the same passage.
    risk = source.get("weekend_prospectus_excerpt")
    if risk:
        if (not filing["form"] or not isinstance(risk, dict) or set(risk) != {"text", "prefix_sha256"}
                or risk["prefix_sha256"] != filing.get("filing_source", {}).get("prefix_sha256")
                or not isinstance(risk["text"], str) or len(risk["text"]) > 1000):
            raise ValueError("Weekend IPO commitments lack matched filing evidence")
        match = COMMITMENTS.fullmatch(risk["text"])
        if not match:
            raise ValueError("Weekend IPO commitments do not match the original passage")
        total, near = (Decimal(match[key]) for key in ("total", "near"))
        if not 0 < near <= total:
            raise ValueError("Weekend IPO commitment amounts are inconsistent")
        summary += (f" In the same filing, {name} reported approximately ${total.normalize():f} billion in purchase and lease "
                    f"commitments, almost entirely for computing and infrastructure. About ${near.normalize():f} billion "
                    f"was scheduled to come due in the twelve months following {match['date']}.")
    source_id = sha256((source["url"] + "|" + source["published"]).encode()).hexdigest()[:16]
    proof = {key: source[key] for key in ("title", "url", "source", "published", "source_checked_at", "official", "ipo")}
    if risk:
        proof["weekend_prospectus_excerpt"] = risk
    return {"id": source_id, "name": name, "summary": summary, "source": proof}


def choose(periods, now, sources):
    """A recent verified later stage supersedes earlier indicative terms."""
    current = []
    closed = set()
    latest = {}
    for source in sources[:50]:
        try:
            ipo_monitor.checked(source)
            at = evidence.clock(source["published"])
            if not evidence.clock(periods["evidence_start"]) <= at <= now:
                continue
            filing = source["ipo"]
            issuer_id = filing["issuer_id"]
            if filing["stage"] in ADVANCED_STAGES:
                closed.add(issuer_id)
            latest[issuer_id] = max(at, latest.get(issuer_id, at))
            if value := profile(source, periods, now):
                current.append(value)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
    candidates = (row for row in current if row["source"]["ipo"]["issuer_id"] not in closed
                  and evidence.clock(row["source"]["published"]) == latest[row["source"]["ipo"]["issuer_id"]])
    return max(candidates, key=lambda row: (row["source"]["published"],
                                           bool(row["source"].get("weekend_prospectus_excerpt")),
                                           row["id"]), default=None)


def read_prefix(url, prefix=False, *, user_agent=None):
    from src.intelligence.special_alert_sources import request_bytes

    if urlsplit(url).hostname != "www.sec.gov":
        raise ValueError("Unexpected filing authority")
    cached = feeds.get_cached_source(url)
    if cached and cached.get("status") == "error":
        raise ValueError(cached.get("error") or "SEC filing retry pending")
    try:
        return request_bytes(url, prefix_bytes=1_000_000 if prefix else None, authority_domain="sec.gov",
                             exact_url=True, user_agent=user_agent)
    except OSError as error:
        attempted = time.time()
        status = error.code if isinstance(error, HTTPError) else None
        pause = 3600 if status in {403, 404} else 900 if status == 429 else 300
        if status and error.headers is not None:
            try:
                pause = min(21600, max(pause, int(error.headers.get("Retry-After", pause))))
            except (TypeError, ValueError):
                pass
        feeds.set_cached_source(url, {"url": url, "status": "error", "error": f"HTTP {status}" if status else type(error).__name__,
                                     "fetched_at_epoch": attempted, "retry_after_epoch": attempted + pause})
        raise


def refresh(periods, now, *, allow_network):
    """Reuse fresh IPO evidence, with a bounded original SEC check when needed."""
    from src.config.special_alerts import settings
    from src.intelligence.special_alert_sources import source_error

    if not settings()["ipo_enabled"]:
        return None, []
    cached = ipo_monitor.read_cache().get("items", [])[:40]
    cached_terms = choose(periods, now, cached)
    if (cached_terms and cached_terms["source"].get("weekend_prospectus_excerpt")) or not allow_network:
        return cached_terms, []
    agent = sec_contact.user_agent()
    if not agent:
        return cached_terms, ["Weekly IPO filings require the existing SEC contact setting"]

    records, issues = [], []
    try:
        issuers = ipo_monitor.issuers()
    except ValueError:
        return None, ["Weekly IPO issuer configuration is invalid"]
    hours = (now - evidence.clock(periods["evidence_start"])).total_seconds() / 3600
    # The existing monitor's two tracked AI issuers bound this independent pass.
    for issuer_id in ipo_monitor.DEFAULT_ISSUERS:
        issuer = issuers.get(issuer_id, {})
        if not issuer.get("cik"):
            continue
        url = f"https://data.sec.gov/submissions/CIK{int(issuer['cik']):010d}.json"
        response = feeds.fetch_url(url, user_agent=agent)
        if isinstance(response, dict) and response.get("status") == "error":
            issues.append(f"Weekly IPO check for {issuer['name']} unavailable ({response.get('error') or 'SEC submissions unavailable'})")
            continue
        try:
            if not isinstance(response, dict) or response.get("status") != "ok" or response.get("final_url") != url:
                raise ValueError("SEC submissions response redirected")
            published_check = evidence.fresh(response["fetched_at_epoch"], now)
            excerpts = {}

            def read(url, prefix=False):
                raw = read_prefix(url, prefix, user_agent=agent)
                if match := COMMITMENTS.search(ipo_monitor.visible(raw)):
                    excerpts[url] = {"text": match[0], "prefix_sha256": sha256(raw[:1_000_000]).hexdigest()}
                return raw

            sources = ipo_monitor.sec_items(issuer_id, issuer, response["body"].encode(), read, now, hours,
                                            latest_only=True, observed=published_check)
            for source in sources:
                if excerpt := excerpts.get(source["url"]):
                    source["weekend_prospectus_excerpt"] = excerpt
                records.append(source)
        except (ValueError, KeyError, TypeError, OSError) as error:
            issues.append(f"Weekly IPO check for {issuer['name']} unavailable ({source_error(error)})")
    return choose(periods, now, [*records, *cached]), issues


def checked(value, periods, now):
    if value != profile(value["source"], periods, now):
        raise ValueError("Weekend IPO facts or original-source evidence changed")
    return value
