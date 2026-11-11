"""Dated issuer results for rechecked major moves; never a price-cause claim.

Alphabet keeps its existing SEC/issuer proof. Intel adds a deliberately narrow
reader for the opening results summary, not financial tables or adjusted EPS.
All reads belong to the normal publisher refresh; narration is cache-only.
"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from hashlib import sha256
import re
from urllib.parse import urlsplit

from src.intelligence import alphabet_earnings as alphabet
from src.intelligence.special_alert_sources import timestamp

INTEL_FEED = "https://www.intc.com/news-events/press-releases/rss"
INTEL_TITLE = r"Intel Reports (First|Second|Third|Fourth)[ -]Quarter (20\d{2}) Financial Results"
QUARTERS = ("first", "second", "third", "fourth")
MAX_AGE = 72 * 3600
MAX_BASELINE_AGE = 120 * 86400
BASELINE_SOURCE = "Dated Intel results"


def intel_period(title):
    match = re.fullmatch(INTEL_TITLE, str(title), re.I)
    return (match[1].lower(), int(match[2])) if match else None


def intel_summary(text, title):
    period = intel_period(title)
    if not period or not isinstance(text, str) or not text.startswith(title + "\n"):
        raise ValueError("Intel results need their exact original heading")
    # The native summary precedes management commentary and comparative tables.
    # Bind its reported period to the issuer's explicit opening sentence.
    marker = re.search(r"\bIntel Corporation today reported ([a-z]+)[ -]quarter (20\d{2}) financial results\.", text[:3000], re.I)
    if not marker or (marker[1].lower(), int(marker[2])) != period:
        raise ValueError("Intel results heading and reported period disagree")
    opening = text[:marker.end()].strip()
    if not re.search(r"\nNews Summary\n", opening[:1200]):
        raise ValueError("Intel opening news summary unavailable")
    return opening


def intel_facts(text, title):
    """Current revenue and separately qualified next-quarter revenue guidance.

    Full summary lines bind period, units and measure. Tables, EPS, historical
    comparisons and management quotations cannot supply these fields.
    """
    try:
        opening = intel_summary(text, title)
    except ValueError:
        return []
    quarter, year = intel_period(title)
    next_index = QUARTERS.index(quarter) + 1
    future = (QUARTERS[next_index % 4], year + (next_index == 4))
    lines = opening.split("\nNews Summary\n", 1)[1].splitlines()
    money = r"\$(\d+(?:\.\d+)?) (billion|million)"
    actual_pattern = (re.escape(quarter) + r"[ -]quarter revenue was " + money
        + r"(?:, (?:up|down) \d+(?:\.\d+)?% year-over-year(?: \(YoY\))?)?\.")
    forecast_pattern = r"Forecasting ([a-z]+)[ -]quarter (20\d{2}) revenue of " + money + r" to " + money + r"\.?"
    actual, forecasts = [], []
    for line in lines:
        match = re.fullmatch(actual_pattern, line, re.I)
        if match:
            actual.append({"field": "reported_revenue", "value": "$" + match[1] + " " + match[2].lower(),
                           "period": f"{quarter} quarter {year}", "basis": "reported", "evidence": line})
        clause = line.split(";", 1)[0]
        match = re.fullmatch(forecast_pattern, clause, re.I)
        if match:
            if ((match[1].lower(), int(match[2])) != future or match[4].lower() != match[6].lower()
                    or Decimal(match[3]) > Decimal(match[5])):
                # A contradictory outlook is withheld, rather than relabeled.
                return []
            forecasts.append({"field": "forecast_revenue", "value": "$" + match[3] + " " + match[4].lower() + " to $" + match[5] + " " + match[6].lower(),
                              "period": f"{future[0]} quarter {future[1]}", "basis": "forecast", "evidence": clause})
    if len(actual) != 1 or len(forecasts) > 1:
        return []
    return actual + forecasts


def checked(record, now, *, baseline=False):
    if not isinstance(record, dict):
        raise ValueError("Company earnings context must be an original-source record")
    if record.get("symbol") == "GOOG" and not baseline:
        return alphabet.checked(record, now)
    schema = 3 if baseline else 2
    if (type(record.get("schema")) is not int or record["schema"] != schema or record.get("symbol") != "INTC"
            or record.get("route") != "issuer" or record.get("source") != "Intel Investor Relations"
            or not isinstance(record.get("text"), str) or len(record["text"]) > 3000
            or sha256(record["text"].encode()).hexdigest() != record.get("sha256")
            or intel_summary(record["text"], record.get("title", "")) != record["text"]
            or not intel_facts(record["text"], record["title"])):
        raise ValueError("Intel earnings context lost its original summary proof")
    native = record.get("publisher_clock", "")
    try:
        original = datetime.fromisoformat(native.replace("Z", "+00:00"))
    except ValueError:
        original = parsedate_to_datetime(native)
    published, observed = timestamp(record.get("published")), timestamp(record.get("observed"))
    age = (now-published).total_seconds() if published else -1
    valid_age = MAX_AGE < age <= MAX_BASELINE_AGE if baseline else 0 <= age <= MAX_AGE
    url = urlsplit(record.get("url", ""))
    slug = re.sub(r"[ -]+", "-", record["title"].lower())
    if (original.tzinfo is None or timestamp(native) != published or published is None or observed is None
            or not valid_age
            or not -60 <= (now-observed).total_seconds() <= 21600 or (published-observed).total_seconds() > 60
            or original.date().isoformat() != record.get("release_date")
            or url.scheme != "https" or url.netloc != "www.intc.com" or url.query or url.fragment
            or re.fullmatch(r"/news-events/press-releases/detail/\d+/" + re.escape(slug), url.path) is None):
        raise ValueError("Intel results authority or original publication/observation clock invalid")
    preface = record["text"].split("\nNews Summary\n", 1)[0]
    if not re.search(r"\b(?:" + original.strftime("%B|%b") + r")\.?\s+" + str(original.day)
                     + r",\s+" + str(original.year) + r"\b", preface):
        raise ValueError("Intel visible release day does not match its native feed clock")
    return deepcopy(record)


def from_issuer(raw, now, *, baseline=False):
    if (raw.get("publisher_symbol") != "INTC" or raw.get("source") != "Intel Investor Relations"
            or raw.get("official") is not True or raw.get("excerpt_scope") != "original release excerpt"):
        raise ValueError("Original Intel release body required")
    text = intel_summary(raw.get("source_excerpt", ""), raw.get("title", ""))
    clock = raw["published"]
    try:
        native = datetime.fromisoformat(clock.replace("Z", "+00:00"))
    except ValueError:
        native = parsedate_to_datetime(clock)
    published = timestamp(clock)
    if published is None:
        raise ValueError("Intel release needs its original zoned feed clock")
    observed = raw.get("evidence_checked_at") if baseline else raw.get("evidence_checked_at") or raw["source_checked_at"]
    return checked({"schema": 3 if baseline else 2, "route": "issuer", "symbol": "INTC", "source": raw["source"],
        "title": raw["title"], "text": text, "sha256": sha256(text.encode()).hexdigest(),
        "release_date": native.date().isoformat(), "publisher_clock": clock, "published": published.isoformat(),
        "observed": observed, "url": raw["url"]}, now, baseline=baseline)


def matching(values, symbol):
    issuer = "GOOG" if symbol in {"GOOG", "GOOGL"} else symbol
    return next((row for row in values if row.get("symbol") == issuer), None)


def rechecked_intel(event):
    return event.get("symbol") == "INTC" and event.get("status") == "rechecked" and abs(event["reported_move"]) >= 5


def latest_intel_result(raw, now, *, baseline=False):
    max_age = MAX_BASELINE_AGE if baseline else MAX_AGE
    known = []
    for item in raw:
        if (item.get("publisher_symbol") == "INTC" and item.get("source") == "Intel Investor Relations"
                and item.get("official") is True and intel_period(item.get("title", ""))):
            published = timestamp(item.get("published"))
            if published and 0 <= (now-published).total_seconds() <= max_age:
                known.append((published, item))
    latest_clock = max((published for published, _ in known), default=None)
    records = []
    for published, item in known:
        if published == latest_clock:
            try:
                records.append(from_issuer(item, now, baseline=baseline))
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
    conflict = len({repr(intel_facts(row["text"], row["title"])) for row in records}) > 1
    return (records[0] if records and not conflict else None), conflict


def cached_baseline(raw, now, events):
    if any(rechecked_intel(event) for event in events):
        return latest_intel_result(raw, now, baseline=True)[0]
    return None


def cached_context(raw, now, events):
    values, backup_health = alphabet.cached_context(raw, now, events)
    health = []
    if any(rechecked_intel(event) for event in events):
        latest, conflict = latest_intel_result(raw, now)
        if latest:
            values.append(latest)
        health.append({"symbol": "INTC", "status": "available" if latest else "limited",
            "reason": "Dated original results available; context only" if latest else
                      "Conflicting original results; context withheld" if conflict else
                      "No usable original results summary within 72 hours and a six-hour source observation"})
    return values, backup_health, health


def retain_intel(record, now, events, stories, focus, *, baseline=False):
    value = checked(record, now, baseline=baseline)
    if not any(rechecked_intel(event) for event in events):
        raise ValueError("Earnings context needs a matching rechecked major move")
    current_events = {"earnings", "guidance"} if baseline else {"earnings"}
    fresh = any("INTC" in story.get("symbols", []) and story.get("event_evidence", {}).get("event") in current_events
                for story in stories)
    if not fresh and any(item["symbol"] == "INTC" for item in (focus or {}).get("selected", [])):
        return value
    return None


def retain(values, now, events, stories, focus):
    if not isinstance(values, list) or len(values) > 2 or not all(isinstance(row, dict) for row in values):
        raise ValueError("Company earnings context exceeds its edition bound")
    if len({row.get("symbol") for row in values}) != len(values):
        raise ValueError("Duplicate issuer earnings context")
    old = [row for row in values if row.get("symbol") == "GOOG"]
    retained = alphabet.retain(old, now, events, stories, focus) if old else []
    for row in values:
        if row.get("symbol") == "GOOG":
            continue
        value = retain_intel(row, now, events, stories, focus)
        if value:
            retained.append(value)
    return retained


def baseline_watch(record):
    actual, *outlook = intel_facts(record["text"], record["title"])
    day = datetime.fromisoformat(record["release_date"]).strftime("%B %d, %Y").replace(" 0", " ")
    if outlook:
        forecast = outlook[0]
        return (f"Compare reported {forecast['period']} revenue with the {forecast['value']} forecast from its {day} release. "
                "Check how much cash operations generate alongside those sales.")
    return (f"Compare the next reported sales with {actual['period']} revenue of {actual['value']} from its {day} release. "
            "Check operating costs and cash flow for signs of improving profitability.")


def intel_narration(record, *, day=None):
    facts = intel_facts(record["text"], record["title"])
    actual = facts[0]
    day = day or datetime.fromisoformat(record["release_date"]).strftime("%B %d").replace(" 0", " ")
    text = f"Its {day} release reported {actual['period']} revenue of {actual['value']}."
    if len(facts) > 1:
        forecast = facts[1]
        text += f" Management forecast {forecast['period']} revenue of {forecast['value']}; that is an outlook, not a reported result."
        scales = {"million": Decimal(10)**6, "billion": Decimal(10)**9}
        def amount(value):
            found = re.fullmatch(r"\$(\d+(?:\.\d+)?) (million|billion)", value)
            return Decimal(found[1]) * scales[found[2]]
        reported = amount(actual["value"])
        low, high = (amount(value) for value in forecast["value"].split(" to "))
        if high < reported:
            text += " The entire forecast range is below the revenue just reported."
        elif low > reported:
            text += " The entire forecast range is above the revenue just reported."
    return text


def intel_watch(record):
    return ("Watch delivery against the revenue outlook, operating costs and cash generation." if len(intel_facts(record["text"], record["title"])) > 1 else
            "Watch the next company outlook, profitability and cash generation.")


def narration(record, event):
    if record["symbol"] == "GOOG":
        return alphabet.narration(record, event)
    move = f"Shares {'fell' if event['reported_move'] < 0 else 'rose'} {abs(event['reported_move']):.1f} percent in the quoted regular session."
    return ("Intel — recent earnings context: " + move + " " + intel_narration(record)
            + " Investor focus: " + intel_watch(record) + " These dated results do not establish the cause of the price move.")


def audit(record):
    if record["symbol"] == "GOOG":
        return alphabet.audit(record)
    baseline = record["schema"] == 3
    heading = "DATED RESULTS BENCHMARK — Intel" if baseline else "DATED EARNINGS CONTEXT — Intel"
    purpose = ("Purpose: compare the next results with a dated issuer benchmark." if baseline else
               "Purpose: dated context for a rechecked move; not counted as a fresh news story or proof of its cause.")
    lines = [heading, "Release: " + record["title"], "Release date: " + record["release_date"],
             "Original publisher clock: " + record["published"], "Source: " + record["source"] + " | Checked: " + record["observed"],
             purpose]
    lines.extend("Retained fact: " + fact["field"] + " | " + fact["value"] + " | " + fact["period"] + " | " + fact["basis"]
                 + "\nSupporting source text: " + fact["evidence"] for fact in intel_facts(record["text"], record["title"]))
    return lines + ["Release document: " + record["url"]]
