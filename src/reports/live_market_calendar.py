from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
import logging
from html import unescape
import threading
import time


REPORT_TIMEZONE = os.getenv(
    "REPORT_TIMEZONE",
    "America/New_York",
)

REQUEST_TIMEOUT = float(
    os.getenv(
        "CALENDAR_REQUEST_TIMEOUT",
        "30",
    )
)

NASDAQ_EARNINGS_URL = (
    "https://api.nasdaq.com/api/calendar/earnings"
)

NASDAQ_ECONOMIC_URL = (
    "https://api.nasdaq.com/api/calendar/economicevents"
)

NASDAQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nasdaq.com/",
    "Origin": "https://www.nasdaq.com",
}

HIGH_IMPACT_TERMS = (
    "cpi",
    "consumer price",
    "pce",
    "personal consumption",
    "ppi",
    "producer price",
    "payroll",
    "employment",
    "unemployment",
    "jobless",
    "claims",
    "fed",
    "fomc",
    "interest rate",
    "gdp",
    "retail sales",
    "consumer sentiment",
    "consumer confidence",
    "durable goods",
    "industrial production",
    "manufacturing",
    "services pmi",
    "manufacturing pmi",
    "ism",
    "housing starts",
    "building permits",
    "home sales",
)


def _clean(value: Any) -> str:
    # Numeric zero is a real observation, not a missing value.
    text = "" if value is None else str(value)
    return " ".join(unescape(text).replace("\xa0", " ").split()).strip()


def _missing(value: Any) -> bool:
    text = _clean(value).lower()

    return text in {
        "",
        "--",
        "-",
        "n/a",
        "na",
        "none",
        "null",
    }


def _first(
    row: dict,
    *keys: str,
) -> str:
    for key in keys:
        value = row.get(key)

        if not _missing(value):
            return _clean(value)

    return ""


def _request_json(base_url: str, event_date: date) -> dict:
    requested_date = event_date
    if base_url == NASDAQ_ECONOMIC_URL:
        requested_date += timedelta(days=_calendar_economic_date_offset())
    # Nasdaq's asOf is feed metadata, not the date of these event rows.
    return _calendar_request_payload(base_url, requested_date)

_CALENDAR_ECONOMIC_OFFSET_CACHE = None
_CALENDAR_ECONOMIC_OFFSET_LOCK = threading.Lock()


def _calendar_request_payload(base_url: str, requested_date: date) -> dict:
    query = urllib.parse.urlencode({"date": requested_date.isoformat()})
    request = urllib.request.Request(f"{base_url}?{query}", headers=NASDAQ_HEADERS)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    _extract_rows(payload)
    return payload


def _calendar_claims_anchor() -> date:
    # FRED publishes the next release date for the US Initial Claims series.
    # Use its actual schedule, including holiday changes, rather than a fixed
    # weekday or Nasdaq's unrelated asOf value.
    request = urllib.request.Request(
        "https://fred.stlouisfed.org/series/ICSA",
        headers={"User-Agent": NASDAQ_HEADERS["User-Agent"], "Accept": "text/html"},
    )
    # The reference page can take longer than Nasdaq's small JSON responses.
    with urllib.request.urlopen(request, timeout=max(REQUEST_TIMEOUT, 10.0)) as response:
        page = response.read().decode("utf-8", errors="replace")
    page = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
    text = _clean(re.sub(r"<[^>]+>", " ", page))
    matches = re.findall(
        r"Next Release Date:\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text,
    )
    months = {
        name: index for index, name in enumerate(
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
            start=1,
        )
    }
    dates = {
        date(int(year), months[month[:3].lower()], int(day))
        for month, day, year in matches
        if month[:3].lower() in months
    }
    if len(dates) != 1:
        raise ValueError("FRED did not provide one recognizable Initial Claims release date")
    release_date = dates.pop()
    today = datetime.now(ZoneInfo(REPORT_TIMEZONE)).date()
    if not 0 <= (release_date - today).days <= 14:
        raise ValueError(f"FRED Initial Claims release date is stale or too distant: {release_date}")
    return release_date


