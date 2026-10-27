"""Deterministic alert rules; facts and research implications stay separate."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re

from src.intelligence.special_alert_sources import ALIASES, clean, company_url, timestamp


PRODUCTS = ("roadster", "robotaxi", "cybercab", "optimus", "cybertruck", "semi",
            "rubin", "blackwell", "vera", "cuda", "copilot", "azure", "grok",
            "falcon", "foundry", "gotham", "switchblade", "valkyrie", "maia", "nemotron", "aip")
SPECULATION = re.compile(r"\b(rumou?rs?|reportedly|might|could|may|expected to|likely to|speculat\w*|leak\w*|fan[- ]?made|rendering|render|prediction|predicts?|wish\w*)\b|\?", re.I)
EVENT_VERBS = re.compile(r"\b(unveil(?:s|ed|ing)?|reveal(?:s|ed|ing)?|releas(?:e|es|ed|ing)|introduc(?:es|ed|ing)|debut(?:s|ed)?|announc(?:es|ed|ing)|launch(?:es|ed|ing)?|showcas(?:es|ed|ing)|demonstrat(?:es|ed|ing)|demo(?:s|ed)?|rolls out|begins production|starts production|first deliveries)\b", re.I)
PRODUCT_WORDS = re.compile(r"\b(concepts?|prototypes?|products?|vehicles?|cars?|chips?|processors?|platforms?|robots?|robotaxi|roadster|cybercab|optimus|cybertruck|semi|rubin|blackwell|copilot|azure|falcon|foundry|gotham|switchblade|valkyrie|drones?|aircraft|technology|models?|systems?|services?|software|battery)\b", re.I)


def company_event(title: str):
    """Classify concrete developments; routine scheduling and stock chatter are excluded."""
    if re.search(r"\b(earnings|results) (date|call|webcast)|\bdate of .*?(earnings|results)|\bannounces? (?:its |the )?(?:date|webcast|conference)|\bearnings preview\b|\b(?:will|plans to|to) (?:report|release|announce)\b.{0,80}\b(?:financial results|quarterly results|earnings)\b", title, re.I):
        return None
    patterns = [
        ("guidance", r"\b(raises?|cuts?|lowers?|reduces?|withdraws?|reaffirms?|updates?)\b.{0,65}\b(guidance|revenue outlook|earnings outlook)\b", "Guidance update reported"),
        ("earnings", r"\b(reports?|releases?|announces?)\b.{0,70}\b(financial results|quarterly results|earnings results|Q[1-4] results|Q[1-4] 20\d{2} .{0,25}(?:revenue|earnings|EPS))\b", "Financial results reported"),
        ("risk", r"\b(confirms?|discloses?|suffers?|reports?)\b.{0,25}\b(data breach|ransomware attack|major outage|product recall)\b|\b(faces?|discloses?)\b.{0,35}\b(antitrust investigation|regulatory investigation)\b", "Business risk reported"),
        ("acquisition", r"\b(agrees? to acquire|to acquire|acquires?|announces? acquisition|announces? .*?merger)\b", "Acquisition / merger announced"),
        ("contract", r"\b(wins?|secures?|awarded|signs?|forms?|renews?|extends?|expands?|announces?|partners?|collaborates?|team(?:s)? up)\b.{0,100}\b(contract|strategic partnership|strategic alliance|agreement)\b|\b(partners?|collaborates?|teams? up) with\b|\b(partners?|collaborates?) to\b.{0,100}\b(AI|software|cloud|defense|banking|technology)\b", "Contract / partnership announced"),
    ]
    for kind, pattern, stage in patterns:
        match = re.search(pattern, title, re.I)
        if match:
            return kind, stage, match
    verb = EVENT_VERBS.search(title)
    if not verb or not PRODUCT_WORDS.search(title):
        return None
    if re.search(r"\b(will|to) (unveil|reveal|release|launch|introduce)\b|\b(schedules?|plans to)\b", title[:verb.end()], re.I):
        stage = "Event announced"
    elif re.search(r"\b(begins production|starts production|first deliveries|production launch)\b", title, re.I):
        stage = "Production / deliveries reported"
    else:
        stage = "Concept / product reveal"
    return "product", stage, verb


def company_is_actor(item: dict, title: str, verb, config: dict, kind: str = "product") -> bool:
    symbol = item["symbol"]
    # Only the final clause before the event verb supplies its actor.
    prefix = re.split(r"\b(?:while|whereas|after|as)\b|[;:]", title[:verb.start()], flags=re.I)[-1]
    actors = []
    for candidate in set(config["symbols"]) | set(ALIASES):
        names = [(candidate, 0)] if len(candidate) >= 3 else []
        names += [(name, re.I) for name in ALIASES.get(candidate, ())]
        for name, flags in names:
            actors.extend((m.start(), m.end(), candidate) for m in re.finditer(r"\b" + re.escape(name) + r"\b", prefix, flags))
    if actors:
        actors = sorted(set(actors))
        last = max(actors)
        if last[2] == symbol:
            if re.search(r"\b(stock|shares)\b.{0,30}\b(falls?|rises?|surges?|drops?|rallies|slips?)\b", prefix[last[1]:], re.I):
                return False
            return True
        # A named joint actor is distinct from an incidental stock-price mention.
        for start, end, candidate in actors:
            if candidate == symbol and start < last[0] and re.fullmatch(r"\s*(?:,?\s*and|&)\s*", prefix[end:last[0]], re.I):
                return True
        if kind == "contract":
            for name in (symbol,) + ALIASES.get(symbol, ()):
                if re.search(r"\bwith\s+" + re.escape(name) + r"\b", title[verb.end():], re.I):
                    return True
        return False
    if item.get("official") and item.get("publisher_symbol") == symbol and company_url(symbol, item.get("url", "")):
        # A publisher's brand-free headline is usable; another named company's
        # reveal is not reassigned simply because the feed discussed it.
        from src.intelligence.special_alert_sources import mentions_company
        if not mentions_company(title, symbol):
            lead = title[verb.end():].lstrip()[:60]
            for other in ALIASES:
                if other != symbol and mentions_company(lead, other):
                    return False
        return True
    return symbol == "TSLA" and bool(re.search(r"\bmusk\b", prefix, re.I)) and bool(re.search(r"\btesla\b", title, re.I))


def company_alert(item: dict, now: datetime, config: dict) -> dict | None:
    published = timestamp(item.get("published"))
    if published is None or not 0 <= (now - published).total_seconds() <= config["news_hours"] * 3600:
        return None
    title = clean(item.get("title"))
    if SPECULATION.search(title) or re.search(r"\b(anniversary|throwback|years? ago|recap of|remembering|rival|competitor|fan)\b", title, re.I):
        return None
    symbol = item.get("symbol", "")
    if symbol not in config["symbols"]:
        return None
    event = company_event(title)
    if not event:
        return None
    kind, stage, verb = event
    if not company_is_actor(item, title, verb, config, kind):
        return None
    lower = title.lower()
    products = sorted({"cybercab" if word == "robotaxi" else word for word in PRODUCTS
                       if re.search(r"\b" + word + r"\b", lower)})
    if products and kind == "product":
        topic = "+".join(products)
    else:
        words = sorted(set(re.findall(r"[a-z0-9]{4,}", lower)) - {
            "unveils", "unveiled", "reveals", "revealed", "announces", "announced", "launches",
            "launched", "introduces", "introduced", "tesla", "nvidia", "microsoft", "palantir",
            "first", "new", "with", "from", "that", "this", "after", "their", "today",
        })
        topic = "+".join(words[:8]) or "product"
        if kind != "product":
            topic = kind + ":" + topic
    # Preserve existing product keys and receipts across the expanded rule set.
    key = hashlib.sha256(f"{symbol}:{topic}:{stage}".encode()).hexdigest()[:24]
    official = bool(item.get("official"))
    implications = {
        "product": "Review demand, timing, costs and execution risk; a reveal alone does not establish revenue or a buy signal.",
        "contract": "Check contract value, duration, funded commitments and revenue recognition; a partnership alone does not establish revenue.",
        "earnings": "Compare actual results with prior guidance and expectations; check margins, cash flow and management's outlook.",
        "guidance": "Verify the direction, scope and assumptions of the guidance change against the original disclosure.",
        "risk": "Verify affected operations, severity, company response and potential financial exposure; the impact remains unquantified.",
        "acquisition": "Review deal terms, funding, approvals and integration risk; an announced transaction may not close.",
    }
    text = "\n".join([
        (f"⚠️ Company Risk — {symbol}" if kind == "risk" else f"📣 Company Development — {symbol}"), f"Stage: {stage}",
        "Evidence: " + ("Company announcement" if official else "News report — headline only; company confirmation pending"),
        f"Headline: {title}", f"Published: {published.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Source: {clean(item.get('source'), 90)}", str(item["url"]),
        *( ["Original publication time source: " + item["publication_url"]] if item.get("publication_url") else []),
        "", "Research implication: " + implications[kind],
        f"Next: /tickernews {symbol} · /tradeplan {symbol}",
    ])
    return {"key": "company:" + key, "level": 2 if official else 1, "kind": "company", "event_type": kind,
            "published": published.isoformat(), "text": text, "ttl": 48 * 3600,
            "symbols": [symbol], "stage": stage, "evidence": item,
            "expires": published.timestamp() + config["news_hours"] * 3600}


def market_alert(observations: dict, now: datetime, config: dict) -> dict | None:
    hits, severe = [], False
    for symbol, prefix in (("^GSPC", "sp"), ("^IXIC", "nasdaq")):
        row = observations.get(symbol)
        if not row:
            continue
        daily = row["change"]
        if daily <= -config[prefix + "_drop"] + 1e-9:
            hits.append(f"{row['name']} one-session drop reached {config[prefix + '_drop']:.2f}%")
        if daily <= -config[prefix + "_severe"] + 1e-9:
            severe = True
        if (row.get("two_day") is not None and row.get("prior_change") is not None
                and daily < 0 and row["prior_change"] < 0
                and row["two_day"] <= -config[prefix + "_two_day"] + 1e-9):
            hits.append(f"{row['name']} fell across two consecutive trading sessions (compounded)")
    if not hits:
        return None
    indexes = [observations[s] for s in ("^GSPC", "^IXIC") if s in observations]
    dates = {row["session_date"] for row in indexes}
    if len(dates) != 1:
        return None
    level = 2 if severe else 1
    lines = ["🔴 Severe Market Selloff" if severe else "🟠 Market Selloff Alert", "Trigger: " + "; ".join(hits), ""]
    for symbol in ("^GSPC", "^IXIC", "^VIX"):
        row = observations.get(symbol)
        if row is None:
            lines.append(f"{symbol}: unavailable")
            continue
        asof = timestamp(row["asof"])
        line = f"{row['name']}: {row['change']:+.2f}% vs previous close"
        if symbol == "^VIX":
            line += f" | level {row['price']:.2f}"
        elif row.get("two_day") is not None:
            line += f" | two sessions {row['two_day']:+.2f}%"
        lines.append(line + f" | as of {asof.strftime('%H:%M UTC')}")
    lines.extend(["", f"Session: {indexes[0]['session_date']} · Regular session / closing check",
                  "Source: Yahoo Finance chart; quotes may be delayed.",
                  indexes[0]["url"], "",
                  "Research implication: Review growth/AI exposure, position size and near-term catalysts.",
                  "Cause: Not established by price data. Check /macronews before attributing the move.",
                  "Next: /risk MSFT · /tradeplans · /weeklycalendar"])
    return {"key": "market:" + dates.pop(), "level": level, "kind": "market",
            "published": now.isoformat(), "text": "\n".join(lines), "ttl": 2 * 86400,
            "symbols": [], "evidence": observations,
            "expires": min(timestamp(row["asof"]).timestamp() for row in indexes) + config["max_quote_age"]}


def evaluate(observations: dict, news: list[dict], now: datetime, config: dict) -> list[dict]:
    candidates = {}
    for item in news:
        if item.get("kind") == "ipo":
            from src.intelligence.ipo_monitor import alert as ipo_alert
            alert = ipo_alert(item, now, config) if config.get("ipo_enabled") else None
        else:
            alert = company_alert(item, now, config)
        if alert and (alert["key"] not in candidates or alert["level"] > candidates[alert["key"]]["level"]):
            candidates[alert["key"]] = alert
    result = sorted(candidates.values(), key=lambda a: (a["kind"] == "ipo", a["published"]), reverse=True)
    market = market_alert(observations, now, config)
    return ([market] if market else []) + result
