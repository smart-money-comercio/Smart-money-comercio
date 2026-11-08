"""Manual Daily Agent reply receipts, separate from research workflow status."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from uuid import uuid4

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
LOCK = RLock()
MAX_BYTES = 16384
STATES = {"in_progress", "confirmed", "unconfirmed", "failed", "interrupted", "workflow_error"}


def clock():
    return datetime.now(timezone.utc).isoformat()


def state_path():
    return Path(os.getenv("DAILY_AGENT_DELIVERY_STATE_FILE", str(ROOT / "data/daily_agent_delivery.json")))


def error_note(error):
    """Keep exception classes, without URLs, tokens or arbitrary provider text."""
    names = []
    current = error
    for _ in range(4):
        if current is None:break
        name = type(current).__name__
        if name not in names:names.append(name)
        current = current.__cause__ or current.__context__
    for name in re.findall(r"\b(?:ReadError|ConnectError|ReadTimeout|ConnectTimeout|PoolTimeout|WriteError|RemoteProtocolError)\b", str(error)):
        if name not in names:names.append(name)
    return " / ".join(names)[:180]


def read_receipt():
    try:
        path = state_path()
        if path.stat().st_size > MAX_BYTES:return None
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1
                or value.get("state") not in STATES or not isinstance(value.get("started_at"), str)
                or not isinstance(value.get("workflow_last_run"), str) or not isinstance(value.get("run_id"), str)):
            return None
        if value.get("workflow_status") not in {"PASS", "FAIL", "UNKNOWN"}:return None
        for key in ("stage", "error", "updated_at"):
            if not isinstance(value.get(key), str) or len(value[key]) > 180:return None
        for key in ("started_at", "updated_at"):
            if datetime.fromisoformat(value[key]).tzinfo is None:return None
        for key in ("status_total", "status_confirmed", "report_total", "report_confirmed", "part", "total"):
            if type(value.get(key)) is not int or not 0 <= value[key] <= 1000:return None
        if value["status_confirmed"] > value["status_total"] or value["report_confirmed"] > value["report_total"]:return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def save_receipt(value):
    """Diagnostics cannot fail or change a completed research run."""
    temporary = None
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(text.encode()) > MAX_BYTES:raise ValueError("Reply receipt exceeds its bound")
        with LOCK:
            prior = read_receipt()
            if prior and prior["started_at"] > value["started_at"]:return False
            path = state_path();path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="."+path.name+"-", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text+"\n")
            os.replace(temporary, path);temporary = None
        return True
    except (OSError, ValueError, TypeError) as error:
        LOG.warning("Daily agent reply receipt unavailable error=%s", type(error).__name__)
        return False
    finally:
        if temporary:
            try:os.unlink(temporary)
            except OSError:pass


class Receipt:
    def __init__(self):
        self.value = {"schema":1, "run_id":uuid4().hex, "started_at":clock(), "updated_at":clock(),
            "workflow_last_run":"", "workflow_status":"UNKNOWN", "state":"in_progress", "stage":"starting",
            "part":0, "total":0, "status_total":0, "status_confirmed":0, "report_total":0, "report_confirmed":0,
            "error":"", "loading_notice":"pending"}
        self.update()

    def update(self, **changes):
        self.value.update(changes, updated_at=clock())
        save_receipt(self.value)

    def result(self, result, status_total, report_total):
        self.update(workflow_last_run=str(result.get("last_run") or ""), workflow_status="PASS" if result.get("success") else "FAIL",
            status_total=status_total, report_total=report_total)


def status_suffix(status):
    value = read_receipt()
    if value is None:return ""
    if not value["workflow_last_run"]:
        if value["state"] != "workflow_error":return ""
        return ("\n\nLatest manual request did not return a workflow result. The saved run above may be earlier.\n"
                +"Request stage: "+str(value.get("stage", "unknown"))+"\nError: "+str(value.get("error", "unknown")))
    if value["workflow_last_run"] != status.get("last_run"):return ""
    labels = {"confirmed":"CONFIRMED by Telegram API", "unconfirmed":"UNCONFIRMED", "failed":"FAILED",
        "interrupted":"INTERRUPTED", "in_progress":"no final confirmation recorded", "workflow_error":"not completed"}
    return ("\n\nManual Telegram reply: "+labels[value["state"]]+"\n"
        +f"Confirmed status parts: {value['status_confirmed']}/{value['status_total']}; report parts: {value['report_confirmed']}/{value['report_total']}\n"
        +"Last recorded stage: "+str(value.get("stage", "unknown"))
        +(f" ({value['part']}/{value['total']})" if value["part"] else "")
        +("\nError: "+value["error"] if value.get("error") else "")
        +"\nRecorded: "+str(value.get("updated_at", "unknown"))
        +"\nAPI confirmation does not establish that a person read the messages.")
