"""Issuer-confirmed earnings schedules, independent of news materiality filters."""

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import re
from zoneinfo import ZoneInfo

from src.intelligence.special_alert_sources import timestamp

NY = ZoneInfo("America/New_York")
MONTHS = {name: index for index, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
DATE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:,?\s+(\d{4}))?\b")
CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?\s*(Eastern(?: (?:Standard|Daylight))?(?: Time)?|Pacific(?: (?:Standard|Daylight))?(?: Time)?|EDT|EST|PDT|PST|ET|PT)\b", re.I)
NOTICE = re.compile(r"\b(?:sets?|schedules?)\b.{0,100}\b(?:conference call|financial results|earnings)\b|\b(?:will|to) (?:report|release|announce)\b.{0,80}\b(?:financial results|earnings)\b|\bannounces? (?:the |its )?date\b", re.I)
FUTURE = re.compile(r"\b(?:will (?:host|hold|conduct|report|release|announce)|scheduled (?:for|to)|plans to (?:report|release))\b", re.I)
REAFFIRMED = re.compile(
    r"^(?P<issuer>[^,.;]{2,70}?) will report (?:its )?[^,.;]{0,75}?financial results on "
    r"(?P<date>[^;]{8,60}?), at (?P<release>[^,]{1,56}), as previously scheduled, "
    r"followed by (?:its|the) earnings call at (?P<call>.{1,72})$", re.I)
SOURCE_FIELDS = ("title", "url", "source", "kind", "symbols", "official", "publisher_symbol",
                 "published", "source_checked_at", "source_excerpt", "excerpt_scope")


def event_date(match, published, window):
    month, raw_day, raw_year = match.groups()
    years = [int(raw_year)] if raw_year else [published.year, published.year+1]
    candidates = []
    weekday = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[, ]*$", window[:match.start()])
    for year in years:
        try: day = datetime(year, MONTHS[month], int(raw_day)).date()
        except ValueError: continue
        if (0 <= (day-published.astimezone(NY).date()).days <= 90
                and (weekday is None or day.strftime("%A") == weekday[1])):
            candidates.append(day)
    if len(candidates) != 1:
        raise ValueError("Issuer schedule year or weekday is ambiguous")
    return candidates[0], "explicit year" if raw_year else "unique future date within 90 days of original publication"


def scheduled_clock(text, day):
    clocks = []
    for clock in CLOCK.finditer(text):
        hour, minute, half, raw_zone = clock.groups()
        hour, minute = int(hour), int(minute or 0)
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            raise ValueError("Issuer schedule clock invalid")
        west = raw_zone.upper().startswith("P")
        zone = ZoneInfo("America/Los_Angeles" if west else "America/New_York")
        at = datetime(day.year, day.month, day.day, hour % 12 + (12 if half.lower() == "p" else 0), minute, tzinfo=zone)
        abbreviation = raw_zone.upper()
        if abbreviation in {"EST", "EDT", "PST", "PDT"} and abbreviation != at.tzname():
            raise ValueError("Issuer schedule DST offset conflicts with its date")
        if "STANDARD" in abbreviation and not at.tzname().endswith("ST") or "DAYLIGHT" in abbreviation and not at.tzname().endswith("DT"):
            raise ValueError("Issuer schedule DST wording conflicts with its date")
        clocks.append(at.astimezone(NY))
    if len(set(clocks)) > 1:
        raise ValueError("Issuer schedule clocks disagree")
    return clocks[0] if clocks else None


def reaffirmed_notice(story, now, published, text):
    from src.intelligence.news_editor import ALIASES
    if story.get("excerpt_scope") != "original release excerpt":
        return None
    symbol = story["publisher_symbol"]
    issuer_names = {name.casefold() for name in ALIASES.get(symbol, [symbol])}
    lines = [line.strip() for line in text.splitlines() if "as previously scheduled" in line.lower()]
    matches = [match for line in lines if (match := REAFFIRMED.fullmatch(line)) and match["issuer"].casefold() in issuer_names]
    if len(matches) != 1:
        return None
    match = matches[0]
    dates = list(DATE.finditer(match["date"]))
    call = match["call"]
    if len(dates) != 1 or not re.fullmatch(CLOCK.pattern + r"(?:\s*\(" + CLOCK.pattern + r"\))?\.?", call, re.I):
        return None
    try:
        day, basis = event_date(dates[0], published, match["date"])
        release_at = scheduled_clock(match["release"], day)
        call_at = scheduled_clock(call, day)
    except ValueError:
        return None
    if not release_at or not call_at or not release_at < call_at or not now <= call_at <= now + timedelta(days=60):
        return None
    source = deepcopy({key: story[key] for key in SOURCE_FIELDS})
    if story.get("evidence_checked_at"):
        source["evidence_checked_at"] = story["evidence_checked_at"]
    return {"schema": 2, "symbol": symbol, "event": "earnings conference call", "event_date": day.isoformat(),
            "event_at": call_at.isoformat(), "precision": "time", "year_basis": basis, "source_quote": match[0],
            "source": source, "source_sha256": hashlib.sha256(text.encode()).hexdigest()}


