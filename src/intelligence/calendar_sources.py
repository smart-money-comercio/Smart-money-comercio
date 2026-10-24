"""Publisher release schedules, independent of Nasdaq's unnamed time column."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
import json
import logging
import re
from urllib.error import HTTPError
import urllib.request
from zoneinfo import ZoneInfo

from src.intelligence import calendar_source_cache as source_cache


NY = ZoneInfo("America/New_York")
BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
DOL_URL = "https://oui.doleta.gov/unemploy/claims_arch.asp"
FED_URL = "https://www.federalreserve.gov/json/calendar.json"
MICHIGAN_URL = "https://www.sca.isr.umich.edu/"
SOURCE_URLS = {"BLS": BLS_URL, "BEA": BEA_URL, "DOL": DOL_URL,
               "Fed": FED_URL, "Michigan": MICHIGAN_URL}
MAX_BYTES = 1_000_000


def request_schedule(url: str) -> str:
    if url not in SOURCE_URLS.values():
        raise ValueError("Unknown release-schedule source")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/calendar,application/json,text/html,*/*"})
    with urllib.request.urlopen(request, timeout=8) as response:
        if response.geturl().split("/", 3)[:3] != url.split("/", 3)[:3]:
            raise ValueError("Release schedule redirected to another host")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Release schedule is too large")
    return raw.decode("utf-8-sig")


def category(name: str, publisher: str = "") -> str:
    name = " ".join(unescape(str(name)).lower().split())
    if publisher == "BLS":
        exact = {"consumer price index": "cpi", "producer price index": "ppi",
                 "employment situation": "jobs", "job openings and labor turnover survey": "jolts",
                 "employment cost index": "eci", "productivity and costs": "productivity",
                 "u.s. import and export price indexes": "trade_prices"}
        return exact.get(name, "")
    if publisher == "BEA":
        # National releases also use the abbreviated GDP title. Regional GDP
        # and Puerto Rico releases cannot confirm the national GDP schedule.
        if re.match(r"^(?:gross domestic product|gdp)(?:$|,| \((?:advance|second|third|initial|updated) estimate\))", name):
            return "gdp"
        if name.startswith("personal income and outlays"):
            return "pce"
        if name.startswith("u.s. international trade in goods and services"):
            return "trade"
        return ""
    if name in {"fomc statement", "fed interest rate decision", "fomc statement / rate decision"}:
        return "fomc_decision"
    if name == "fomc press conference":
        return "fomc_press"
    if name in {"fomc minutes", "fomc meeting minutes"}:
        return "fomc_minutes"
    if re.fullmatch(r"(?:university of )?michigan consumer sentiment(?: \((?:prelim|preliminary|final)\))?", name):
        return "michigan_sentiment"
    if re.fullmatch(r"(?:initial(?: jobless| unemployment)? claims|continuing jobless claims|jobless claims 4-week avg\.?)", name):
        return "claims"
    if re.search(r"\b(?:cpi|consumer price index)\b", name):
        return "cpi"
    if re.search(r"\b(?:ppi|producer price index)\b", name):
        return "ppi"
    if re.search(r"\b(?:non.?farm payrolls?|unemployment rate|average hourly earnings|participation rate)\b", name):
        return "jobs"
    if "jolts" in name or "job openings" in name:
        return "jolts"
    if "employment cost" in name:
        return "eci"
    if "productivity" in name or "unit labor costs" in name:
        return "productivity"
    if "import price" in name or "export price" in name:
        return "trade_prices"
    if "gdp" in name and "gdpnow" not in name:
        return "gdp"
    if name in {"pce prices", "core pce prices"}:
        return "gdp"  # Quarterly GDP components, distinct from monthly PCE indexes.
    if any(term in name for term in ("pce price", "personal consumption expenditure", "personal income", "personal spending")):
        return "pce"
    if name == "trade balance":
        return "trade"
    return ""


def parse_ics(text: str, publisher: str) -> list[dict]:
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text:
        raise ValueError("Publisher did not return an iCalendar schedule")
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    revisions = {}
    for body in re.findall(r"BEGIN:VEVENT\s*(.*?)END:VEVENT", unfolded, re.S)[:1500]:
        ids = re.findall(r"^UID:(.+)$", body, re.M)
        sequences = re.findall(r"^SEQUENCE:(.+)$", body, re.M)
        if len(ids) != 1 or len(sequences) > 1:
            continue
        try:
            sequence = int(sequences[0].strip()) if sequences else 0
        except ValueError:
            continue
        uid = ids[0].strip()
        old = revisions.get(uid)
        if old is None or sequence > old[0]:
            revisions[uid] = (sequence, body)
        elif sequence == old[0] and body != old[1]:
            revisions[uid] = (sequence, "")  # Conflicting equal revisions are not a verified schedule.
    result = []
    for _, body in revisions.values():
        properties = {}
        for line in body.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            properties.setdefault(key.split(";", 1)[0], []).append((key, value.strip()))
        if len(properties.get("DTSTART", [])) != 1 or len(properties.get("SUMMARY", [])) != 1:
            continue
        name = properties["SUMMARY"][0][1].replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
        kind = category(name, publisher)
        if not kind or any(value.upper() == "CANCELLED" for _, value in properties.get("STATUS", [])):
            continue
        key, raw = properties["DTSTART"][0]
        try:
            if raw.endswith("Z"):
                at = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            else:
                match = re.search(r"(?:^|;)TZID=([^;:]+)", key)
                if not match:
                    continue  # Floating or all-day dates do not establish a release time.
                zone = match[1].strip('"')
                if zone in {"US-Eastern", "US/Eastern"}:
                    zone = "America/New_York"
                at = datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(zone))
            result.append({"category": kind, "name": name[:180], "at": at.astimezone(timezone.utc).isoformat(),
                           "publisher": publisher, "url": SOURCE_URLS[publisher]})
        except (ValueError, KeyError):
            continue
    return result


def parse_claims_schedule(text: str, dates: list[date]) -> list[dict]:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())
    if not re.search(r"published each week on Thursday morning at 8:30\s*am\s*(?:EST|Eastern)", text, re.I):
        raise ValueError("DOL did not provide the recognized weekly publication schedule")
    exceptions = {}
    for month, day, year, hour, minute in re.findall(
            r"(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+(\d{1,2}):(\d{2})\s*AM\s*(?:EST|EDT|Eastern)", text):
        shifted = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
        if shifted.weekday() <= 4:
            regular = shifted + timedelta(days=3 - shifted.weekday())
            exceptions[regular] = (shifted, time(int(hour), int(minute)))
    result = []
    if not dates:
        return result
    cursor = min(dates) - timedelta(days=7)
    while cursor <= max(dates) + timedelta(days=7):
        if cursor.weekday() == 3:
            day, clock = exceptions.get(cursor, (cursor, time(8, 30)))
            at = datetime.combine(day, clock, NY)
            result.append({"category": "claims", "name": "Unemployment Insurance Weekly Claims",
                           "at": at.astimezone(timezone.utc).isoformat(), "publisher": "DOL", "url": DOL_URL})
        cursor += timedelta(days=1)
    return result


def parse_fed_calendar(text: str) -> list[dict]:
    payload = json.loads(text.lstrip("\ufeff"))
    if (not isinstance(payload, dict) or not isinstance(payload.get("events"), list)
            or len(payload["events"]) > 4000):
        raise ValueError("Fed did not return the recognized event calendar")
    titles = {"FOMC Meeting": ("fomc_decision", "FOMC Statement / Rate Decision"),
              "FOMC Press Conference": ("fomc_press", "FOMC Press Conference"),
              "FOMC Minutes": ("fomc_minutes", "FOMC Minutes")}
    result = []
    for row in payload["events"]:
        if (not isinstance(row, dict) or row.get("type") != "FOMC"
                or not isinstance(row.get("title"), str) or row["title"] not in titles):
            continue
        month, day, clock = row.get("month", ""), row.get("days", ""), row.get("time", "")
        if not all(isinstance(value, str) for value in (month, day, clock)):
            continue
        # The calendar's day is the announcement day, rather than the first
        # date mentioned in the meeting description. Never expand a range.
        if not re.fullmatch(r"\d{4}-\d{2}", month) or not re.fullmatch(r"\d{1,2}", day.strip()):
            continue
        match = re.fullmatch(r"(\d{1,2}):(\d{2})\s+([ap])\.m\.", clock.strip(), re.I)
        if not match:
            continue
        hour, minute = int(match[1]), int(match[2])
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            continue
        try:
            scheduled_day = date.fromisoformat(month + "-" + day.strip().zfill(2))
            # Fed FOMC announcement clocks use US Eastern Time. The actual
            # clock comes from the calendar; no 14:00/14:30 default is inserted.
            at = datetime.combine(scheduled_day, time(hour % 12 + (12 if match[3].lower() == "p" else 0), minute), NY)
        except ValueError:
            continue
        kind, name = titles[row["title"]]
        result.append({"category": kind, "name": name, "at": at.astimezone(timezone.utc).isoformat(),
                       "publisher": "Fed", "url": FED_URL})
    return result


def parse_michigan_schedule(text: str) -> list[dict]:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())
    matches = re.findall(
        r"Next data release:\s*(Monday|Tuesday|Wednesday|Thursday|Friday),\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})"
        r"\s+for\s+(Final|Preliminary|Prelim)\s+[A-Za-z]+\s+data at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s+(ET|EST|EDT)\b",
        text, flags=re.I)
    if len(matches) != 1:
        raise ValueError("Michigan did not provide one dated release with an Eastern time")
    weekday, month, day, year, stage, hour, minute, meridiem, _ = matches[0]
    months = {name: number for number, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}
    if month.lower() not in months:
        raise ValueError("Michigan release month is unrecognized")
    release_day = date(int(year), months[month.lower()], int(day))
    hour, minute = int(hour), int(minute or 0)
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if weekdays[release_day.weekday()] != weekday.lower() or not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise ValueError("Michigan release date or clock is inconsistent")
    at = datetime.combine(release_day, time(hour % 12 + (12 if meridiem.lower() == "pm" else 0), minute), NY)
    stage = "Final" if stage.lower() == "final" else "Preliminary"
    return [{"category": "michigan_sentiment", "name": f"Michigan Consumer Sentiment ({stage})",
             "at": at.astimezone(timezone.utc).isoformat(), "publisher": "Michigan", "url": MICHIGAN_URL}]


def collect_schedules(dates: list[date]) -> tuple[list[dict], dict]:
    with source_cache.LOCK:
        return _collect_schedules(dates)


def _collect_schedules(dates: list[date]) -> tuple[list[dict], dict]:
    now = source_cache.utc_now()
    saved = source_cache.load()
    def fetch(publisher):
        previous = source_cache.usable_rows(publisher, saved.get(publisher), SOURCE_URLS[publisher], now)
        pause = source_cache.paused_until(saved.get(publisher), now)
        if pause is not None:
            record = saved[publisher]
            rows = [{**row, "cached": True} for row in previous]
            label = "cached" if rows else "unavailable"
            retry = pause.astimezone(timezone.utc).strftime("%m-%d %H:%M UTC")
            return rows, f"{label} ({record['error']}; retry after {retry})", {**record, "events": previous}
        try:
            text = request_schedule(SOURCE_URLS[publisher])
            if publisher == "DOL":
                events = parse_claims_schedule(text, dates)
            elif publisher == "Fed":
                events = parse_fed_calendar(text)
            elif publisher == "Michigan":
                events = parse_michigan_schedule(text)
                if dates and datetime.fromisoformat(events[0]["at"]).astimezone(NY).date() < min(dates):
                    raise ValueError("Michigan's next-release notice predates the requested window")
            else:
                events = parse_ics(text, publisher)
            if not events:
                # A parsed document with no recognized active releases can
                # represent cancellations. Do not revive its superseded rows.
                previous = []
                raise ValueError("No recognized publisher releases")
            record = source_cache.success(events, previous, publisher, now)
            rows = [{**row, "cached": row["fetched_at"] != now.isoformat()} for row in record["events"]]
            return rows, "available", record
        except Exception as exc:
            detail = f"HTTP {exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
            record = source_cache.failure(previous, detail, now, isinstance(exc, HTTPError) and exc.code == 403)
            rows = [{**row, "cached": True} for row in previous]
            label = "cached" if rows else "unavailable"
            retry = source_cache.timestamp(record["retry_after"]).astimezone(timezone.utc).strftime("%m-%d %H:%M UTC")
            return rows, f"{label} ({detail}; retry after {retry})", record
    events, status = [], {}
    updated = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for publisher, (rows, detail, record) in zip(SOURCE_URLS, pool.map(fetch, SOURCE_URLS)):
            events.extend(rows)
            status[publisher] = detail
            updated[publisher] = record
    try:
        source_cache.save(updated)
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Publisher schedule cache save unavailable (%s)", type(exc).__name__)
        status["Schedule cache"] = "save unavailable (" + type(exc).__name__ + ")"
    return events, status


def timing_evidence(row: dict) -> dict:
    if "fetched_at" not in row:
        return {}
    return {"timing_checked_at": row["fetched_at"], "timing_cached": bool(row.get("cached"))}


def verify_time(name: str, source_date: date, schedules: list[dict]) -> dict:
    kind = category(name)
    matching = [row for row in schedules if row["category"] == kind and kind]
    exact = [row for row in matching if datetime.fromisoformat(row["at"]).astimezone(NY).date() == source_date]
    times = {row["at"] for row in exact}
    if len(times) == 1:
        row = min(exact, key=lambda value: bool(value.get("cached")))
        return {"time_status": "cached" if row.get("cached") else "verified", "event_at": row["at"],
                "publisher": row["publisher"], "timing_url": row["url"], **timing_evidence(row)}
    if len(times) > 1:
        return {"time_status": "conflict", "event_at": "", "publisher": "", "timing_url": ""}
    nearby = [row for row in matching if abs((datetime.fromisoformat(row["at"]).astimezone(NY).date() - source_date).days) <= 3]
    evidence = timing_evidence(nearby[0]) if nearby else {}
    return {"time_status": "conflict" if nearby else "unverified", "event_at": "", "publisher": "", "timing_url": "", **evidence}