def _calendar_has_initial_claims(requested_date: date) -> bool:
    payload = _calendar_request_payload(NASDAQ_ECONOMIC_URL, requested_date)
    return any(
        _is_us_event(row)
        and re.fullmatch(
            r"initial(?: jobless| unemployment)? claims(?: \([^)]*\))?",
            _economic_event_name(row).lower(),
        ) is not None
        for row in _extract_rows(payload)
    )


def _calendar_economic_date_offset() -> int:
    # Nasdaq's economic feed currently requires the next date in the query.
    # Verified against ISM, FRED and the Fed's schedules on 2026-10-05.
    # Date verification is an optional diagnostic, not a report dependency.
    # Set CALENDAR_ECONOMIC_DATE_OFFSET=0 if the provider fixes its dates.
    configured = os.getenv("CALENDAR_ECONOMIC_DATE_OFFSET", "1").strip()
    if configured not in {"0", "1"}:
        raise ValueError("CALENDAR_ECONOMIC_DATE_OFFSET must be 0 or 1")
    return int(configured)


def _extract_rows(payload: dict) -> list[dict]:
    # Only a recognized list of rows establishes availability. An empty list
    # is a valid empty calendar; an error or unknown schema is unavailable.
    if not isinstance(payload, dict):
        raise ValueError("Calendar response is not a JSON object")
    status = payload.get("status")
    if isinstance(status, dict):
        code = status.get("rCode")
        if code is not None and str(code) != "200":
            raise ValueError(f"Calendar API returned status {code}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Calendar response has no usable data object")
    containers = (data, data.get("calendar"))
    for container in containers:
        if not isinstance(container, dict):
            continue
        rows = container.get("rows")
        if isinstance(rows, list):
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("Calendar response contains malformed rows")
            return rows
    raise ValueError("Calendar response has no recognized rows list")


def _business_days(
    count: int,
) -> list[date]:
    now = datetime.now(
        ZoneInfo(REPORT_TIMEZONE)
    )

    cursor = now.date()

    # After the regular session, start with the
    # next business day.
    if now.hour >= 18:
        cursor += timedelta(days=1)

    days = []

    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)

        cursor += timedelta(days=1)

    return days


def _fetch_one(
    event_date: date, kind: str
) -> tuple[date, str, list[dict] | None]:
    try:
        if kind == "economic":
            payload = _request_json(NASDAQ_ECONOMIC_URL, event_date)
        else:
            payload = _request_json(NASDAQ_EARNINGS_URL, event_date)
        return (event_date, kind, _extract_rows(payload))
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Calendar %s unavailable for %s: %s: %s",
            kind, event_date, type(exc).__name__, exc,
        )
        return (event_date, kind, None)


def _fetch_calendar_days(
    dates: list[date],
) -> dict:
    results = {}

    jobs = []

    for event_date in dates:
        jobs.append(
            (event_date, "economic")
        )
        jobs.append(
            (event_date, "earnings")
        )

    with ThreadPoolExecutor(
        max_workers=min(8, len(jobs))
    ) as executor:
        futures = [
            executor.submit(
                _fetch_one,
                event_date,
                kind,
            )
            for event_date, kind in jobs
        ]

        for future in as_completed(futures):
            event_date, kind, rows = (
                future.result()
            )

            results[
                (event_date, kind)
            ] = rows

    return results


def _is_us_event(row: dict) -> bool:
    country = _first(
        row,
        "country",
        "countryName",
    )

    if not country:
        return True

    normalized = (
        country.lower()
        .replace("_", " ")
        .strip()
    )

    return normalized in {
        "us",
        "usa",
        "united states",
        "united states of america",
    }


def _economic_event_name(
    row: dict,
) -> str:
    return _first(
        row,
        "eventName",
        "event",
        "name",
        "indicator",
    )


def _economic_is_high_impact(
    row: dict,
) -> bool:
    name = _economic_event_name(
        row
    ).lower()

    importance = _first(
        row,
        "importance",
        "impact",
    ).lower()

    if importance in {
        "high",
        "3",
        "3.0",
    }:
        return True

    return any(
        term in name
        for term in HIGH_IMPACT_TERMS
    )


