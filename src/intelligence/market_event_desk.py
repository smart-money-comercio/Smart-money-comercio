"""Bounded repeat quote checks and frozen editorial attention; never infer causes."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock

from src.utils.yahoo_quote import finite_number, parse_regular_quote
from src.intelligence.special_alert_sources import timestamp

ROOT = Path(__file__).resolve().parents[2]
LOCK = RLock()
THRESHOLD = 5.0
LIMIT = 3
RECHECK_SECONDS = 900


def state_path():
    return Path(os.getenv("MARKET_EVENT_STATE_FILE", str(ROOT / "data/market_event_checks.json")))


def packet(row, symbol, now):
    if not isinstance(row, dict) or row.get("ok") is not True or not isinstance(row.get("quote_evidence"), dict):
        raise ValueError("Original chart evidence unavailable")
    quote = parse_regular_quote(symbol, row["quote_evidence"], now)
    if (quote["instrument_type"] != "EQUITY" or any(row.get(key) != quote[key] for key in
        ("symbol", "asof", "session_date", "previous_session_date")) or any(
        finite_number(row.get(key)) is None or abs(row[key]-quote[key]) > .011
        for key in ("price", "previous_close", "change_percent")
    )):
        raise ValueError("Displayed equity quote does not match its source")
    return quote


def verdict(row, now):
    first = packet(row["first"], row["symbol"], now)
    action = row["first"]["quote_evidence"].get("events", {}).get("splits", {})
    if action:
        return "corporate action check"
    try:
        second = packet(row["second"], row["symbol"], now)
    except (ValueError, KeyError, TypeError):
        return "quote check pending"
    same = (first["session_date"] == second["session_date"] and first["previous_session_date"] == second["previous_session_date"]
            and abs(first["previous_close"]-second["previous_close"]) <= max(.000001, first["previous_close"]*.000001)
            and abs(first["change_percent"]-second["change_percent"]) <= 2
            and first["change_percent"]*second["change_percent"] > 0
            and abs(second["change_percent"]) >= THRESHOLD)
    return "rechecked" if same else "quote changed; check pending"


def checked_row(row, now):
    from src.intelligence.company_focus import COMPANY_NAMES, issuer
    if not isinstance(row, dict) or row.get("symbol") not in COMPANY_NAMES:
        raise ValueError("Event issuer unavailable")
    observed = timestamp(row.get("checked_at"))
    if observed is None or not -60 <= (now-observed).total_seconds() <= 3600:
        raise ValueError("Event observation unavailable or stale")
    first = packet(row["first"], row["symbol"], observed)
    if abs(first["change_percent"]) < THRESHOLD or row.get("status") != verdict(row, observed) or row.get("issuer") != issuer(row["symbol"]):
        raise ValueError("Event verification does not match its source")
    return row


def read_snapshot(now):
    try:
        path = state_path()
        if path.stat().st_size > 150_000:
            return []
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or type(value.get("schema")) is not int or value["schema"] != 1 or not isinstance(value.get("events"), list) or len(value["events"]) > LIMIT:
            return []
        result = []
        for row in value["events"]:
            try: result.append(deepcopy(checked_row(row, now)))
            except (ValueError, TypeError, KeyError, OverflowError): pass
        return result
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []


def save_snapshot(rows):
    path = state_path(); path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"schema": 1, "events": rows}, allow_nan=False).encode()
    if len(body) > 150_000:
        raise ValueError("Market event evidence exceeds its limit")
    fd, name = tempfile.mkstemp(prefix=".market-events-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream: stream.write(body)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def review_quotes(quotes, fetch, now=None):
    """At most three same-provider reads; recent repeat checks can be reused."""
    from src.intelligence.company_focus import COMPANY_NAMES, issuer
    now = now or datetime.now(timezone.utc)
    candidates = []
    for symbol, row in quotes.items():
        try:
            if symbol not in COMPANY_NAMES: continue
            quote = packet(row, symbol, now)
            if THRESHOLD <= abs(quote["change_percent"]) <= 1000:
                candidates.append((symbol, row, quote))
        except (ValueError, TypeError, KeyError, OverflowError): pass
    candidates.sort(key=lambda value: (-abs(value[2]["change_percent"]), value[0]))
    with LOCK:
        previous = read_snapshot(now); rows, seen = [], set()
        for symbol, first, quote in candidates:
            identity = issuer(symbol)
            if identity in seen: continue
            seen.add(identity)
            prior = next((row for row in previous if row["symbol"] == symbol and
                          -60 <= (now-timestamp(row.get("recheck_at", row["checked_at"]))).total_seconds() <= RECHECK_SECONDS), None)
            value = {"symbol": symbol, "issuer": identity, "first": deepcopy(first),
                     "checked_at": now.isoformat(), "recheck_at": prior.get("recheck_at", prior["checked_at"]) if prior else now.isoformat()}
            try: value["second"] = deepcopy(prior.get("second", {})) if prior else fetch(symbol)
            except Exception: value["second"] = {}
            value["status"] = verdict(value, now)
            rows.append(value)
            if len(rows) == LIMIT: break
        save_snapshot(rows)
    return rows


def report_prices(report):
    from src.reports.report_quality import split_report_sections
    sections = {key: "\n".join(lines[1:]) for key, lines in split_report_sections(report) if key}
    prices = {}
    for symbol, value in re.findall(r"^[•\-] (\w+): \$[\d,.]+ \(([+-]?\d+(?:\.\d+)?)%\)$", sections.get("Watchlist Movers", ""), re.M):
        number = float(value)
        if THRESHOLD <= abs(number) <= 1000: prices[symbol] = number
    return prices, re.search(r"^Quote session: (\d{4}-\d{2}-\d{2})$", sections.get("Market Snapshot", ""), re.M)


def context_for_report(report, now):
    from src.intelligence.company_focus import COMPANY_NAMES, issuer
    prices, session = report_prices(report)
    verified = []
    for row in read_snapshot(now):
        try:
            packet(row["first"], row["symbol"], now)
            verified.append(row)
        except (ValueError, TypeError, KeyError): pass
    events, seen = [], set()
    for symbol, value in sorted(prices.items(), key=lambda item: -abs(item[1])):
        if symbol not in COMPANY_NAMES or issuer(symbol) in seen or session is None: continue
        seen.add(issuer(symbol))
        proof = next((row for row in verified if row["symbol"] == symbol
                      and row["first"]["session_date"] == session[1]
                      and abs(row["first"]["change_percent"]-value) <= .11), None)
        events.append({"symbol": issuer(symbol), "source_symbol": symbol, "reported_move": value,
                       "status": proof["status"] if proof else "quote check pending", "proof": proof})
        if len(events) == LIMIT: break
    return {"schema": 1, "report_sha256": hashlib.sha256(report.encode()).hexdigest(), "events": events}


def checked_context(context, report, now):
    prices, session = report_prices(report)
    if (not isinstance(context, dict) or context.get("schema") != 1 or context.get("report_sha256") != hashlib.sha256(report.encode()).hexdigest()
            or not isinstance(context.get("events"), list) or len(context["events"]) > LIMIT):
        raise ValueError("Market event context does not match the research edition")
    from src.intelligence.company_focus import issuer
    from src.intelligence.company_focus import COMPANY_NAMES
    expected, used = [], set()
    for symbol, value in sorted(prices.items(), key=lambda item: -abs(item[1])):
        if session is not None and symbol in COMPANY_NAMES and issuer(symbol) not in used:
            expected.append((issuer(symbol), symbol, value)); used.add(issuer(symbol))
            if len(expected) == LIMIT: break
    if [(row.get("symbol"), row.get("source_symbol"), row.get("reported_move")) for row in context["events"]] != expected:
        raise ValueError("Market event attention omitted or changed a reported outlier")
    seen = set()
    for event in context["events"]:
        matches = [value for symbol, value in prices.items() if symbol == event.get("source_symbol") and issuer(symbol) == event["symbol"]]
        if event["symbol"] in seen or event.get("reported_move") not in matches or session is None:
            raise ValueError("Market event does not match the reported move")
        seen.add(event["symbol"])
        proof = event.get("proof")
        if proof is not None:
            checked_row(proof, now)
            packet(proof["first"], proof["symbol"], now)
            quote = proof["first"]
            if proof["symbol"] != event["source_symbol"] or proof["issuer"] != event["symbol"] or quote["session_date"] != session[1] or abs(quote["change_percent"]-event["reported_move"]) > .11:
                raise ValueError("Market event quote does not match the edition")
        if event["status"] != (proof["status"] if proof else "quote check pending"):
            raise ValueError("Market event status lost its evidence")
    return context


def search_hints(now):
    rows = read_snapshot(now)
    return [{"symbol": row["issuer"], "session": row["first"]["session_date"], "quote_status": row["status"],
             "quote_asof": row["first"]["asof"], "checked_at": row["checked_at"],
             "research_task": "Verify original earnings, guidance, regulatory disclosures and corporate actions. Price movement does not establish its cause."}
            for row in rows]


def story_priority(story, now, events):
    from src.intelligence.company_focus import issuer
    topic = story.get("materiality", "")
    age = (now-timestamp(story["published"])).total_seconds()
    base = {"IPO": 4, "monetary policy": 4, "economic data": 4, "guidance": 3, "regulation": 3,
            "earnings": 2, "acquisition": 2, "restructuring": 2, "contract": 1, "product": 1}.get(topic, 0)
    movers = {event["symbol"] for event in events if event["status"] == "rechecked"}
    match = bool(movers & {issuer(symbol) for symbol in story.get("symbols", [])})
    profile, checked = story.get("priority_evidence", {}), timestamp(story.get("priority_checked_at"))
    support = (profile.get("scope") in {"publisher feed excerpt", "original release excerpt"} and len(profile.get("source_text", "")) >= 80
               and checked is not None and -60 <= (now-checked).total_seconds() <= 21600
               and (timestamp(story["published"])-checked).total_seconds() <= 60)
    if support and age <= 8*3600 and topic in {"earnings", "guidance", "regulation"}:
        return 7 if match else 6
    return base + (1 if age <= 4*3600 else 0)
