import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_FILE = PROJECT_ROOT / "data" / "quarterly_market_data_cache.json"

REPORT_TIMEZONE = "America/Lima"
REQUEST_TIMEOUT = 8
CACHE_TTL_SECONDS = 60 * 60 * 24 * 5


MARKET_GROUPS = {
    "Benchmarks": [
        {"symbol": "^GSPC", "label": "S&P 500"},
        {"symbol": "^IXIC", "label": "Nasdaq Composite"},
        {"symbol": "^DJI", "label": "Dow Jones"},
        {"symbol": "^RUT", "label": "Russell 2000"},
        {"symbol": "RSP", "label": "Equal-Weight S&P 500"},
    ],
    "Sectors and Themes": [
        {"symbol": "SMH", "label": "Semiconductors"},
        {"symbol": "XLK", "label": "Technology"},
        {"symbol": "XLF", "label": "Financials"},
        {"symbol": "XLE", "label": "Energy"},
        {"symbol": "XLU", "label": "Utilities"},
        {"symbol": "XLI", "label": "Industrials"},
        {"symbol": "XLY", "label": "Consumer Discretionary"},
        {"symbol": "XLP", "label": "Consumer Staples"},
    ],
    "Macro Assets": [
        {"symbol": "TLT", "label": "Long Bonds"},
        {"symbol": "GLD", "label": "Gold"},
        {"symbol": "USO", "label": "Oil"},
        {"symbol": "UUP", "label": "U.S. Dollar"},
    ],
}


def clean_text(value: Any, max_length: int = 220) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default

        return float(value)
    except Exception:
        return default


def read_json(path: Path, default: Any):
    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)

    except Exception:
        return


