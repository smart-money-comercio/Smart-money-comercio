"""Original publisher checks and bounded outage backoff, separate from report age."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading


ROOT = Path(__file__).resolve().parents[2]
MAX_AGE_SECONDS = 24 * 60 * 60
MAX_BYTES = 1_000_000
LOCK = threading.RLock()
CATEGORIES = {"BLS": {"cpi", "ppi", "jobs", "jolts", "eci", "productivity", "trade_prices"},
              "BEA": {"gdp", "pce", "trade"}, "DOL": {"claims"},
              "Fed": {"fomc_decision", "fomc_press", "fomc_minutes"}, "Michigan": {"michigan_sentiment"}}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing publisher check time")
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("Publisher check has no timezone")
    return at


def state_path() -> Path:
    report = Path(os.getenv("CALENDAR_STATE_FILE", str(ROOT / "data/calendar_snapshot.json")))
    return Path(os.getenv("CALENDAR_SOURCE_CACHE_FILE", str(report.with_name("calendar_source_cache.json"))))


def load() -> dict:
    try:
        path = state_path()
        if path.stat().st_size > MAX_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1:
            return {}
        return value["sources"] if isinstance(value.get("sources"), dict) else {}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {}


def save(sources: dict) -> None:
    raw = json.dumps({"schema": 1, "sources": sources}, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("Publisher cache is too large")
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".calendar-source-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def usable_rows(publisher: str, record, source_url: str, now: datetime) -> list[dict]:
    if not isinstance(record, dict) or not isinstance(record.get("events"), list) or len(record["events"]) > 1000:
        return []
    result = []
    for row in record["events"]:
        try:
            if (not isinstance(row, dict) or row["publisher"] != publisher or row["url"] != source_url
                    or row["category"] not in CATEGORIES.get(publisher, set())
                    or not isinstance(row["name"], str) or not 1 <= len(row["name"]) <= 180):
                continue
            timestamp(row["at"])
            age = (now - timestamp(row["fetched_at"])).total_seconds()
            if not -60 <= age <= MAX_AGE_SECONDS:
                continue
            result.append({key: row[key] for key in ("category", "name", "at", "publisher", "url", "fetched_at")})
        except (KeyError, TypeError, ValueError):
            continue
    return result


def paused_until(record, now: datetime) -> datetime | None:
    try:
        if not isinstance(record, dict) or not isinstance(record.get("error"), str) or len(record["error"]) > 100:
            return None
        attempted = timestamp(record["attempted_at"])
        retry = timestamp(record["retry_after"])
        if (-60 <= (now - attempted).total_seconds() <= 6 * 60 * 60
                and 0 < (retry - now).total_seconds() <= 6 * 60 * 60):
            return retry
    except (KeyError, TypeError, ValueError):
        pass
    return None


def success(rows: list[dict], previous: list[dict], publisher: str, now: datetime) -> dict:
    fresh = [{**row, "fetched_at": now.isoformat()} for row in rows]
    if publisher == "Michigan":
        # The next-release notice rolls forward. Retain only past scheduled
        # dates already checked within 24 hours, without renewing their age.
        fresh_days = {timestamp(row["at"]).date() for row in fresh}
        fresh += [row for row in previous if timestamp(row["at"]) <= now and timestamp(row["at"]).date() not in fresh_days]
    return {"events": fresh, "attempted_at": now.isoformat(), "retry_after": None, "error": ""}


def failure(previous: list[dict], detail: str, now: datetime, forbidden: bool = False) -> dict:
    return {"events": previous, "attempted_at": now.isoformat(), "error": detail,
            "retry_after": (now + timedelta(hours=6) if forbidden else now + timedelta(minutes=15)).isoformat()}