def _select_economic(rows: list[dict], limit: int) -> list[dict]:
    selected = []
    for row in rows:
        if not _is_us_event(row):
            continue
        if not _economic_event_name(row):
            continue
        if not _economic_is_high_impact(row):
            continue
        selected.append(row)

    def priority(row: dict) -> int:
        name = _economic_event_name(row).lower()
        headlines = (
            "cpi", "consumer price", "pce", "personal consumption",
            "ppi", "producer price", "nonfarm payroll", "non-farm payroll",
            "non farm payroll", "unemployment rate", "initial jobless claims",
            "continuing jobless claims", "retail sales", "fomc meeting minutes",
            "interest rate decision",
        )
        if any(term in name for term in headlines):
            return 0
        if "ism" in name and "pmi" in name:
            return 0
        if "gdp" in name and "gdpnow" not in name:
            return 0
        if any(term in name for term in ("pmi", "consumer sentiment", "consumer confidence")):
            return 1
        if "ism" in name:
            return 3
        return 2

    # Select headline releases first, then retain the source's display order.
    ranked = sorted(enumerate(selected), key=lambda pair: (priority(pair[1]), pair[0]))[:limit]
    return [row for _, row in sorted(ranked, key=lambda pair: pair[0])]


def _market_cap_value(
    value: Any,
) -> float:
    text = (
        _clean(value)
        .upper()
        .replace("$", "")
        .replace(",", "")
    )

    if not text:
        return 0.0

    match = re.search(
        r"([-+]?\d*\.?\d+)\s*([TBMK]?)",
        text,
    )

    if not match:
        return 0.0

    try:
        number = float(
            match.group(1)
        )
    except ValueError:
        return 0.0

    multiplier = {
        "T": 1_000_000_000_000,
        "B": 1_000_000_000,
        "M": 1_000_000,
        "K": 1_000,
        "": 1,
    }.get(
        match.group(2),
        1,
    )

    return number * multiplier


def _select_earnings(
    rows: list[dict],
    watchlist_symbols: list[str],
    limit: int,
) -> list[dict]:
    watchlist = {
        str(symbol).upper()
        for symbol in (
            watchlist_symbols or []
        )
    }

    clean_rows = []

    for row in rows:
        symbol = _first(
            row,
            "symbol",
            "ticker",
        ).upper()

        if not symbol:
            continue

        clean_rows.append(row)

    clean_rows.sort(
        key=lambda row: (
            1
            if _first(
                row,
                "symbol",
                "ticker",
            ).upper()
            in watchlist
            else 0,
            _market_cap_value(
                row.get("marketCap")
                or row.get("market_cap")
            ),
        ),
        reverse=True,
    )

    return clean_rows[:limit]


def _format_economic(row: dict) -> str:
    name = _economic_event_name(row)
    # The feed calls the field 'gmt', but its header only says 'Time'.
    # Calendar output identifies the timezone as unverified.
    event_time = _first(row, "gmt", "time")
    consensus = _first(row, "consensus", "forecast", "estimate")
    previous = _first(row, "previous", "prior")
    actual = _first(row, "actual")
    prefix = f"{event_time} - " if event_time else ""
    if actual:
        details = [f"actual {actual}"]
        if consensus:
            details.append(f"expected {consensus}")
        if previous:
            details.append(f"previous {previous}")
        return f"- {prefix}{name} - {' | '.join(details)}"
    if consensus and previous:
        return f"- {prefix}{name} - {consensus} expected vs {previous} previous"
    if consensus:
        return f"- {prefix}{name} - {consensus} expected"
    if previous:
        return f"- {prefix}{name} - {previous} previous"
    return f"- {prefix}{name}"


def _format_earnings(row: dict) -> str:
    symbol = _first(row, "symbol", "ticker").upper()
    company = _first(row, "name", "companyName")
    event_time = _first(row, "time", "reportTime")
    event_time = {
        "time-pre-market": "Before market open",
        "time-after-hours": "After market close",
        "time-not-supplied": "Time not supplied",
    }.get(event_time.lower(), event_time)
    eps = _first(row, "epsForecast", "epsEstimate", "consensusEPS")
    line = f"- {symbol}"
    if company:
        line += f" - {company}"
    if event_time:
        line += f" | {event_time}"
    if eps:
        line += f" | EPS est {eps}"
    return line


