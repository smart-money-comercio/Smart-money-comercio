"""A dated calendar snapshot shared by reports and the existing daily agent."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from src.intelligence import calendar_sources as publishers


ROOT = Path(__file__).resolve().parents[2]
MAX_AGE_SECONDS = 6 * 60 * 60
REFRESH_AGE_SECONDS = 30 * 60
MAX_BYTES = 1_000_000
MAX_ROWS = 2000
LOG = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def state_path() -> Path:
    return Path(os.getenv("CALENDAR_STATE_FILE", str(ROOT / "data/calendar_snapshot.json")))


def report_zone() -> ZoneInfo:
    return ZoneInfo(os.getenv("REPORT_TIMEZONE", "America/New_York"))


def checked_time(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Calendar timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Calendar timestamp has no timezone")
    return parsed


def read_snapshot(now: datetime | None = None) -> dict | None:
    now = now or utc_now()
    try:
        path = state_path()
        if path.stat().st_size > MAX_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(value, dict) or type(value.get("schema")) is not int
                or value["schema"] != 1 or value.get("timezone") != str(report_zone())):
            return None
        if not -60 <= (now - checked_time(value["checked_at"])).total_seconds() <= MAX_AGE_SECONDS:
            return None
        days = value["days"]
        if not isinstance(days, list) or not 1 <= len(days) <= 7:
            return None
        for day in days:
            date.fromisoformat(day["date"])
            if type(day["economic_available"]) is not bool or type(day["earnings_available"]) is not bool:
                return None
        for kind in ("economic", "earnings"):
            rows = value[kind]
            if not isinstance(rows, list) or len(rows) > MAX_ROWS:
                return None
            for row in rows:
                if not isinstance(row, dict) or row["time_status"] not in {"verified", "unverified", "conflict"}:
                    return None
                date.fromisoformat(row["source_date"])
                date.fromisoformat(row["display_date"])
                if row["time_status"] == "verified":
                    at = checked_time(row["event_at"])
                    if at.astimezone(publishers.NY).date().isoformat() != row["source_date"]:
                        return None
                    if publishers.SOURCE_URLS.get(row["publisher"]) != row["timing_url"]:
                        return None
        if not isinstance(value["issues"], list) or not all(isinstance(item, str) for item in value["issues"]):
            return None
        if not isinstance(value["source_status"], dict):
            return None
        return value
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        return None


def save_snapshot(snapshot: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("Calendar snapshot is too large")
    fd, name = tempfile.mkstemp(prefix=".calendar-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def normalize_snapshot(dates: list[date], raw: dict, schedules: list[dict], source_status: dict,
                       now: datetime | None = None) -> dict:
    from src.reports import live_market_calendar as calendar
    now = now or utc_now()
    zone = report_zone()
    snapshot = {"schema": 1, "checked_at": now.isoformat(), "timezone": str(zone), "days": [],
                "economic": [], "earnings": [], "source_status": source_status, "issues": []}
    for day in dates:
        economic, earnings = raw.get((day, "economic")), raw.get((day, "earnings"))
        official_day = [row for row in schedules if checked_time(row["at"]).astimezone(publishers.NY).date() == day]
        snapshot["days"].append({"date": day.isoformat(), "economic_available": economic is not None or bool(official_day),
                                 "earnings_available": earnings is not None})
        for kind, rows in (("economic", economic), ("earnings", earnings)):
            if rows is None:
                snapshot["issues"].append(f"Nasdaq {kind} unavailable for {day.isoformat()}")
        def text(row, *keys):
            return calendar._first(row, *keys)[:180]
        for row in (economic or [])[:1000]:
            if not calendar._first(row, "country", "countryName") or not calendar._is_us_event(row) or not calendar._economic_is_high_impact(row):
                continue
            name = text(row, "eventName", "event", "name", "indicator")
            if not name:
                continue
            timing = publishers.verify_time(name, day, schedules)
            at = checked_time(timing["event_at"]) if timing["event_at"] else None
            actual = text(row, "actual")
            if day > now.astimezone(publishers.NY).date() or (at is not None and at > now):
                actual = ""
            fields = {"eventName": name, "gmt": text(row, "gmt", "time"),
                      "consensus": text(row, "consensus", "forecast", "estimate"),
                      "previous": text(row, "previous", "prior"), "actual": actual,
                      "source_date": day.isoformat(), "display_date": at.astimezone(zone).date().isoformat() if at else day.isoformat(),
                      "data_source": "Nasdaq", **timing}
            if timing["time_status"] == "conflict":
                fields.update(actual="", consensus="", previous="")
            snapshot["economic"].append(fields)
        covered = {publishers.category(row["eventName"]) for row in snapshot["economic"]
                   if row["source_date"] == day.isoformat() and row["time_status"] == "verified"}
        for row in official_day:
            if row["category"] in covered:
                continue
            times = {item["at"] for item in official_day if item["category"] == row["category"]}
            if len(times) != 1:
                continue
            at = checked_time(row["at"])
            snapshot["economic"].append({"eventName": row["name"], "gmt": "", "actual": "", "previous": "", "consensus": "",
                "source_date": day.isoformat(), "display_date": at.astimezone(zone).date().isoformat(),
                "data_source": row["publisher"], "time_status": "verified", "event_at": row["at"],
                "publisher": row["publisher"], "timing_url": row["url"]})
            covered.add(row["category"])
        for row in (earnings or [])[:1000]:
            symbol = text(row, "symbol", "ticker").upper()
            if not symbol or not all(character.isalnum() or character in ".-" for character in symbol) or len(symbol) > 12:
                continue
            snapshot["earnings"].append({"symbol": symbol, "name": text(row, "name", "companyName"),
                "time": text(row, "time", "reportTime"), "epsForecast": text(row, "epsForecast", "epsEstimate", "consensusEPS"),
                "marketCap": text(row, "marketCap", "market_cap"), "source_date": day.isoformat(), "display_date": day.isoformat(),
                "time_status": "unverified", "date_status": "estimated", "data_source": "Nasdaq"})
    # Bound storage without selecting only the current report's watchlist.
    for kind in ("economic", "earnings"):
        snapshot[kind] = snapshot[kind][:MAX_ROWS]
    return snapshot


def get_snapshot(dates: list[date], force_refresh: bool = False) -> dict:
    from src.reports import live_market_calendar as calendar
    if not dates or len(dates) > 7 or not all(type(day) is date for day in dates):
        raise ValueError("Calendar needs one to seven source dates")
    if not force_refresh:
        cached = read_snapshot()
        if (cached and (utc_now() - checked_time(cached["checked_at"])).total_seconds() <= REFRESH_AGE_SECONDS
                and set(day.isoformat() for day in dates).issubset({day["date"] for day in cached["days"]})):
            return cached
    with ThreadPoolExecutor(max_workers=2) as pool:
        feed = pool.submit(calendar._fetch_calendar_days, dates)
        official = pool.submit(publishers.collect_schedules, dates)
        raw = feed.result()
        schedules, status = official.result()
    snapshot = normalize_snapshot(dates, raw, schedules, status)
    try:
        save_snapshot(snapshot)
    except (OSError, ValueError) as exc:
        snapshot["issues"].append("Calendar context save unavailable (" + type(exc).__name__ + ")")
        LOG.warning("Calendar context save unavailable (%s)", type(exc).__name__)
    return snapshot


def review_snapshot(snapshot: dict) -> str:
    verified = len({(row["publisher"], row["event_at"]) for row in snapshot["economic"] if row["time_status"] == "verified"})
    unverified = sum(row["time_status"] == "unverified" for row in snapshot["economic"])
    conflicts = sum(row["time_status"] == "conflict" for row in snapshot["economic"])
    estimated = len(snapshot["earnings"])
    detail = f"{verified} publisher-verified releases; {unverified} rows with unverified times; {conflicts} date conflicts; {estimated} estimated earnings dates."
    if snapshot["issues"]:
        detail += " " + "; ".join(snapshot["issues"][:2])
    return detail


def refresh_calendar_review() -> str:
    from src.reports.live_market_calendar import _business_days
    snapshot = get_snapshot(_business_days(2), force_refresh=True)
    if not any(day["economic_available"] or day["earnings_available"] for day in snapshot["days"]):
        raise RuntimeError("Calendar sources unavailable; no current calendar evidence.")
    return review_snapshot(snapshot)


def calendar_context_provider():
    from src.intelligence.intelligence_context_registry import IntelligenceContextBlock
    snapshot = read_snapshot()
    if snapshot is None:
        return None
    if not any(day["economic_available"] or day["earnings_available"] for day in snapshot["days"]):
        return None
    now = utc_now()
    upcoming = [row for row in snapshot["economic"] if row["time_status"] == "verified" and checked_time(row["event_at"]) >= now]
    signals = []
    for row in sorted(upcoming, key=lambda value: value["event_at"])[:2]:
        at = checked_time(row["event_at"]).astimezone(report_zone())
        signals.append(f"{row['eventName']} {at.strftime('%m-%d %H:%M %Z')} ({row['publisher']})")
    if not signals:
        signals.append("Calendar reviewed; no upcoming publisher-verified release in the cached window.")
    return IntelligenceContextBlock(feature="Calendar Evidence", priority=65, signal="; ".join(signals),
        implication="Earnings dates from Nasdaq are estimates pending company confirmation. " + review_snapshot(snapshot),
        validation="Use /calendar and verify the company's investor-relations announcement before planning around earnings.",
        commands=["/calendar", "/weeklycalendar"],
        metadata={"checked_at": snapshot["checked_at"], "timezone": snapshot["timezone"], "cache_only": True,
                  "score_changes": False, "estimated_earnings": len(snapshot["earnings"]),
                  "timing_sources": publishers.SOURCE_URLS})


def build_catalyst_review(symbol: str) -> str:
    snapshot = read_snapshot()
    if snapshot is None:
        return ""
    today = utc_now().astimezone(publishers.NY).date()
    matches = [row for row in snapshot["earnings"] if row["symbol"] == str(symbol).upper()
               and date.fromisoformat(row["source_date"]) >= today]
    if not matches:
        return ""
    row = min(matches, key=lambda value: value["source_date"])
    timing = {"time-pre-market": "before market open", "time-after-hours": "after market close"}.get(
        row["time"].lower(), "time not supplied")
    return (f"Calendar Catalyst\n{row['source_date']}: earnings {timing} (US market session).\n"
            "Nasdaq date estimate; company confirmation pending. Confirm the investor-relations announcement before planning around it.")
