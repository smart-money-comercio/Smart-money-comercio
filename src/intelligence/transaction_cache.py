"""Coordinate disclosure refresh attempts and publish complete cache snapshots."""

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile


MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 12000
UNCONDITIONAL = object()


def revision(stat):
    return stat.st_ino, stat.st_mtime_ns, stat.st_size


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
    with closing(sqlite3.connect(path.with_suffix(".refresh.sqlite3"), timeout=1)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        yield db


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


def reserve(path, now):
    with locked(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS refresh (id INTEGER PRIMARY KEY, attempt REAL, due REAL, cursor INTEGER, status TEXT, detail TEXT)")
        row = db.execute("SELECT due, cursor, status, detail FROM refresh WHERE id = 1").fetchone()
        if row and now < row[0]:
            return None, row[2], row[3]
        cursor = row[1] if row else 0
        db.execute("INSERT OR REPLACE INTO refresh VALUES (1, ?, ?, ?, ?, ?)",
                   (now, now + 900, cursor, "limited", "Refresh in progress"))
    return cursor, "", ""


def finish(path, started, due, cursor, status, detail):
    with locked(path) as db:
        db.execute("UPDATE refresh SET due = ?, cursor = ?, status = ?, detail = ? WHERE id = 1 AND attempt = ?",
                   (due, cursor, status, detail, started))