def _build_market_impact(
    economic_rows: list[dict],
    earnings_rows: list[dict],
) -> str:
    names = " ".join(
        _economic_event_name(row).lower()
        for row in economic_rows
    )

    notes = []

    if any(
        term in names
        for term in (
            "cpi",
            "pce",
            "ppi",
            "inflation",
        )
    ):
        notes.append(
            "- Inflation data can move Treasury "
            "yields and rate-sensitive growth/AI."
        )

    if any(
        term in names
        for term in (
            "payroll",
            "employment",
            "unemployment",
            "jobless",
            "claims",
        )
    ):
        notes.append(
            "- Labor data can reshape Fed "
            "expectations and index breadth."
        )

    if any(
        term in names
        for term in (
            "retail",
            "gdp",
            "sentiment",
            "confidence",
            "housing",
            "home sales",
            "pmi",
            "ism",
        )
    ):
        notes.append(
            "- Growth and consumer releases can "
            "move cyclicals, small caps, and rates."
        )

    if earnings_rows:
        notes.append(
            "- Earnings focus: guidance, margins, "
            "backlog, and AI/enterprise demand."
        )

    notes.append(
        "- Avoid oversized new positions "
        "immediately before major catalysts."
    )

    return "\n".join(
        notes[:4]
    )


def _build_calendar(
    day_count: int,
    watchlist_symbols: list[str] | None,
    economic_limit: int,
    earnings_limit: int,
    compact: bool,
) -> str:
    dates = _business_days(day_count)
    today = datetime.now(ZoneInfo(REPORT_TIMEZONE)).date()
    payload = _fetch_calendar_days(dates)
    sections = []
    all_economic = []
    all_earnings = []
    for event_date in dates:
        economic_source = payload.get((event_date, "economic"))
        earnings_source = payload.get((event_date, "earnings"))
        economic_available = economic_source is not None
        earnings_available = earnings_source is not None
        economic_rows = _select_economic(economic_source or [], economic_limit)
        earnings_rows = _select_earnings(
            earnings_source or [], watchlist_symbols or [], earnings_limit,
        )
        if (
            compact and economic_available and earnings_available
            and not economic_rows and not earnings_rows
        ):
            continue
        all_economic.extend(economic_rows)
        all_earnings.extend(earnings_rows)
        lines = [event_date.strftime("%A, %b %d")]
        lines.append("Economic:")
        if not economic_available:
            lines.append("- Live economic calendar unavailable.")
        elif economic_rows:
            display_rows = (
                [dict(row, actual="") for row in economic_rows]
                if event_date > today else economic_rows
            )
            lines.extend(_format_economic(row) for row in display_rows)
        else:
            lines.append("- No matching major US macro events found.")
        lines.append("Earnings:")
        if not earnings_available:
            lines.append("- Live earnings calendar unavailable.")
        elif earnings_rows:
            lines.extend(_format_earnings(row) for row in earnings_rows)
        else:
            lines.append("- No earnings entries returned.")
        sections.append("\n".join(lines))
    if not sections:
        return (
            "Earnings & Economic Calendar\n"
            "No major US macro events or earnings found for this period.\n"
            "Full calendar: /weeklycalendar"
        )
    result = "Earnings & Economic Calendar\n"
    if any(_first(row, "gmt", "time") for row in all_economic):
        result += "Economic release times: timezone unverified.\n"
    result += "\n" + "\n\n".join(sections)
    if all_economic or all_earnings:
        result += "\n\nMarket Impact\n" + _build_market_impact(all_economic, all_earnings)
    if compact:
        result += "\n\nFull calendar: /weeklycalendar"
    return result.strip()


def build_compact_market_calendar(
    watchlist_symbols: list[str] | None = None,
) -> str:
    # Keep /report concise: next two business days.
    return _build_calendar(
        day_count=2,
        watchlist_symbols=watchlist_symbols,
        economic_limit=3,
        earnings_limit=4,
        compact=True,
    )


def build_full_market_calendar() -> str:
    return _build_calendar(
        day_count=5,
        watchlist_symbols=None,
        economic_limit=8,
        earnings_limit=10,
        compact=False,
    )
