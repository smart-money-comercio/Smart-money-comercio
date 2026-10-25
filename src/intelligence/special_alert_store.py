"""Durable per-destination delivery receipts and controls. Never commit this DB."""

from __future__ import annotations

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def connection():
    path = Path(os.getenv("SPECIAL_ALERT_STATE_FILE", str(ROOT / "data/special_alerts.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS deliveries (destination TEXT, event_key TEXT, level INTEGER, sent REAL, PRIMARY KEY (destination, event_key))")
            db.execute("CREATE TABLE IF NOT EXISTS leases (destination TEXT, event_key TEXT, until REAL, PRIMARY KEY (destination, event_key))")
            db.execute("CREATE TABLE IF NOT EXISTS events (event_key TEXT PRIMARY KEY, kind TEXT, payload TEXT, observed REAL, expires REAL, active INTEGER)")
            yield db


def get_settings() -> dict:
    with connection() as db:
        return {name: json.loads(value) for name, value in db.execute("SELECT name,value FROM settings")}


def save_settings(**values) -> None:
    with connection() as db:
        db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)",
                       [(name, json.dumps(value)) for name, value in values.items()])


def claim(destination, alert: dict, now: float) -> bool:
    """Lease before sending; commit a receipt only after Telegram accepts a message."""
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM deliveries WHERE sent < ?", (now - 90 * 86400,))
        db.execute("DELETE FROM leases WHERE until < ?", (now,))
        key = (str(destination), alert["key"])
        row = db.execute("SELECT level,sent FROM deliveries WHERE destination=? AND event_key=?", key).fetchone()
        if row and row[1] > now - alert["ttl"] and row[0] >= alert["level"]:
            return False
        if db.execute("SELECT 1 FROM leases WHERE destination=? AND event_key=?", key).fetchone():
            return False
        db.execute("INSERT OR REPLACE INTO leases VALUES (?,?,?)", (*key, now + 120))
        return True


def finish(destination, alert: dict, now: float, success: bool) -> None:
    with connection() as db:
        key = (str(destination), alert["key"])
        if success:
            db.execute("INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?)", (*key, alert["level"], now))
        db.execute("DELETE FROM leases WHERE destination=? AND event_key=?", key)


def record_snapshot(alerts: list[dict], observations: dict, now: float) -> None:
    """Retain evidence and agent assessments even if Telegram delivery fails."""
    with connection() as db:
        if all(symbol in observations for symbol in ("^GSPC", "^IXIC")):
            db.execute("UPDATE events SET active=0 WHERE kind='market'")
        for alert in alerts:
            db.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,1)",
                       (alert["key"], alert["kind"], json.dumps(alert), now, alert["expires"]))
        db.execute("DELETE FROM events WHERE observed < ?", (now - 30 * 86400,))


def recent_events(now: float, symbol: str = "", active_only: bool = True, limit: int = 5) -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT payload,active,expires FROM events WHERE observed >= ? ORDER BY observed DESC LIMIT 100",
                          (now - 86400,)).fetchall()
    result = []
    for payload, active, expires in rows:
        event = json.loads(payload)
        event["currently_active"] = bool(active and expires >= now)
        if active_only and not event["currently_active"]:
            continue
        if symbol and event["kind"] != "market" and symbol not in event.get("symbols", []):
            continue
        result.append(event)
        if len(result) >= limit:
            break
    return result


def read_current_events(now: float, limit: int = 100) -> list[dict]:
    """Read existing evidence without creating a DB, tables, leases or receipts."""
    path = Path(os.getenv("SPECIAL_ALERT_STATE_FILE", str(ROOT / "data/special_alerts.sqlite3")))
    if not path.is_file():
        raise FileNotFoundError("Special alert evidence cache is unavailable")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        rows = db.execute("SELECT payload,observed,expires FROM events WHERE active=1 AND expires>=? AND observed BETWEEN ? AND ? ORDER BY observed DESC LIMIT ?",
                          (now, now - 86400, now + 60, min(max(int(limit), 1), 100))).fetchall()
    result = []
    for payload, observed, expires in rows:
        try:
            event = json.loads(payload)
            if not isinstance(event, dict):
                continue
            event.update(expires=expires, observed=observed, currently_active=True)
            result.append(event)
        except (ValueError, TypeError):
            continue
    return result