def parse_notice(story, now):
    from src.intelligence import news_editor as editor
    title = story.get("title", "")
    if story.get("kind") != "company":
        return None
    notice_title = NOTICE.search(title) and re.search(r"\b(?:financial results|earnings|quarter)\b", title, re.I)
    if not notice_title and story.get("excerpt_scope") != "original release excerpt":
        return None
    if re.search(r"\b(?:cancel|postpon|reschedul|withdraw)\w*\b", title, re.I):
        return None
    published, observed = timestamp(story.get("published")), timestamp(story.get("evidence_checked_at") or story.get("source_checked_at"))
    if (published is None or observed is None or not 0 <= (now-published).total_seconds() <= 90*86400
            or not -60 <= (now-observed).total_seconds() <= 21600 or (published-observed).total_seconds() > 60
            or not editor.primary_source(story) or not story.get("publisher_symbol")
            or story.get("excerpt_scope") not in {"publisher feed excerpt", "original release excerpt"}):
        return None
    text = story.get("source_excerpt", "")
    if not isinstance(text, str) or not 80 <= len(text) <= 6000:
        return None
    if not notice_title:
        return reaffirmed_notice(story, now, published, text)
    candidates = []
    for anchor in list(FUTURE.finditer(text))[:4]:
        window = text[anchor.start():anchor.start()+550].split("\n", 1)[0]
        window = re.split(r",?\s+which ended\b|(?<![aApP]\.[mM])\.\s+(?=[A-Z])", window, maxsplit=1)[0]
        dates = list(DATE.finditer(window))
        if len(dates) != 1:
            continue
        label = "earnings conference call" if re.search(r"\b(?:conference|earnings) call\b", window, re.I) else "financial-results release"
        if label == "financial-results release" and not re.search(r"\b(?:results|earnings)\b", window, re.I):
            continue
        try:
            day, basis = event_date(dates[0], published, window)
            if not now.astimezone(NY).date() <= day <= now.astimezone(NY).date()+timedelta(days=60):
                continue
            at = scheduled_clock(window[dates[0].end():], day)
            if at is not None and at < now:
                continue
            candidates.append({"symbol": story["publisher_symbol"], "event": label, "event_date": day.isoformat(),
                "event_at": at.isoformat() if at else "", "precision": "time" if at else "date", "year_basis": basis,
                "source_quote": window, "source": deepcopy({key: story[key] for key in SOURCE_FIELDS}),
                "source_sha256": hashlib.sha256(text.encode()).hexdigest()})
        except (ValueError, TypeError, KeyError):
            continue
    if len(candidates) != 1:
        return None
    return {"schema": 1, **candidates[0]}


def checked_notice(value, now):
    if not isinstance(value, dict) or parse_notice(value.get("source", {}), now) != value:
        raise ValueError("Issuer calendar evidence does not match the original notice")
    return value


def notices(candidates, now):
    rows, seen, conflicts, withdrawn = [], set(), set(), {}
    for story in candidates:
        if not isinstance(story, dict):
            continue
        if re.search(r"\b(?:cancel|postpon|reschedul|withdraw)\w*\b", str(story.get("title", "")), re.I):
            from src.intelligence.news_editor import primary_source
            try:
                published, observed = timestamp(story.get("published")), timestamp(story.get("source_checked_at"))
                if (story.get("kind") == "company" and primary_source(story) and published and observed
                        and re.search(r"\b(?:earnings|financial results)\b", story["title"], re.I)
                        and 0 <= (now-published).total_seconds() <= 90*86400 and -60 <= (now-observed).total_seconds() <= 21600
                        and (published-observed).total_seconds() <= 60):
                    symbol = story.get("publisher_symbol")
                    withdrawn[symbol] = max(withdrawn.get(symbol, published), published)
            except (ValueError, TypeError, KeyError): pass
        try: value = parse_notice(story, now)
        except (ValueError, TypeError, KeyError, AttributeError): continue
        if value is None or value["source"]["url"] in seen: continue
        seen.add(value["source"]["url"]); rows.append(value)
    for row in rows:
        same = [value for value in rows if value["symbol"] == row["symbol"] and value["event"] == row["event"]]
        if len({(value["event_date"], value["event_at"]) for value in same}) > 1:
            conflicts.add((row["symbol"], row["event"]))
    unique = {}
    for row in rows:
        key = (row["symbol"], row["event"])
        if key not in conflicts and not (row["symbol"] in withdrawn and timestamp(row["source"]["published"]) <= withdrawn[row["symbol"]]):
            unique.setdefault(key, row)
    return sorted(unique.values(), key=lambda row: (row["event_at"] or row["event_date"], row["symbol"]))[:20]


def cached_notices(now, symbols):
    from src.intelligence.news_editor import cache_candidates
    rows, _ = cache_candidates(now, symbols)
    return notices(rows, now)


def narration(row, zone, names):
    label = names.get(row["symbol"], row["symbol"])
    if row["event_at"]:
        when = timestamp(row["event_at"]).astimezone(zone).strftime("%A, %B %d at %I:%M %p %Z")
    else:
        when = datetime.fromisoformat(row["event_date"]).strftime("%A, %B %d") + "; the announcement does not supply a verified time"
    return f"{label} has scheduled its {row['event']} for {when}, according to its company announcement."


def earnings_focus(row):
    if row["symbol"] == "NVDA":
        return "Nvidia's data center sales and margin guidance will help show whether AI demand is translating into profitable growth."
    return "The company’s results and outlook will help test its sales and margin expectations."
