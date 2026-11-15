"""Separate bounded Weekend Outlook editions; daily records are never modified."""

from contextlib import closing
from datetime import datetime, timedelta
import json
import os
import re
from pathlib import Path
import sqlite3

from src.intelligence.weekend_inputs import digest

ROOT=Path(__file__).resolve().parents[2]
MAX_BYTES=500_000


def state_path():
    return Path(os.getenv("WEEKEND_STATE_FILE",str(ROOT/'data/weekend_outlook.sqlite3')))


def identity(record):
    return digest({key:value for key,value in record.items() if key!="id"})[:20]


def save(record):
    if record.get("id")!=identity(record):raise ValueError("Weekend edition identity changed")
    text=json.dumps(record,sort_keys=True,ensure_ascii=False,allow_nan=False)
    if len(text.encode())>MAX_BYTES:raise ValueError("Weekend edition exceeds its storage bound")
    path=state_path();path.parent.mkdir(parents=True,exist_ok=True)
    at=datetime.fromisoformat(record["generated_at"])
    with closing(sqlite3.connect(path,timeout=3)) as db,db:
        db.execute("CREATE TABLE IF NOT EXISTS weekend_editions (id TEXT PRIMARY KEY, generated REAL NOT NULL, record TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO weekend_editions VALUES (?,?,?)",(record["id"],at.timestamp(),text))
        db.execute("DELETE FROM weekend_editions WHERE generated < ?",((at-timedelta(days=90)).timestamp(),))
        db.execute("DELETE FROM weekend_editions WHERE id NOT IN (SELECT id FROM weekend_editions ORDER BY generated DESC,rowid DESC LIMIT 40)")
    return record["id"]


def read_record(edition_id=None):
    records = _read_records(edition_id)
    return records[0] if records else None


def recent():
    return _read_records(limit=40)


def _read_records(edition_id=None, *, limit=1):
    if edition_id is not None and (not isinstance(edition_id,str) or not re.fullmatch(r"[0-9a-f]{20}",edition_id)):
        return []
    path=state_path()
    if not path.is_file():return []
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            rows = (db.execute("SELECT id,record FROM weekend_editions WHERE id=?", (edition_id,)).fetchall()
                    if edition_id is not None else
                    db.execute("SELECT id,record FROM weekend_editions ORDER BY generated DESC,rowid DESC LIMIT ?", (limit,)).fetchall())
    except (OSError, sqlite3.Error):
        return []
    records = []
    for saved_id, raw in rows:
        if not isinstance(raw, str) or len(raw.encode()) > MAX_BYTES:
            continue
        try:
            record = json.loads(raw)
            if isinstance(record, dict) and record.get("id") == saved_id == identity(record):
                records.append(record)
        except (ValueError, TypeError):
            continue
    return records


def latest():
    return read_record()
