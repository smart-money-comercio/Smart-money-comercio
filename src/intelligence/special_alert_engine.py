"""Deterministic alert rules; facts and research implications stay separate."""

from __future__ import annotations

from datetime import datetime
import hashlib
import re

from src.intelligence.special_alert_sources import ALIASES, clean, timestamp


PRODUCTS = ("roadster", "robotaxi", "cybercab", "optimus", "cybertruck", "semi",
            "rubin", "blackwell", "vera", "cuda", "copilot", "azure", "grok",
            "falcon", "foundry", "gotham", "switchblade", "valkyrie")
SPECULATION = re.compile(r"\b(rumou?rs?|reportedly|might|could|may|expected to|likely to|speculat\w*|leak\w*|fan[- ]?made|rendering|render|prediction|predicts?|wish\w*)\b|\?", re.I)
EVENT_VERBS = re.compile(r"\b(unveil(?:s|ed|ing)?|reveal(?:s|ed|ing)?|releas(?:e|es|ed|ing)|introduc(?:es|ed|ing)|debut(?:s|ed)?|announc(?:es|ed|ing)|launch(?:es|ed|ing)?|showcas(?:es|ed|ing)|demonstrat(?:es|ed|ing)|demo(?:s|ed)?|rolls out|begins production|starts production|first deliveries)\b", re.I)
PRODUCT_WORDS = re.compile(r"\b(concepts?|prototypes?|products?|vehicles?|cars?|chips?|processors?|platforms?|robots?|robotaxi|roadster|cybercab|optimus|cybertruck|semi|rubin|blackwell|copilot|azure|falcon|foundry|gotham|switchblade|valkyrie|drones?|aircraft|technology|models?|systems?|services?|software|battery)\b", re.I)


def company_alert(item: dict, now: datetime, config: dict) -> dict | None:
    published = timestamp(item.get("published"))
    if published is None or not 0 <= (now - published).total_seconds() <= config["news_hours"] * 3600:
        return None
    title = clean(item.get("title"))
    if SPECULATION.search(title) or not EVENT_VERBS.search(title) or not PRODUCT_WORDS.search(title):
        return None
    if re.search(r"\b(anniversary|throwback|years? ago|recap of|remembering)\b", title, re.I):
        return None
    if re.search(r"\b(rival|competitor|fan)\b", title, re.I):
        return None
    symbol = item.get("symbol", "")
    if symbol not in config["symbols"]:
        return None
    lower = title.lower()
    verb = EVENT_VERBS.search(lower)
    actors = []
    for candidate in config["symbols"]:
        for name in (candidate.lower(),) + ALIASES.get(candidate, ()):
            actors.extend((match.start(), candidate) for match in re.finditer(r"\b" + re.escape(name) + r"\b", lower[:verb.start()]))
    if actors and max(actors)[1] != symbol:
        return None
    if not actors and not (symbol == "TSLA" and "musk" in lower[:verb.start()] and "tesla" in lower):
        return None
    if re.search(r"\b(will|to) (unveil|reveal|release|launch|introduce)\b|\b(schedules?|plans to)\b", lower[:verb.end()]):
        stage = "Event announced"
    elif re.search(r"\b(begins production|starts production|first deliveries|production launch)\b", lower):
        stage = "Production / deliveries reported"
    else:
        stage = "Concept / product reveal"
    products = sorted({"cybercab" if word == "robotaxi" else word for word in PRODUCTS
                       if re.search(r"\b" + word + r"\b", lower)})
    if products:
        topic = "+".join(products)
    else:
        # A conservative topic groups overlapping headlines about the same new product.
        words = sorted(set(re.findall(r"[a-z0-9]{4,}", lower)) - {
            "unveils", "unveiled", "reveals", "revealed", "announces", "announced", "launches",
            "launched", "introduces", "introduced", "tesla", "nvidia", "microsoft", "palantir",
            "first", "new", "with", "from", "that", "this", "after", "their", "today",
        })
        topic = "+".join(words[:8]) or "product"
    # The source publication date is evidence time, not a claimed event date.
    key = hashlib.sha256(f"{symbol}:{topic}:{stage}".encode()).hexdigest()[:24]
    official = bool(item.get("official"))
    text = "\n".join([
        f"🚀 Company Development — {symbol}",
        f"Stage: {stage}",
        "Evidence: " + ("Company announcement" if official else "News report — headline only; company confirmation pending"),
        f"Headline: {title}",
        f"Published: {published.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Source: {clean(item.get('source'), 90)}", str(item["url"]), "",
        "Research implication: Review demand, timing, costs and execution risk; a reveal alone does not establish revenue or a buy signal.",
        f"Next: /tickernews {symbol} · /tradeplan {symbol}",
    ])
    return {"key": "company:" + key, "level": 2 if official else 1, "kind": "company",
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
        alert = company_alert(item, now, config)
        if alert and (alert["key"] not in candidates or alert["level"] > candidates[alert["key"]]["level"]):
            candidates[alert["key"]] = alert
    result = sorted(candidates.values(), key=lambda a: a["published"], reverse=True)
    market = market_alert(observations, now, config)
    return ([market] if market else []) + result
