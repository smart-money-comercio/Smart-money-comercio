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


REPORT_TIMEZONE = os.getenv(
    "REPORT_TIMEZONE",
    "America/New_York",
)

REQUEST_TIMEOUT = float(
    os.getenv(
        "CALENDAR_REQUEST_TIMEOUT",
        "5",
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
    return " ".join(
        str(value or "").replace("\xa0", " ").split()
    ).strip()


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


def _request_json(
    base_url: str,
    event_date: date,
) -> dict:
    query = urllib.parse.urlencode(
        {
            "date": event_date.isoformat(),
        }
    )

    request = urllib.request.Request(
        f"{base_url}?{query}",
        headers=NASDAQ_HEADERS,
    )

    with urllib.request.urlopen(
        request,
        timeout=REQUEST_TIMEOUT,
    ) as response:
        return json.loads(
            response.read().decode(
                "utf-8",
                errors="ignore",
            )
        )


def _extract_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")

    if not isinstance(data, dict):
        return []

    rows = data.get("rows")

    if isinstance(rows, list):
        return [
            row
            for row in rows
            if isinstance(row, dict)
        ]

    calendar = data.get("calendar")

    if isinstance(calendar, dict):
        rows = calendar.get("rows")

        if isinstance(rows, list):
            return [
                row
                for row in rows
                if isinstance(row, dict)
            ]

    return []


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
    event_date: date,
    kind: str,
) -> tuple[date, str, list[dict]]:
    try:
        if kind == "economic":
            payload = _request_json(
                NASDAQ_ECONOMIC_URL,
                event_date,
            )
        else:
            payload = _request_json(
                NASDAQ_EARNINGS_URL,
                event_date,
            )

        return (
            event_date,
            kind,
            _extract_rows(payload),
        )

    except Exception:
        return (
            event_date,
            kind,
            [],
        )


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


def _select_economic(
    rows: list[dict],
    limit: int,
) -> list[dict]:
    selected = []

    for row in rows:
        if not _is_us_event(row):
            continue

        if not _economic_event_name(row):
            continue

        if not _economic_is_high_impact(row):
            continue

        selected.append(row)

    return selected[:limit]


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


def _format_economic(
    row: dict,
) -> str:
    name = _economic_event_name(
        row
    )

    event_time = _first(
        row,
        "time",
    )

    consensus = _first(
        row,
        "consensus",
        "forecast",
        "estimate",
    )

    previous = _first(
        row,
        "previous",
        "prior",
    )

    actual = _first(
        row,
        "actual",
    )

    prefix = (
        f"{event_time} - "
        if event_time
        else ""
    )

    if actual:
        details = []

        if actual:
            details.append(
                f"actual {actual}"
            )

        if consensus:
            details.append(
                f"expected {consensus}"
            )

        if previous:
            details.append(
                f"previous {previous}"
            )

        return (
            f"- {prefix}{name}"
            f" - {' | '.join(details)}"
        )

    if consensus and previous:
        return (
            f"- {prefix}{name}"
            f" - {consensus} expected"
            f" vs {previous} previous"
        )

    if consensus:
        return (
            f"- {prefix}{name}"
            f" - {consensus} expected"
        )

    if previous:
        return (
            f"- {prefix}{name}"
            f" - {previous} previous"
        )

    return f"- {prefix}{name}"


def _format_earnings(
    row: dict,
) -> str:
    symbol = _first(
        row,
        "symbol",
        "ticker",
    ).upper()

    company = _first(
        row,
        "name",
        "companyName",
    )

    event_time = _first(
        row,
        "time",
        "reportTime",
    )

    eps = _first(
        row,
        "epsForecast",
        "epsEstimate",
        "consensusEPS",
    )

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
    dates = _business_days(
        day_count
    )

    payload = _fetch_calendar_days(
        dates
    )

    sections = []
    all_economic = []
    all_earnings = []

    for event_date in dates:
        economic_rows = _select_economic(
            payload.get(
                (
                    event_date,
                    "economic",
                ),
                [],
            ),
            economic_limit,
        )

        earnings_rows = _select_earnings(
            payload.get(
                (
                    event_date,
                    "earnings",
                ),
                [],
            ),
            watchlist_symbols or [],
            earnings_limit,
        )

        if (
            compact
            and not economic_rows
            and not earnings_rows
        ):
            continue

        all_economic.extend(
            economic_rows
        )
        all_earnings.extend(
            earnings_rows
        )

        lines = [
            event_date.strftime(
                "%A, %b %d"
            )
        ]

        if economic_rows:
            lines.append(
                "Economic:"
            )

            lines.extend(
                _format_economic(row)
                for row in economic_rows
            )

        if earnings_rows:
            lines.append(
                "Earnings:"
            )

            lines.extend(
                _format_earnings(row)
                for row in earnings_rows
            )

        if (
            not economic_rows
            and not earnings_rows
        ):
            lines.append(
                "- No major US macro releases "
                "or major earnings found."
            )

        sections.append(
            "\n".join(lines)
        )

    if not sections:
        return (
            "Earnings & Economic Calendar\n"
            "Live calendar data is unavailable "
            "or no major catalysts were found.\n"
            "Full calendar: /weeklycalendar"
        )

    impact = _build_market_impact(
        all_economic,
        all_earnings,
    )

    footer = (
        "\n\nFull calendar: /weeklycalendar"
        if compact
        else ""
    )

    return (
        "Earnings & Economic Calendar\n\n"
        + "\n\n".join(sections)
        + "\n\nMarket Impact\n"
        + impact
        + footer
    ).strip()


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
