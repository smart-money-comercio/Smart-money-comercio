"""Two index futures, aligned to one pre-open clock and the prior cash close."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from threading import Lock

from src.config.premarket import settings
from src.intelligence import premarket_sources as sources


CONTRACTS = {"NQ=F": "Nasdaq-100", "ES=F": "S&P 500"}
SOURCE_SECTION = "Premarket index futures"
SOURCE_ID = "premarket_index_futures"
_MAX_PROOF_BYTES = 16_000
_RETRY_SECONDS = 120
_lock = Lock()
_last_capture = None


def _pair(anchor, responses, now, max_age):
    identity = tuple(anchor.get(key) for key in ("symbol", "instrumentType", "currency", "dataGranularity"))
    if identity != ("SPY", "ETF", "USD", "5m"):
        raise ValueError("SPY cash-session anchor identity could not be verified")
    bounds = sources.session(anchor, now)
    prior_close = datetime.fromisoformat(bounds["previous_close"]).astimezone(sources.NY)
    if prior_close.month in {3, 6, 9, 12} and 8 <= prior_close.day <= 22:
        raise ValueError("Prior cash close falls within the continuous futures roll window")
    rows = [sources.packet(symbol, responses[symbol], now, {"max_age": max_age}, bounds, early_futures=True)
            for symbol in CONTRACTS]
    if rows[0]["asof"] != rows[1]["asof"]:
        raise ValueError("Index futures lack a matching completed five-minute bar")
    return rows


def _size_check(value):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > _MAX_PROOF_BYTES:
        raise ValueError("Premarket futures evidence exceeds its storage limit")


def checked(value, now, cash_session=None):
    """Recalculate saved returns and enforce their age at the report clock."""
    try:
        if (type(value["schema"]) is not int or value["schema"] != 1
                or type(value["max_age"]) is not int or not 300 <= value["max_age"] <= 900
                or not sources.futures_window(now)):
            raise ValueError("Invalid premarket futures evidence or report clock")
        _size_check(value)
        cutoff = datetime.fromisoformat(value["checked_at"])
        if not sources.futures_window(cutoff) or cutoff > now:
            raise ValueError("Premarket futures check time is outside this report's morning")
        inputs = {row["symbol"]: row["evidence"] for row in value["quotes"]}
        rows = _pair(value["anchor"], inputs, cutoff, value["max_age"])
        if rows != value["quotes"] or rows[0]["session"]["day"] != now.astimezone(sources.NY).date().isoformat():
            raise ValueError("Premarket futures evidence changed or belongs to another session")
        if (now - datetime.fromisoformat(rows[0]["asof"])).total_seconds() > value["max_age"]:
            raise ValueError("Premarket futures bars are stale for this report")
        if cash_session and prior_day(value) != cash_session:
            raise ValueError("Futures and cash quotes use different prior sessions")
    except (AttributeError, KeyError, OverflowError, TypeError) as error:
        raise ValueError("Malformed premarket futures evidence") from error
    return value


def _read(now, max_age):
    symbols = ("SPY", *CONTRACTS)
    with ThreadPoolExecutor(max_workers=len(symbols)) as pool:
        requests = {symbol: pool.submit(sources.fetch, symbol) for symbol in symbols}
        responses = {}
        for symbol, request in requests.items():
            try:
                responses[symbol] = request.result()
            except Exception as error:
                return None, f"{symbol} quote source unavailable ({type(error).__name__})"
    try:
        meta = responses["SPY"]["meta"]
        anchor = {key: meta[key] for key in ("symbol", "instrumentType", "currency", "dataGranularity",
                                             "currentTradingPeriod", "tradingPeriods")}
        rows = _pair(anchor, responses, now, max_age)
        value = {"schema": 1, "max_age": max_age, "checked_at": now.astimezone(timezone.utc).isoformat(),
                 "anchor": anchor, "quotes": rows}
        _size_check(value)
    except ValueError as error:
        return None, str(error)
    except (AttributeError, KeyError, OverflowError, TypeError):
        return None, "Malformed futures quote or cash-session schedule"
    return value, ""


def capture(now):
    """Check the three charts once per two minutes, including limited reads."""
    global _last_capture
    if not sources.futures_window(now):
        return None, "Outside the premarket futures window"
    config = settings()
    if not config["enabled"]:
        return None, "Premarket quotes disabled"
    with _lock:
        if _last_capture and 0 <= (now - _last_capture[0]).total_seconds() < _RETRY_SECONDS:
            if config["max_age"] == _last_capture[1]:
                return _last_capture[2]
        result = _read(now, config["max_age"])
        _last_capture = (now, config["max_age"], result)
        return result


def clock(value):
    at = datetime.fromisoformat(value["quotes"][0]["asof"]).astimezone(sources.NY)
    return at.strftime("%I:%M %p %Z").lstrip("0")


def prior_day(value):
    return datetime.fromisoformat(value["quotes"][0]["baseline_at"]).astimezone(sources.NY).date().isoformat()


def opening(value):
    moves = []
    for row in value["quotes"]:
        change = round(row["change"], 2)
        direction = f"{'down' if change < 0 else 'up'} {abs(change):.2f} percent" if change else "unchanged"
        moves.append(f"{CONTRACTS[row['symbol']]} futures were {direction}")
    return f"At {clock(value)}, {' and '.join(moves)} from their levels at the prior U.S. cash close."


def open_check(value):
    changes = [round(row["change"], 2) for row in value["quotes"]]
    if all(change < 0 for change in changes):
        question = "Check how many of the stocks and funds we track open lower. Widespread losses would show that selling extends beyond the futures market."
    elif all(change > 0 for change in changes):
        question = "Check how many of the stocks and funds we track open higher. Broad gains would show that the strength extends beyond the futures market."
    else:
        question = "Compare advances and declines across the stocks and funds we track. That will show whether a clear direction emerges when cash trading begins."
    return {"id": "watch_premarket_open", "section": "watch", "text": "At the open — " + question,
            "sources": [SOURCE_SECTION]}


def source_line(value):
    return "Premarket futures source (Yahoo Finance, may be delayed) — " + " · ".join(row["url"] for row in value["quotes"])
