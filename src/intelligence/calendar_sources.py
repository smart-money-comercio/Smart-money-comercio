"""Publisher release schedules, independent of Nasdaq's unnamed time column."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
import re
import urllib.request
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")
BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
DOL_URL = "https://oui.doleta.gov/unemploy/claims_arch.asp"
SOURCE_URLS = {"BLS": BLS_URL, "BEA": BEA_URL, "DOL": DOL_URL}
MAX_BYTES = 1_000_000


def request_schedule(url: str) -> str:
    if url not in SOURCE_URLS.values():
        raise ValueError("Unknown release-schedule source")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/calendar,text/html,*/*"})
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
        if name.startswith("gross domestic product"):
            return "gdp"
        if name.startswith("personal income and outlays"):
            return "pce"
        if name.startswith("u.s. international trade in goods and services"):
            return "trade"
        return ""
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
    if any(term in name for term in ("pce price", "personal consumption expenditure", "personal income", "personal spending")):
        return "pce"
    if "trade balance" in name:
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


def collect_schedules(dates: list[date]) -> tuple[list[dict], dict]:
    def fetch(publisher):
        try:
            text = request_schedule(SOURCE_URLS[publisher])
            events = parse_claims_schedule(text, dates) if publisher == "DOL" else parse_ics(text, publisher)
            if not events:
                raise ValueError("No recognized publisher releases")
            return events, "available"
        except Exception as exc:
            return [], "unavailable (" + type(exc).__name__ + ")"
    events, status = [], {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for publisher, (rows, detail) in zip(SOURCE_URLS, pool.map(fetch, SOURCE_URLS)):
            events.extend(rows)
            status[publisher] = detail
    return events, status


def verify_time(name: str, source_date: date, schedules: list[dict]) -> dict:
    kind = category(name)
    matching = [row for row in schedules if row["category"] == kind and kind]
    exact = [row for row in matching if datetime.fromisoformat(row["at"]).astimezone(NY).date() == source_date]
    times = {row["at"] for row in exact}
    if len(times) == 1:
        row = exact[0]
        return {"time_status": "verified", "event_at": row["at"], "publisher": row["publisher"], "timing_url": row["url"]}
    if len(times) > 1:
        return {"time_status": "conflict", "event_at": "", "publisher": "", "timing_url": ""}
    nearby = [row for row in matching if abs((datetime.fromisoformat(row["at"]).astimezone(NY).date() - source_date).days) <= 3]
    return {"time_status": "conflict" if nearby else "unverified", "event_at": "", "publisher": "", "timing_url": ""}
