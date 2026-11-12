"""Dated regular-session price returns from Yahoo chart observations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CLOSING_HISTORY_RANGE = "1mo"
CLOSING_HISTORY_BASIS = "dated daily history"
MISSING_CLOSING_BAR = "Completed equity quote needs its dated closing bar"


class QuoteDataError(ValueError):
    """The source cannot establish a usable, dated daily price return."""


def finite_number(value):
    if type(value) not in (int, float):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except OverflowError:
        return None


def source_time(value):
    value = finite_number(value)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def corroborated_index_close(symbol: str, result: dict, price: float, start: datetime,
                             end: datetime, *, profile: int = 1) -> bool:
    """Cash-index closing updates need a matching dated daily bar, not extra time alone."""
    meta = result.get("meta", {})
    precision = meta.get("priceHint")
    if (symbol.upper() not in {"^GSPC", "^IXIC", "^DJI", "^RUT"}
            or meta.get("instrumentType") != "INDEX"
            or meta.get("hasPrePostMarketData") is not False
            or meta.get("dataGranularity") != "1d"
            or type(precision) is not int or not 0 <= precision <= 8):
        return False
    rows = result.get("indicators", {}).get("quote") or []
    if not rows:
        return False
    closes = []
    for epoch, raw_close in zip(result.get("timestamp") or [], rows[0].get("close") or []):
        when, close = source_time(epoch), finite_number(raw_close)
        if when is not None and start <= when <= end:
            closes.append(close)
    # Two independently rounded representations can differ by one displayed tick.
    # Keep the legacy half-tick rule for previously stored source evidence.
    tolerance = (min(10 ** -precision, price * .0001) + 2 * math.ulp(price)
                 if profile == 2 else 0.5 * 10 ** -precision)
    return (len(closes) == 1 and closes[0] is not None and closes[0] > 0
            and abs(price - closes[0]) <= tolerance)


def parse_regular_quote(symbol: str, result: dict, now: datetime | None = None, *, profile: int = 1) -> dict:
    if type(profile) is not int or profile not in {1, 2}:
        raise QuoteDataError("Unknown quote evidence version")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise QuoteDataError("Quote-check clock has no timezone")
    meta = result.get("meta", {})
    if str(meta.get("symbol", "")).upper() != symbol.upper():
        raise QuoteDataError("Quote instrument does not match the requested symbol")
    price = finite_number(meta.get("regularMarketPrice"))
    asof = source_time(meta.get("regularMarketTime"))
    if price is None or price <= 0 or asof is None:
        raise QuoteDataError("Regular-session price or timestamp unavailable")
    age = (now - asof).total_seconds()
    if age < -60 or age > 4 * 86400:
        raise QuoteDataError("Regular-session quote is stale or from the future")
    try:
        exchange_zone = ZoneInfo(meta["exchangeTimezoneName"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise QuoteDataError("Exchange timezone unavailable") from None
    regular = meta.get("currentTradingPeriod", {}).get("regular", {})
    start, end = source_time(regular.get("start")), source_time(regular.get("end"))
    if start is None or end is None or not timedelta(0) < end - start <= timedelta(days=1):
        raise QuoteDataError("Regular-session schedule unavailable")

    quote_day = asof.astimezone(exchange_zone).date()
    regular_day = end.astimezone(exchange_zone).date()
    local_now = now.astimezone(exchange_zone)
    in_check_window = start <= now <= end + timedelta(minutes=20)
    closing_update = False
    if in_check_window:
        if asof < start or asof > end + timedelta(seconds=60) or age > 1200:
            raise QuoteDataError("Current regular-session quote is stale or unavailable")
    elif now > end:
        if asof > end + timedelta(seconds=60):
            closing_update = corroborated_index_close(symbol, result, price, start, end, profile=profile)
        if (quote_day != regular_day or asof < start
                or (asof > end + timedelta(seconds=60) and not closing_update)):
            raise QuoteDataError("Latest completed regular-session quote unavailable")
        # An old schedule must not label a previous weekday's price as current.
        if (local_now.date() > regular_day and local_now.weekday() < 5
                and local_now.time().replace(tzinfo=None) >= start.astimezone(exchange_zone).time().replace(tzinfo=None)):
            raise QuoteDataError("Trading-session metadata is outdated")
    elif asof >= start:
        raise QuoteDataError("Quote is ahead of the upcoming regular session")

    equity = meta.get("instrumentType") in {"EQUITY", "ETF"}
    request = result.get("request")
    closing_history = profile == 2 and equity and isinstance(request, dict) and request.get("range") == CLOSING_HISTORY_RANGE
    previous_session = now < start and quote_day < regular_day
    quote_rows = result.get("indicators", {}).get("quote") or []
    if not quote_rows:
        raise QuoteDataError("Dated closing history unavailable")
    row = quote_rows[0]
    timestamps = result.get("timestamp") or []
    closes = row.get("close") or []
    if closing_history and (len(quote_rows) != 1 or not isinstance(timestamps, list) or not isinstance(closes, list)
                            or not 2 <= len(timestamps) == len(closes) <= 40):
        raise QuoteDataError("Daily history has incomplete or ambiguous closing bars")
    prior_dates, prior_closes = set(), {}
    seen_days, current_closes = set(), []
    latest_observed_day = quote_day
    for epoch, raw_close in zip(timestamps, closes):
        when, close = source_time(epoch), finite_number(raw_close)
        if when is None or when > now + timedelta(seconds=60):
            if closing_history:
                raise QuoteDataError("Daily history has an invalid closing-bar timestamp")
            continue
        day = when.astimezone(exchange_zone).date()
        if profile == 2:
            if day in seen_days:
                raise QuoteDataError("Duplicate daily bars make the return basis ambiguous")
            seen_days.add(day)
            latest_observed_day = max(latest_observed_day, day)
            if day == quote_day and (not closing_history or previous_session or start <= when <= end):
                current_closes.append(close)
        if close is not None and close > 0:
            latest_observed_day = max(latest_observed_day, day)
        if day < quote_day:
            prior_dates.add(day)
            if close is not None and close > 0:
                prior_closes[day] = close
    if latest_observed_day > quote_day:
        raise QuoteDataError("Regular-session quote is older than available dated history")
    if not prior_dates or max(prior_dates) not in prior_closes:
        raise QuoteDataError("Latest prior-session close unavailable")
    previous_day = max(prior_dates)
    if (quote_day - previous_day).days > 4:
        raise QuoteDataError("Prior-session closing history is too old")
    previous_close = prior_closes[previous_day]
    change = price - previous_close
    change_percent = 100 * (price / previous_close - 1)

    volume = None
    for epoch, raw_volume in zip(timestamps, row.get("volume") or []):
        when, number = source_time(epoch), finite_number(raw_volume)
        if when is not None and when <= now + timedelta(seconds=60) and when.astimezone(exchange_zone).date() == quote_day:
            volume = number if number is not None and number >= 0 else None
    timing = "regular_session" if start <= now <= end else "completed_session"
    value = {"symbol": symbol, "ok": True, "price": price,
            "previous_close": previous_close, "change": change, "change_percent": change_percent,
            "volume": volume, "exchange": meta.get("exchangeName") or meta.get("fullExchangeName") or "N/A",
            "currency": meta.get("currency", "USD"),
            "market_state": meta.get("marketState") or ("REGULAR" if timing == "regular_session" else "CLOSED"),
            "instrument_type": meta.get("instrumentType", "N/A"),
            "asof": asof.isoformat(), "session_date": quote_day.isoformat(),
            "previous_session_date": previous_day.isoformat(), "quote_timing": timing,
            "closing_quote_update": closing_update,
            "return_basis": "regular-session price vs dated previous-session close"}
    if profile == 2:
        missing_equity_close = False
        has_closing_bar = len(current_closes) == 1 and current_closes[0] is not None and current_closes[0] > 0
        native_close = end < now and quote_day == regular_day and abs((asof - end).total_seconds()) <= 60
        if closing_history and (not (native_close or previous_session) or not has_closing_bar or meta.get("dataGranularity") != "1d"
                or request.get("interval") != "1d" or request.get("events") != "splits"):
            raise QuoteDataError("Daily history does not establish the dated regular-session close")
        if timing == "completed_session" and equity:
            if not has_closing_bar:
                missing_equity_close = abs(change_percent) >= 5
            elif abs(price-current_closes[0]) > max(.01, price*.0001):
                raise QuoteDataError("Completed equity price conflicts with its dated closing bar")
        action = return_actions(result, value)
        note = ("Split or action evidence needs review for this return interval" if action != "clear" else
                MISSING_CLOSING_BAR if missing_equity_close else
                "Large return needs independent price-basis review" if equity and abs(change_percent) >= 25 else "")
        basis = CLOSING_HISTORY_BASIS if closing_history else "dated daily closing bar matched" if closing_update else "native regular-session quote"
        value.update(quote_schema=2, return_usable=not bool(note), return_note=note,
                     action_check=action, closing_price_basis=basis)
    return value


def return_actions(evidence: dict, quote: dict) -> str:
    """A split outside the two closing dates cannot explain this daily return."""
    from datetime import date
    try:
        events = evidence.get("events", {})
        if not isinstance(events, dict):
            return "unverified action"
        splits = events.get("splits", {})
        if not isinstance(splits, dict) or len(splits) > 20:
            return "unverified action"
        zone = ZoneInfo(evidence["meta"]["exchangeTimezoneName"])
        before, after = date.fromisoformat(quote["previous_session_date"]), date.fromisoformat(quote["session_date"])
        for key, event in splits.items():
            if not isinstance(event, dict):
                return "unverified action"
            when = source_time(event.get("date"))
            key_time = source_time(int(key)) if isinstance(key, str) and key.isdigit() else None
            if "date" in event and when is None:
                return "unverified action"
            if when is None:
                when = key_time
            if when is None or key_time is not None and event.get("date") is not None and when != key_time:
                return "unverified action"
            days = {when.date(), when.astimezone(zone).date()}
            inside = {day for day in days if before < day <= after}
            if not inside:
                continue
            if inside != days:
                return "unverified action"
            # Do not divide a prior close again: Yahoo's Close is split-adjusted.
            return "split in return interval"
        if quote.get("instrument_type") == "EQUITY" and abs(quote["change_percent"]) >= 5 and evidence.get("request", {}).get("events") != "splits":
            return "split query not recorded"
        return "clear"
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, ZoneInfoNotFoundError):
        return "unverified action"


def evidence_quote(symbol: str, evidence: dict, now: datetime | None = None) -> dict:
    version = evidence.get("schema", 1)
    if type(version) is not int or version not in {1, 2}:
        raise QuoteDataError("Unknown cached quote evidence version")
    return parse_regular_quote(symbol, evidence, now, profile=version)


def cached_regular_quote(row: dict, now: datetime | None = None) -> dict:
    """Recheck source evidence; refreshing a cache never refreshes an old quote."""
    if not isinstance(row, dict) or row.get("error"):
        raise QuoteDataError("Cached quote unavailable")
    evidence = row.get("quote_evidence")
    if not isinstance(evidence, dict):
        raise QuoteDataError("Cached quote has no dated source evidence; refresh required")
    quote = evidence_quote(str(row.get("symbol", "")), evidence, now)
    if quote.get("return_usable") is False:
        raise QuoteDataError(quote["return_note"])
    move = finite_number(row.get("move"))
    if move is None or abs(move - round(quote["change_percent"], 2)) > 0.000001:
        raise QuoteDataError("Cached return does not match the dated source evidence")
    return quote
