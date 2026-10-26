"""Bounded edition records; source caches and alert receipts are never written."""

from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[2]
MAX_EDITIONS = 200
MAX_RECORD_BYTES = 500_000


def state_path() -> Path:
    return Path(os.getenv("NEWS_EDITOR_STATE_FILE", str(ROOT / "data/news_editor.sqlite3")))


def save_edition(record: dict, report: str) -> str:
    record = {**record, "report_sha256": hashlib.sha256(report.encode()).hexdigest()}
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(raw.encode()) > MAX_RECORD_BYTES:
        raise ValueError("News editor record exceeds its storage limit")
    edition = hashlib.sha256(raw.encode()).hexdigest()[:20]
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    when = datetime.fromisoformat(record["generated_at"])
    if when.tzinfo is None:
        raise ValueError("Edition time needs a timezone")
    cutoff = (when - timedelta(days=30)).timestamp()
    generated = when.timestamp()
    with closing(sqlite3.connect(path, timeout=3)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS editions (id TEXT PRIMARY KEY, generated REAL NOT NULL, report_sha256 TEXT NOT NULL, record TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO editions VALUES (?,?,?,?)", (edition, generated, record["report_sha256"], raw))
        db.execute("DELETE FROM editions WHERE generated < ?", (cutoff,))
        db.execute("DELETE FROM editions WHERE id NOT IN (SELECT id FROM editions ORDER BY generated DESC, rowid DESC LIMIT ?)", (MAX_EDITIONS,))
    return edition


def read_editions(limit: int = 3, report: str | None = None) -> list[dict]:
    path = state_path()
    if not path.is_file():
        return []
    query = "SELECT id,report_sha256,record FROM editions"
    args = []
    if report is not None:
        query += " WHERE report_sha256=?"
        args.append(hashlib.sha256(report.encode()).hexdigest())
    query += " ORDER BY generated DESC, rowid DESC LIMIT ?"
    args.append(min(max(int(limit), 1), MAX_EDITIONS))
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        rows = db.execute(query, args).fetchall()
    records = []
    for edition, report_digest, raw in rows:
        if not isinstance(raw, str) or len(raw.encode()) > MAX_RECORD_BYTES:
            continue
        try:
            value = json.loads(raw)
            if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
                    or hashlib.sha256(raw.encode()).hexdigest()[:20] != edition
                    or value.get("report_sha256") != report_digest
                    or not isinstance(value.get("generated_at"), str)
                    or not isinstance(value.get("candidates"), list)
                    or len(value["candidates"]) > 180
                    or not isinstance(value.get("stages"), list) or len(value["stages"]) != 6
                    or not isinstance(value.get("issues"), list)
                    or not isinstance(value.get("market_evidence"), dict)
                    or not isinstance(value["market_evidence"].get("moves"), str)):
                continue
            if any(not isinstance(step, dict) or any(not isinstance(step.get(key), str) for key in ("name", "status", "detail")) for step in value["stages"]):
                continue
            health = value.get("source_health", [])
            if (not isinstance(health, list) or len(health) > 48 or any(
                    not isinstance(row, dict) or row.get("status") not in {"available", "limited"}
                    or any(not isinstance(row.get(key), str) or len(row[key]) > 250 for key in ("name", "symbol", "checked_at", "latest_publication", "reason"))
                    or any(type(row.get(key)) is not int or not 0 <= row[key] <= 10000 for key in ("entries", "dated", "fresh", "undated"))
                    for row in health)):
                continue
            analysis = value.get("analyst_review")
            if analysis is not None and (not isinstance(analysis, dict) or analysis.get("schema") != 1
                    or not isinstance(analysis.get("evidence"), dict) or not isinstance(analysis["evidence"].get("source_sections"), list)
                    or any(not isinstance(section, str) for section in analysis["evidence"]["source_sections"])
                    or not isinstance(analysis.get("insights"), list) or len(analysis["insights"]) > 12):
                continue
            if any(not isinstance(story, dict) or story.get("decision") not in {"selected", "skip", "wait"}
                   or any(not isinstance(story.get(key), str) for key in ("title", "url", "source", "published", "reason"))
                   or not isinstance(story.get("symbols"), list) for story in value["candidates"]):
                continue
            value["id"] = edition
            records.append(value)
        except (ValueError, TypeError):
            continue
    return records
