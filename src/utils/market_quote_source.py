"""Bounded same-provider benchmark recovery and source-health records."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from src.utils.yahoo_quote import QuoteDataError, parse_regular_quote, finite_number
from src.utils import yahoo_quote as dated


BENCHMARKS = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^RUT": "Russell 2000"}
LOCK = RLock()
ROOT = Path(__file__).resolve().parents[2]


class RecoveryBudget:
    def __init__(self, limit=2):
        self.remaining = limit
        self.lock = RLock()

    def take(self):
        with self.lock:
            if self.remaining <= 0:
                return False
            self.remaining -= 1
            return True


def state_path():
    return Path(os.getenv("MARKET_QUOTE_STATUS_FILE", str(ROOT / "data/market_quote_status.json")))


def load_health():
    try:
        path = state_path()
        if path.stat().st_size > 256_000:
            return {}
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or type(value.get("schema")) is not int or value.get("schema") != 1 or not isinstance(value.get("symbols"), dict):
            return {}
        return {key: row for key, row in value["symbols"].items() if isinstance(key, str) and len(key) <= 32 and isinstance(row, dict)} if len(value["symbols"]) <= 100 else {}
    except (OSError, ValueError, TypeError):
        return {}


def record_health(symbol, now, attempts, quote_value=None, error="", retry_at=None):
    row = {"symbol": symbol, "checked_at": now.isoformat(), "status": "limited" if error else "available",
           "reason": error[:180] if error else "Dated source quote verified", "attempts": attempts}
    if quote_value:
        row.update({key: quote_value[key] for key in ("session_date", "previous_session_date", "asof", "quote_timing", "closing_price_basis")})
        if quote_value.get("return_usable") is False:
            row.update(status="limited", reason=quote_value["return_note"])
    if retry_at is not None:
        row["retry_after_epoch"] = retry_at
    temporary = None
    try:
        with LOCK:
            values = load_health()
            values[symbol] = row
            values = dict(sorted(values.items(), key=lambda item: str(item[1].get("checked_at", "")), reverse=True)[:100])
            path = state_path(); path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".quote-health-", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"schema": 1, "symbols": values}, stream, allow_nan=False)
            os.replace(temporary, path); temporary = None
    except (OSError, ValueError, TypeError, AttributeError):
        pass  # Diagnostics cannot turn a valid quote into a failed quote.
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def cached_health(now=None):
    now = now or dated.datetime.now(timezone.utc)
    with LOCK:
        values = load_health()
    rows = []
    for symbol, row in values.items():
        try:
            stamp = datetime.fromisoformat(row["checked_at"])
            if (row.get("symbol") != symbol or row.get("status") not in {"available", "limited"}
                    or not -60 <= (now-stamp).total_seconds() <= 21600
                    or not isinstance(row.get("reason"), str) or not isinstance(row.get("attempts"), list)
                    or len(row["attempts"]) > 2):
                continue
            rows.append(deepcopy(row))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            continue
    return sorted(rows, key=lambda row: (row["symbol"] not in BENCHMARKS, row["symbol"]))


def read_chart(symbol, reader, now=None, *, budget=None):
    """One normal read, at most one bounded transport recovery for a benchmark."""
    now = now or dated.datetime.now(timezone.utc)
    with LOCK:
        prior = load_health().get(symbol, {})
    retry = finite_number(prior.get("retry_after_epoch"))
    try:
        observed = datetime.fromisoformat(prior.get("checked_at", ""))
        valid_retry = observed.tzinfo is not None and retry is not None and observed.timestamp() <= now.timestamp() < retry <= observed.timestamp()+21600
    except (ValueError, TypeError, OverflowError):
        valid_retry = False
    if valid_retry:
        raise QuoteDataError("Quote source cooldown; retry after " + datetime.fromtimestamp(retry, timezone.utc).strftime("%m-%d %H:%M UTC"))
    attempts = []
    for index, host in enumerate(("query1.finance.yahoo.com", "query2.finance.yahoo.com")):
        if index and (symbol not in BENCHMARKS or budget is not None and not budget.take()):
            break
        url = "https://"+host+"/v8/finance/chart/"+quote(symbol, safe="")+"?range=5d&interval=1d&events=splits"
        try:
            text = reader(url)
            if not isinstance(text, str) or len(text.encode()) > 2_000_000:
                raise QuoteDataError("Chart response exceeds its bounded size or has invalid text")
            payload = json.loads(text)
            chart = payload.get("chart", {})
            rows = chart.get("result")
            if chart.get("error") or not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise QuoteDataError("Original chart result unavailable or ambiguous")
            result = {**rows[0], "request": {"range": "5d", "interval": "1d", "events": "splits"}}
            value = parse_regular_quote(symbol, result, now, profile=2)
            attempts.append({"host": host, "status": "verified"})
            record_health(symbol, now, attempts, value)
            return value, result
        except HTTPError as error:
            reason = "HTTPError " + str(error.code)
            attempts.append({"host": host, "status": reason})
            if error.code in {403, 429}:
                delay = 3600 if error.code == 403 else 900
                try:
                    delay = min(21600, max(delay, int(error.headers.get("Retry-After", delay))))
                except (ValueError, TypeError, AttributeError):
                    pass
                record_health(symbol, now, attempts, error=reason, retry_at=now.timestamp()+delay)
                raise QuoteDataError(reason) from None
            if error.code not in {500, 502, 503, 504}:
                record_health(symbol, now, attempts, error=reason)
                raise QuoteDataError(reason) from None
        except (URLError, TimeoutError, ConnectionError):
            reason = "Quote source timeout or network failure"
            attempts.append({"host": host, "status": reason})
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
            reason = str(error)[:180] if isinstance(error, QuoteDataError) else "Invalid chart response ("+type(error).__name__+")"
            attempts.append({"host": host, "status": reason})
            record_health(symbol, now, attempts, error=reason)
            raise QuoteDataError(reason) from None
        if index == 0 and symbol not in BENCHMARKS:
            break
    record_health(symbol, now, attempts, error=reason)
    raise QuoteDataError(reason)


def source_evidence(result, *, volume=True):
    fields = ("symbol", "regularMarketPrice", "regularMarketTime", "exchangeTimezoneName", "currentTradingPeriod",
              "currency", "exchangeName", "instrumentType", "hasPrePostMarketData", "dataGranularity", "priceHint")
    quotes = result["indicators"]["quote"]
    return {"schema": 2, "request": deepcopy(result["request"]),
            "meta": {key: deepcopy(result["meta"][key]) for key in fields if key in result["meta"]},
            "timestamp": deepcopy(result["timestamp"]), "indicators": {"quote": deepcopy(quotes) if volume else [{"close":deepcopy(quotes[0]["close"])}]},
            "events": deepcopy(result.get("events", {}))}
