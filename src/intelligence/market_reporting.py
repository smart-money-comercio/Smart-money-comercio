"""Dated market reporting and conditional connections, separate from issuer facts."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from src.intelligence.research_evidence import SourceRejected
from src.intelligence.special_alert_sources import timestamp
from src.intelligence.special_alert_company_sources import PublicationPage, publication_time


SOURCE_SECTION = "Dated market reporting"
HOSTS = {"reuters.com": "Reuters", "www.reuters.com": "Reuters",
         "finance.yahoo.com": "Yahoo Finance", "apnews.com": "Associated Press"}
SIGNALS = {
    "gold_down": r"\bgold\b.{0,90}\b(?:fell|falling|dropped|declined|slid|sank|sinks|tumbled|weakened)\b",
    "gold_up": r"\bgold\b.{0,70}\b(?:rose|rallied|rebounded|surged|climbed)\b",
    "yields_up": r"\b(?:Treasury|bond) yields?\b.{0,70}\b(?:rose|jumped|surged|climbed|increased|higher)\b|\b(?:higher|rising) Treasury yields?\b",
    "yields_down": r"\b(?:Treasury|bond) yields?\b.{0,70}\b(?:fell|dropped|declined|eased)\b|\b(?:lower|falling) Treasury yields?\b",
    "dollar_up": r"\bdollar\b.{0,65}\b(?:rose|jumped|surged|climbed|strengthened|highest|stronger)\b|\b(?:strong|stronger|firm|firmer|rising) (?:US |U\.S\. )?dollar\b",
    "dollar_down": r"\bdollar\b.{0,65}\b(?:fell|dropped|declined|weakened|eased)\b|\b(?:weaker|falling) dollar\b",
    "equities_down": r"\b(?:stocks|equities|shares|S&P 500|Nasdaq)\b.{0,65}\b(?:fell|dropped|declined|slid|sank|tumbled)\b",
    "oil_up": r"\b(?:oil|crude) (?:prices? )?\b.{0,65}\b(?:rose|jumped|surged|climbed|increased)\b|\b(?:higher|rising) (?:oil|crude) prices?\b",
    "oil_down": r"\b(?:oil|crude) (?:prices? )?\b.{0,65}\b(?:fell|dropped|declined|slid|sank)\b",
    "supply_disruption": r"\b(?:shipping|shipments|oil supply|oil production|exports|pipeline|strait|ports?)\b.{0,75}\b(?:halted|disrupted|closed|suspended|blocked|closure)\b",
    "inflation_up": r"\b(?:inflation|fuel costs|energy costs|input costs|consumer prices)\b.{0,60}\b(?:rose|increased|accelerated|climbed|higher)\b",
    "copper_down": r"\bcopper\b.{0,65}\b(?:fell|dropped|declined|slid|sank)\b",
    "demand_down": r"\b(?:Chinese demand|China.s demand|industrial demand|factory output|manufacturing output)\b.{0,65}\b(?:fell|dropped|declined|slowed|weakened|contracted)\b",
    "currency_down": r"\b(?:euro|yen|sterling|emerging.market currencies)\b.{0,65}\b(?:fell|dropped|declined|weakened|slid)\b",
}
RECIPES = (
    ("gold_rates", {"gold_down", "yields_up", "dollar_up"},
     "weaker gold alongside higher Treasury yields and a firmer dollar",
     "Higher yields can pressure both gold demand and growth valuations.",
     "Watch whether gold stabilizes as yields and the dollar ease."),
    ("rates_growth", {"yields_up", "equities_down"},
     "rising Treasury yields alongside falling stocks",
     "Higher financing costs can challenge growth valuations and debt-funded investment.",
     "Check whether yields ease and company funding plans change."),
    ("energy_supply", {"oil_up", "supply_disruption"},
     "rising oil prices alongside disrupted energy or shipping flows",
     "Sustained disruption could raise fuel and transport costs for businesses.",
     "Watch supply restoration and the next company margin guidance."),
    ("energy_inflation", {"oil_up", "inflation_up"},
     "higher oil prices alongside rising inflation or business input costs",
     "Persistent cost pressure could squeeze margins and complicate rate decisions.",
     "Check subsequent price releases and company cost guidance."),
    ("industrial_demand", {"copper_down", "demand_down"},
     "falling copper prices alongside weaker industrial demand or factory output",
     "That combination warrants checking volume and pricing at industrial suppliers.",
     "Watch the next production data and original company orders."),
    ("dollar_currency", {"dollar_up", "currency_down"},
     "a stronger dollar alongside weaker foreign currencies",
     "Currency translation can reduce overseas sales reported in dollars.",
     "Check multinational currency guidance and the next dollar reading."),
)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password
            or parts.port not in (None, 443) or len(url) > 2048):
        raise ValueError("Market reporting publisher is not configured")
    path = parts.path
    if re.search(r"/(?:opinion|breakingviews|press-releases|sponsored|advertorial)(?:/|$)", path, re.I):
        raise ValueError("Commentary or promotional page is not a dated market report")
    allowed = (re.fullmatch(r"/(?:markets|world|business|sustainability)/.+-\d{4}-\d{2}-\d{2}/?", path) if HOSTS[parts.hostname] == "Reuters" else
               re.fullmatch(r"/(?:markets/.+|news)/.+-\d{9}\.html", path) if parts.hostname == "finance.yahoo.com" else
               re.fullmatch(r"/article/[a-z0-9-]+", path))
    if not allowed:
        raise ValueError("Specific dated market article required")
    return urlunsplit(("https", parts.hostname, path, "", ""))


def configured(url: str) -> bool:
    try:
        canonical_url(url)
        return True
    except (ValueError, TypeError):
        return False


def facts(text: str) -> dict:
    result = {}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = " ".join(sentence.split())
        # A reported move may precede a separate, explicitly prospective
        # explanation. Read the factual clause and retain its exact passage.
        claim = re.split(r"\b(?:on|amid) expectations?\b", sentence, maxsplit=1, flags=re.I)[0]
        if (not 20 <= len(sentence) <= 500
                or re.search(r"\b(?:if|could|may|might|would|forecast|predict\w*|expected|will|not|never)\b", claim, re.I)):
            continue
        for key, pattern in SIGNALS.items():
            if key not in result and re.search(pattern, claim, re.I):
                result[key] = sentence
    for noun in ("gold", "yields", "dollar", "oil"):
        if noun + "_up" in result and noun + "_down" in result:
            result.pop(noun + "_up"); result.pop(noun + "_down")
    return result


# An attributed trading observation, distinct from verified terms of a filing.
IPO_LEVEL = re.compile(
    r"(?P<name>Anthropic|OpenAI)(?: (?:shares|stock))? (?:fell|dropped|slid|traded|rose|climbed|rebounded)"
    r"(?: (?:more than |about |nearly )?\d+(?:\.\d+)?% to)?"
    r"(?: (?:more than |about |nearly )?\$\d+(?:\.\d{1,2})?)?"
    r" (?P<side>below|above) (?:its|the) IPO price of \$(?P<price>[1-9]\d{0,3}(?:\.\d{1,2})?)"
    r"(?=[,.]?(?:\s|$))",
)


def ipo_benchmark(text):
    observations = {}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        match = IPO_LEVEL.match(sentence.strip())
        if not match or len(sentence) > 500:
            continue
        tail = sentence.strip()[match.end():].strip()
        if tail not in ("", ".") and not tail.startswith(","):
            continue
        if re.search(r"\b(?:last (?:year|month|week)|yesterday|in 20\d\d|if|would|could|before|earlier|but|correction)\b", sentence, re.I):
            continue
        key = (match["name"], match["side"], match["price"])
        observations[key] = sentence.strip()
    if len(observations) != 1:
        return None
    (name, side, price), passage = next(iter(observations.items()))
    return {"family": "ipo_benchmark", "summary": f"{name} trading {side} its ${price} IPO price",
            "implication": "The offer price gives readers a benchmark for how demand has changed since the debut.",
            "watch": "Compare the next regular close with the price paid by IPO investors.",
            "facts": {"reported_ipo_comparison": passage}}


def connection(text: str, *, schema=2) -> dict | None:
    if schema == 2 and (benchmark := ipo_benchmark(text)):
        return benchmark
    evidence = facts(text)
    for family, needed, summary, implication, watch in RECIPES:
        if needed <= evidence.keys():
            return {"family": family, "summary": summary, "implication": implication, "watch": watch,
                    "facts": {key: evidence[key] for key in sorted(needed)}}
    return None


def article(lead: dict, now: datetime, fetch) -> dict:
    url = canonical_url(lead["url"])
    raw = fetch(url)
    if not isinstance(raw, bytes) or len(raw) > 2_000_000:
        raise ValueError("Invalid market article body")
    page = PublicationPage(); page.feed(raw.decode("utf-8")); page.close()
    title = page.title or (page.headings[0] if len(page.headings) == 1 else "")
    if not 10 <= len(title) <= 1000:
        raise ValueError("Market article title unavailable")
    nodes = []
    def walk(value, depth=0):
        if depth > 20:
            return
        if isinstance(value, dict):
            types = value.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if (isinstance(types, list) and set(types) & {"NewsArticle", "ReportageNewsArticle"}
                    and value.get("headline", "").strip().casefold() == title.casefold()):
                nodes.append(value)
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)
    for script in page.scripts:
        try:
            walk(json.loads(script))
        except (ValueError, TypeError):
            continue
    if len(nodes) != 1 or "datePublished" not in nodes[0]:
        raise ValueError("A matching dated news article is required")
    node = nodes[0]
    published = publication_time(raw, title, url=url)
    if timestamp(node["datePublished"]) != published or not 0 <= (now-published).total_seconds() <= 86400:
        raise SourceRejected("Market report is future-dated or outside the 24-hour news window", status="expired", published=published.isoformat())
    modified = timestamp(node.get("dateModified"))
    if "dateModified" in node and (modified is None or not published <= modified <= now):
        raise ValueError("Article update clock is invalid or after the cutoff")
    text = node.get("articleBody")
    if not isinstance(text, str) or not text.strip():
        from src.intelligence.news_original_sources import ArticleBody
        parser = ArticleBody(url=url); parser.feed(raw.decode("utf-8")); parser.close()
        text = "".join(parser.parts)
        if title not in raw.decode("utf-8") or not page.headings or title not in page.headings:
            raise ValueError("The visible article body is not bound to the report title")
    from src.intelligence.story_analysis import release_text
    text = release_text(text)
    if len(text) < 120:
        raise ValueError("Original market article body unavailable; headline or description is insufficient")
    publisher = HOSTS[urlsplit(url).hostname]
    if publisher == "Yahoo Finance":
        # Yahoo can carry original reporting or a clearly identified wire report.
        name = node.get("publisher", {})
        name = name.get("name", "") if isinstance(name, dict) else name
        if not isinstance(name, str) or name.casefold() not in {"yahoo finance", "yahoo", "reuters", "associated press", "ap"}:
            raise ValueError("Yahoo article does not identify a supported reporting publisher")
        wire = re.search(r"\((Reuters|AP)\)", text[:500])
        if name.casefold() in {"reuters", "associated press", "ap"} and not wire:
            raise ValueError("Syndicated article lacks its wire attribution in the original body")
        publisher = {"Reuters": "Reuters", "AP": "Associated Press"}[wire[1]] if wire else publisher
    else:
        name = node.get("publisher", {})
        name = name.get("name", "") if isinstance(name, dict) else name
        if not isinstance(name, str) or not re.search(r"Reuters" if publisher == "Reuters" else r"Associated Press|\bAP\b", name, re.I):
            raise ValueError("Market article publisher attribution is missing")
    link = connection(text)
    if not link:
        raise SourceRejected("No supported cross-market development extracted from the article body", status="rejected")
    proof = {"schema": 2, "url": url, "title": title, "published": published.isoformat(), "observed": now.isoformat(),
             "publisher": publisher, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "connection": link}
    if modified:
        proof["modified"] = modified.isoformat()
    value = {"url": url, "title": title, "published": proof["published"], "source_checked_at": proof["observed"],
             "source": publisher, "official": False, "kind": "macro", "publisher_symbol": "", "symbol": "", "symbols": [],
             "relevant": True, "source_excerpt": text, "excerpt_scope": "reported article body", "reporting_evidence": proof}
    checked(value, now)
    return value


def supports_benchmark(proof, quote):
    link = proof.get("connection", {})
    return link.get("family") != "ipo_benchmark" or quote == link["facts"]["reported_ipo_comparison"]


def checked(value: dict, now: datetime | None = None) -> dict:
    proof = value["reporting_evidence"]
    url = canonical_url(value["url"])
    allowed = {HOSTS[urlsplit(url).hostname]}
    if "Yahoo Finance" in allowed:
        allowed |= {"Reuters", "Associated Press"}
    if (not isinstance(proof, dict) or type(proof.get("schema")) is not int or proof.get("schema") not in (1, 2) or value.get("official") is not False
            or value.get("kind") != "macro" or value.get("symbols") != [] or value.get("publisher_symbol") != ""
            or proof.get("url") != url or value["url"] != url or proof.get("title") != value.get("title")
            or proof.get("published") != value.get("published") or proof.get("observed") != value.get("source_checked_at")
            or proof.get("publisher") != value.get("source") or proof.get("publisher") not in allowed
            or not isinstance(proof.get("text"), str) or not 120 <= len(proof["text"]) <= 6000
            or proof["text"] != value.get("source_excerpt") or value.get("excerpt_scope") != "reported article body"
            or proof.get("sha256") != hashlib.sha256(proof["text"].encode()).hexdigest()
            or not proof.get("connection") or proof["connection"] != connection(proof["text"], schema=proof["schema"])):
        raise ValueError("Market reporting proof or extracted connection changed")
    published, observed = timestamp(proof["published"]), timestamp(proof["observed"])
    if (published is None or observed is None or not 0 <= (observed-published).total_seconds() <= 86400
            or now is not None and (not 0 <= (now-published).total_seconds() <= 86400 or not -60 <= (now-observed).total_seconds() <= 21600)):
        raise ValueError("Market reporting clocks are unavailable or stale")
    if now is not None and proof["schema"] == 2 and observed > now:
        raise ValueError("Article observation is after the edition cutoff")
    if "modified" in proof:
        updated = timestamp(proof["modified"])
        if updated is None or not published <= updated <= observed:
            raise ValueError("Article update clock differs from the observed edition")
    review = value.get("research_review")
    if review is not None and (not isinstance(review, dict) or not isinstance(review.get("response_id"), str) or not review["response_id"]
            or type(review.get("score")) is not int or not 65 <= review["score"] <= 100
            or not isinstance(review.get("quote"), str) or not 20 <= len(review["quote"]) <= 500 or review["quote"] not in proof["text"]):
        raise ValueError("Market reporting lost its independent relevance review")
    if review and not supports_benchmark(proof, review["quote"]):
        raise ValueError("IPO benchmark needs review of the quoted trading evidence")
    return proof


def retain(values: list[dict], now: datetime) -> list[dict]:
    if not isinstance(values, list) or len(values) > 2:
        raise ValueError("Invalid market reporting selection")
    families, result = set(), []
    for value in values:
        proof = checked(value, now)
        if not value.get("research_review") or proof["connection"]["family"] in families:
            raise ValueError("Market context needs reviewed, distinct developments")
        families.add(proof["connection"]["family"])
        result.append(deepcopy(value))
    return result


def cached(now: datetime) -> list[dict]:
    from src.intelligence.hourly_research import approved
    result, families, seen = [], set(), set()
    for value in sorted(approved(now), key=lambda row: timestamp(row["published"]), reverse=True):
        if not value.get("reporting_evidence"):
            continue
        try:
            proof = checked(value, now)
            family = proof["connection"]["family"]
            key = (proof["title"].casefold(), proof["published"])
            if family in families or key in seen:
                continue
            result.append(value); families.add(family); seen.add(key)
        except (ValueError, KeyError, TypeError):
            continue
        if len(result) == 2:
            break
    return retain(result, now)


def health() -> dict:
    """Capture the latest desk state for this edition without starting work."""
    from src.intelligence.hourly_research import settings, status
    value = status()
    bodies = value.get("details", {}).get("market_reports", 0)
    state = value.get("status")
    return {"enabled": settings()["enabled"],
            "status": state if state in {"complete", "limited", "paused", "not run", "unavailable"} else "unavailable",
            "run_at": value.get("started") if timestamp(value.get("started")) else "",
            "market_bodies": bodies if type(bodies) is int and 0 <= bodies <= 8 else 0}


def health_line(value: dict) -> str:
    if value.get("enabled") is not True:
        return "Market reporting: disabled for this edition. /researchdesk status"
    return ("Market reporting: no eligible reviewed article used in this edition; latest hourly scan "
            + value["status"] + (" at " + value["run_at"] if value["run_at"] else "")
            + f"; {value['market_bodies']} market article bodies verified in that scan. /researchdesk history")


def summary(value: dict) -> str:
    proof = checked(value)
    day = timestamp(proof["published"]).astimezone(ZoneInfo("America/New_York")).strftime("%B %d").replace(" 0", " ")
    return f"In a {day} report, {proof['publisher']} described {proof['connection']['summary']}."


def source_line(value: dict) -> str:
    return "Market reporting source — " + value["source"] + " · " + value["url"]


def segment(evidence: dict) -> str:
    value = evidence["market_context"][0]
    proof = checked(value)
    link = proof["connection"]
    moves = evidence["moves"]
    parts = []
    if evidence.get("session"):
        for key, label in (("S&P", "the S&P 500"), ("Nasdaq", "the Nasdaq Composite")):
            if key in moves:
                change = moves[key]
                parts.append(label + (" was unchanged" if change == 0 else f" {'rose' if change > 0 else 'fell'} {abs(change):.2f} percent"))
    if parts:
        day = datetime.strptime(evidence["session"], "%Y-%m-%d").strftime("%A, %B %d")
        clock = f"During the {day} regular session" if evidence["is_open"] else f"At the {day} regular-session close"
        lead = clock + ", " + "; ".join(parts) + ". "
    else:
        lead = "Current index coverage is incomplete. The dated article provides context; it does not supply live market prices. "
    text = lead + summary(value) + " Analyst view: " + link["implication"] + " " + link["watch"]
    from src.intelligence.market_brief import word_count, MIN_MARKET_WORDS, MAX_MARKET_WORDS
    if not MIN_MARKET_WORDS <= word_count(text) <= MAX_MARKET_WORDS:
        raise ValueError("Reported market context exceeds the market narration budget")
    return text


def detailed(values: list[dict]) -> str:
    lines = []
    for value in values:
        proof = checked(value)
        link = proof["connection"]
        # Keep the source clock and URL on the same evidence line so the
        # detailed report's section budgets cannot separate them from the copy.
        lines.append("• " + summary(value) + " Analyst view: " + link["implication"] + " " + link["watch"]
                     + " Published: " + proof["published"] + " | Observed: " + proof["observed"] + " " + value["url"])
    return "\n".join(lines)
