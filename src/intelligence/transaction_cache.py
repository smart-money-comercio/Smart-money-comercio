"""Coordinate disclosure refresh attempts and publish complete cache snapshots."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile


MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 12000
UNCONDITIONAL = object()
REFRESH_KEYS = {"": 1, "House": 2, "Senate": 3}


def revision(stat):
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size


def read(path):
    try:
        with path.open("rb") as stream:
            stamp = revision(os.fstat(stream.fileno()))
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}, None
    try:
        payload = json.loads(raw, parse_constant=lambda _: None) if len(raw) <= MAX_BYTES else None
    except (ValueError, RecursionError):
        payload = None
    return (payload if isinstance(payload, dict) else {}), stamp


def rows(payload):
    values = payload.get("trades")
    if not isinstance(values, list) or len(values) > MAX_ROWS:
        return []
    return [value for value in values if isinstance(value, dict)]


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(status_path(path), timeout=1)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        yield db


def status_path(path):
    return path.with_suffix(".refresh.sqlite3")


def refresh_row(db, scope):
    query = "SELECT attempt, due, cursor, status, detail FROM refresh WHERE id = ?"
    row = db.execute(query, (REFRESH_KEYS[scope],)).fetchone()
    if row is None and scope:
        # Honor a provider retry already recorded by the previous shared scheduler.
        legacy = db.execute(query, (REFRESH_KEYS[""],)).fetchone()
        if legacy and legacy[1] - legacy[0] > 900:
            reason = next((part.strip().removeprefix(scope + " ") for part in legacy[4].split(";")
                           if part.strip().startswith(scope + " HTTP ")), "")
            if reason:
                return (*legacy[:4], reason)
    return row


def publish(path, payload, expected=UNCONDITIONAL):
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > MAX_BYTES:
        raise ValueError("Disclosure cache exceeds its size limit")
    with locked(path):
        try:
            existing = path.stat()
        except FileNotFoundError:
            existing = None
        current = revision(existing) if existing else None
        if expected is not UNCONDITIONAL and current != expected:
            return False
        descriptor, name = tempfile.mkstemp(prefix=".disclosures-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(stat.S_IMODE(existing.st_mode) if existing else 0o644)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def reserve(path, now, force=False, *, scope=""):
    with locked(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS refresh (id INTEGER PRIMARY KEY, attempt REAL, due REAL, cursor INTEGER, status TEXT, detail TEXT)")
        key = REFRESH_KEYS[scope]
        row = refresh_row(db, scope)
        if row and now < row[1] and (not force or row[4] == "Refresh in progress" or (row[3] == "limited" and row[1] - row[0] > 900)):
            return None, row[3], row[4]
        cursor = row[2] if row else 0
        db.execute("INSERT OR REPLACE INTO refresh VALUES (?, ?, ?, ?, ?, ?)",
                   (key, now, now + 900, cursor, "limited", "Refresh in progress"))
    return cursor, "", ""


def finish(path, started, due, cursor, status, detail, *, scope=""):
    with locked(path) as db:
        db.execute("UPDATE refresh SET due = ?, cursor = ?, status = ?, detail = ? WHERE id = ? AND attempt = ?",
                   (due, cursor, status, detail, REFRESH_KEYS[scope], started))


def refresh_note(path, scope, now):
    """Read the most recent chamber attempt without creating a database."""
    status_file = status_path(path)
    try:
        with closing(sqlite3.connect(status_file.resolve().as_uri() + "?mode=ro", uri=True, timeout=.2)) as db:
            row = refresh_row(db, scope)
    except (sqlite3.Error, OSError):
        return ""
    if not row or row[0] > now.timestamp() or row[3] != "limited":
        return ""
    detail = row[4]
    if row[1] <= now.timestamp() and detail == "Refresh in progress":
        return ""
    if row[1] > now.timestamp() and detail != "Refresh in progress":
        retry = datetime.fromtimestamp(row[1], timezone.utc).strftime("%b %d %H:%M UTC")
        detail += f"; next check after {retry}"
    return detail
