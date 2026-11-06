"""Immutable slot evidence, separate delivery receipts and after-close reviews."""

from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3

from src.intelligence.premarket_risk import checked,LEVELS
from src.intelligence.special_alert_sources import timestamp

ROOT=Path(__file__).resolve().parents[2]


def path():return Path(os.getenv("PREMARKET_STATE_FILE",str(ROOT/"data/premarket.sqlite3")))


@contextmanager
def database(write=False):
    p=path()
    if not write and not p.is_file():
        yield None;return
    if write:p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(p) if write else p.resolve().as_uri()+"?mode=ro",uri=not write,timeout=5)
    try:
        db.execute("PRAGMA busy_timeout=5000")
        if write:
            db.executescript("""CREATE TABLE IF NOT EXISTS snapshots(day TEXT,slot TEXT,id TEXT UNIQUE,body TEXT,PRIMARY KEY(day,slot));
            CREATE TABLE IF NOT EXISTS deliveries(day TEXT,chat TEXT,level INTEGER,snapshot TEXT,status TEXT,at TEXT,PRIMARY KEY(day,chat,level));
            CREATE TABLE IF NOT EXISTS outcomes(day TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);""")
        yield db
        if write:db.commit()
    finally:db.close()


def save(value):
    checked(value)
    if value["slot"] not in {"08:45","09:15"}:raise ValueError("Previews cannot enter the scheduled evidence ledger")
    body=json.dumps(value,ensure_ascii=False,allow_nan=False)
    if len(body.encode())>250000:raise ValueError("Premarket evidence exceeds its storage bound")
    with database(True) as db:
        db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)",(value["day"],value["slot"],value["id"],body))
        oldest=(timestamp(value["observed_at"])-timedelta(days=90)).date().isoformat()
        for table in ("snapshots","deliveries","outcomes"):db.execute(f"DELETE FROM {table} WHERE day<?",(oldest,))
        saved=db.execute("SELECT body FROM snapshots WHERE day=? AND slot=?",(value["day"],value["slot"])).fetchone()
    return checked(json.loads(saved[0]))


def history(limit=10,day=None):
    with database() as db:
        if db is None:return []
        rows=db.execute("SELECT body FROM snapshots "+("WHERE day=? " if day else "")+"ORDER BY day DESC,slot DESC LIMIT ?",(day,min(180,limit)) if day else (min(180,limit),)).fetchall()
    return [checked(json.loads(row[0])) for row in rows]


def enabled():
    with database() as db:
        row=db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone() if db else None
    return row is None or row[0]=="true"


def set_enabled(value):
    with database(True) as db:db.execute("INSERT OR REPLACE INTO settings VALUES('enabled',?)",("true" if value else "false",))


def claim(value,chat,now):
    checked(value);level=LEVELS[value["assessment"]["level"]]
    if level<1 or value["slot"]=="preview" or not timestamp(value["observed_at"])<=now or (now-timestamp(value["observed_at"])).total_seconds()>600:return False
    from src.intelligence.premarket_sources import window,NY
    if not window(now) or now.astimezone(NY).date().isoformat()!=value["day"]:return False
    if any(not 0<=(now-timestamp(row["asof"])).total_seconds()<=value["config"]["max_age"] for row in value["quotes"].values()):return False
    with database(True) as db:
        db.execute("BEGIN IMMEDIATE")
        saved=db.execute("SELECT id FROM snapshots WHERE day=? AND slot=?",(value["day"],value["slot"])).fetchone()
        if not saved or saved[0]!=value["id"]:return False
        if db.execute("SELECT 1 FROM deliveries WHERE day=? AND chat=? AND level>=? AND status IN ('pending','sent')",(value["day"],str(chat),level)).fetchone():return False
        prior=db.execute("SELECT snapshot FROM deliveries WHERE day=? AND chat=? AND level=?",(value["day"],str(chat),level)).fetchone()
        if prior and prior[0]==value["id"]:return False
        db.execute("INSERT OR REPLACE INTO deliveries VALUES(?,?,?,?,?,?)",(value["day"],str(chat),level,value["id"],"pending",now.isoformat()))
    return True


def finish(value,chat,now,sent):
    with database(True) as db:
        db.execute("UPDATE deliveries SET status=?,at=? WHERE day=? AND chat=? AND level=? AND snapshot=? AND status='pending'",
            ("sent" if sent else "failed",now.isoformat(),value["day"],str(chat),LEVELS[value["assessment"]["level"]],value["id"]))


def receipts(day):
    with database() as db:
        rows=db.execute("SELECT level,status,at FROM deliveries WHERE day=? ORDER BY at",(day,)).fetchall() if db else []
    return [{"level":level,"status":status,"at":at} for level,status,at in rows]


def save_outcome(day,value):
    from src.intelligence.premarket_review import checked_outcome
    checked_outcome(value)
    if value["day"]!=day or len(json.dumps(value))>500000:raise ValueError("Outcome day or evidence size invalid")
    with database(True) as db:
        db.execute("INSERT OR IGNORE INTO outcomes VALUES(?,?)",(day,json.dumps(value,allow_nan=False)))
        oldest=(timestamp(value["observed_at"])-timedelta(days=90)).date().isoformat()
        for table in ("snapshots","deliveries","outcomes"):db.execute(f"DELETE FROM {table} WHERE day<?",(oldest,))


def outcomes():
    with database() as db:rows=db.execute("SELECT day,body FROM outcomes ORDER BY day DESC LIMIT 90").fetchall() if db else []
    return {day:json.loads(body) for day,body in rows}
