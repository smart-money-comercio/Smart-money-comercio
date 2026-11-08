"""Separate bounded Weekend Outlook editions; daily records are never modified."""

from contextlib import closing
from datetime import datetime, timedelta
import json
import os
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


def latest():
    path=state_path()
    if not path.is_file():return None
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)) as db:
            row=db.execute("SELECT id,record FROM weekend_editions ORDER BY generated DESC,rowid DESC LIMIT 1").fetchone()
        if row is None or not isinstance(row[1],str) or len(row[1].encode())>MAX_BYTES:return None
        record=json.loads(row[1])
        if not isinstance(record,dict) or record.get("id")!=row[0] or row[0]!=identity(record):return None
        return record
    except (OSError,sqlite3.Error,ValueError,TypeError):return None