def get_completed_quarter_label(now: datetime | None = None) -> str:
    now = now or datetime.now(ZoneInfo(REPORT_TIMEZONE))
    month = now.month
    year = now.year

    current_quarter = ((month - 1) // 3) + 1
    completed_quarter = current_quarter - 1

    if completed_quarter == 0:
        completed_quarter = 4
        year -= 1

    return f"Q{completed_quarter} {year}"


def parse_quarter_label(quarter_label: str | None = None) -> tuple[int, int, str]:
    label = clean_text(quarter_label or get_completed_quarter_label(), 40).upper()
    parts = label.replace("-", " ").split()

    quarter = None
    year = None

    for part in parts:
        if part.startswith("Q") and part[1:].isdigit():
            value = int(part[1:])

            if 1 <= value <= 4:
                quarter = value

        elif part.isdigit() and len(part) == 4:
            year = int(part)

    if quarter is None or year is None:
        fallback = get_completed_quarter_label()
        return parse_quarter_label(fallback)

    normalized = f"Q{quarter} {year}"

    return year, quarter, normalized


def get_quarter_date_range(quarter_label: str | None = None) -> tuple[date, date, str]:
    year, quarter, normalized = parse_quarter_label(quarter_label)

    start_month = ((quarter - 1) * 3) + 1
    start = date(year, start_month, 1)

    if quarter == 4:
        next_quarter_start = date(year + 1, 1, 1)
    else:
        next_quarter_start = date(year, start_month + 3, 1)

    end = next_quarter_start - timedelta(days=1)

    today = datetime.now(ZoneInfo(REPORT_TIMEZONE)).date()

    if end > today:
        end = today

    return start, end, normalized


def date_to_unix(value: date) -> int:
    dt = datetime(
        value.year,
        value.month,
        value.day,
        tzinfo=timezone.utc,
    )

    return int(dt.timestamp())


def request_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SmartMoneyAI/1.0",
            "Accept": "application/json, text/plain, */*",
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def fetch_symbol_return(symbol: str, start: date, end: date) -> dict:
    period1 = date_to_unix(start)
    period2 = date_to_unix(end + timedelta(days=1))

    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )

    try:
        payload = request_json(url)
        result = payload["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes = quote.get("close") or []

        clean_closes = [
            float(value)
            for value in closes
            if value is not None
        ]

        if len(clean_closes) < 2:
            return {
                "symbol": symbol,
                "return_percent": None,
                "error": "Not enough price data",
            }

        first = clean_closes[0]
        last = clean_closes[-1]

        if first == 0:
            return {
                "symbol": symbol,
                "return_percent": None,
                "error": "Invalid starting price",
            }

        return_percent = ((last - first) / first) * 100

        return {
            "symbol": symbol,
            "start_price": round(first, 2),
            "end_price": round(last, 2),
            "return_percent": round(return_percent, 2),
            "error": "",
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "return_percent": None,
            "error": f"{type(error).__name__}: {error}",
        }


def refresh_quarterly_market_cache(quarter_label: str | None = None) -> dict:
    start, end, normalized = get_quarter_date_range(quarter_label)

    groups = {}

    for group_name, assets in MARKET_GROUPS.items():
        group_rows = []

        for asset in assets:
            result = fetch_symbol_return(
                symbol=asset["symbol"],
                start=start,
                end=end,
            )

            result.update(
                {
                    "label": asset["label"],
                    "group": group_name,
                }
            )

            group_rows.append(result)

        groups[group_name] = group_rows

    payload = {
        "quarter_label": normalized,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "cached_at": time.time(),
        "cached_at_iso": datetime.now(ZoneInfo(REPORT_TIMEZONE)).isoformat(),
        "groups": groups,
    }

    cache = read_json(CACHE_FILE, {})

    if not isinstance(cache, dict):
        cache = {}

    quarters = cache.get("quarters", {})

    if not isinstance(quarters, dict):
        quarters = {}

    quarters[normalized] = payload

    write_json(
        CACHE_FILE,
        {
            "updated_at": time.time(),
            "updated_at_iso": datetime.now(ZoneInfo(REPORT_TIMEZONE)).isoformat(),
            "quarters": quarters,
        },
    )

    return payload


def load_quarterly_market_cache(quarter_label: str | None = None) -> dict:
    _year, _quarter, normalized = parse_quarter_label(quarter_label)
    cache = read_json(CACHE_FILE, {})

    if not isinstance(cache, dict):
        return {}

    quarters = cache.get("quarters", {})

    if not isinstance(quarters, dict):
        return {}

    payload = quarters.get(normalized)

    if isinstance(payload, dict):
        return payload

    return {}


def get_cached_or_empty_market_data(quarter_label: str | None = None) -> dict:
    payload = load_quarterly_market_cache(quarter_label)

    if payload:
        return payload

    return {
        "quarter_label": parse_quarter_label(quarter_label)[2],
        "start_date": "",
        "end_date": "",
        "cached_at_iso": "",
        "groups": {},
    }


def format_return(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    sign = "+" if number >= 0 else ""

    return f"{sign}{number:.2f}%"


def get_all_valid_rows(payload: dict) -> list[dict]:
    rows = []

    for group_rows in (payload.get("groups") or {}).values():
        for row in group_rows:
            if safe_float(row.get("return_percent")) is not None:
                rows.append(row)

    return rows


def get_return_for_label(payload: dict, label: str) -> float | None:
    for row in get_all_valid_rows(payload):
        if row.get("label") == label:
            return safe_float(row.get("return_percent"))

    return None


def format_group_rows(rows: list[dict]) -> str:
    if not rows:
        return "• No data available."

    lines = []

    for row in rows:
        label = row.get("label", row.get("symbol", "Unknown"))
        symbol = row.get("symbol", "")
        ret = format_return(row.get("return_percent"))

        if row.get("error") and row.get("return_percent") is None:
            lines.append(f"• {label} ({symbol}): N/A")
        else:
            lines.append(f"• {label} ({symbol}): {ret}")

    return "\n".join(lines)


def build_market_interpretation(payload: dict) -> str:
    rows = get_all_valid_rows(payload)

    if not rows:
        return "Market return data is not available yet. Run /quarterly refresh Q2 2026 to refresh the cache."

    best = max(rows, key=lambda row: safe_float(row.get("return_percent"), -999) or -999)
    worst = min(rows, key=lambda row: safe_float(row.get("return_percent"), 999) or 999)

    sp500 = get_return_for_label(payload, "S&P 500")
    nasdaq = get_return_for_label(payload, "Nasdaq Composite")
    russell = get_return_for_label(payload, "Russell 2000")
    equal_weight = get_return_for_label(payload, "Equal-Weight S&P 500")
    semis = get_return_for_label(payload, "Semiconductors")
    bonds = get_return_for_label(payload, "Long Bonds")
    oil = get_return_for_label(payload, "Oil")
    gold = get_return_for_label(payload, "Gold")

    notes = [
        f"Best performer in the attribution set: {best.get('label')} at {format_return(best.get('return_percent'))}.",
        f"Weakest performer in the attribution set: {worst.get('label')} at {format_return(worst.get('return_percent'))}.",
    ]

    if nasdaq is not None and sp500 is not None:
        if nasdaq > sp500:
            notes.append("Nasdaq leadership suggests growth and AI-related appetite helped drive the quarter.")
        else:
            notes.append("Nasdaq lagging the S&P 500 suggests growth leadership was less dominant or more selective.")

    if equal_weight is not None and sp500 is not None:
        if equal_weight > sp500:
            notes.append("Equal-weight outperformance suggests healthier market breadth.")
        else:
            notes.append("Equal-weight underperformance suggests leadership remained concentrated.")

    if russell is not None and sp500 is not None:
        if russell > sp500:
            notes.append("Small-cap strength suggests risk appetite broadened beyond mega-cap leaders.")
        else:
            notes.append("Small-cap lag suggests investors stayed selective and favored larger, higher-quality names.")

    if semis is not None and sp500 is not None:
        if semis > sp500:
            notes.append("Semiconductor outperformance supports the AI infrastructure thesis.")
        else:
            notes.append("Semiconductor lag suggests AI enthusiasm became more selective during the quarter.")

    if bonds is not None:
        if bonds < 0:
            notes.append("Long-bond weakness points to rate pressure or reduced duration appetite.")
        else:
            notes.append("Long-bond gains helped restore some diversification benefit.")

    if oil is not None and oil > 5:
        notes.append("Oil strength added inflation and geopolitical risk to the portfolio backdrop.")

    if gold is not None and gold > 5:
        notes.append("Gold strength suggests demand for safety, inflation protection, or dollar diversification.")

    return "\n".join(f"• {note}" for note in notes[:8])


def build_quarterly_market_attribution_section(quarter_label: str | None = None) -> str:
    payload = get_cached_or_empty_market_data(quarter_label)
    groups = payload.get("groups") or {}
    quarter = payload.get("quarter_label") or parse_quarter_label(quarter_label)[2]
    start_date = payload.get("start_date") or "N/A"
    end_date = payload.get("end_date") or "N/A"
    cached_at = payload.get("cached_at_iso") or "Not refreshed yet"

    benchmarks = groups.get("Benchmarks", [])
    sectors = groups.get("Sectors and Themes", [])
    macro = groups.get("Macro Assets", [])

    return f"""
Benchmark and Sector Attribution
Quarter: {quarter}
Period: {start_date} to {end_date}
Data Cache: {cached_at}

Benchmarks:
{format_group_rows(benchmarks)}

Sectors and Themes:
{format_group_rows(sectors)}

Macro Assets:
{format_group_rows(macro)}

Interpretation:
{build_market_interpretation(payload)}
""".strip()