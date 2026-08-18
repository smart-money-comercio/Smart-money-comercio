import html
import json
import os
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


BASE_URL = "https://stockanalysis.com/stocks"
CACHE_FILE = Path(
    os.getenv("STOCKANALYSIS_CACHE_FILE", "data/stockanalysis_cache.json")
)
CACHE_TTL_SECONDS = int(os.getenv("STOCKANALYSIS_CACHE_TTL_SECONDS", "21600"))
TIMEZONE = os.getenv("REPORT_TIMEZONE", "America/Lima")
REQUEST_TIMEOUT = int(os.getenv("STOCKANALYSIS_TIMEOUT_SECONDS", "12"))

USER_AGENT = os.getenv(
    "STOCKANALYSIS_USER_AGENT",
    "SmartMoneyAI/1.4 research-only bot",
)


PAGE_PATHS = {
    "overview": "",
    "forecast": "forecast/",
    "statistics": "statistics/",
    "financials": "financials/",
    "balance_sheet": "financials/balance-sheet/",
    "cash_flow": "financials/cash-flow-statement/",
}


METRIC_ALIASES = {
    # Analyst / forecast fields
    "analyst_consensus": ["analyst consensus", "average rating", "consensus rating"],
    "price_target": ["price target", "average price target", "stock price target"],
    "price_target_low": ["low"],
    "price_target_average": ["average"],
    "price_target_median": ["median"],
    "price_target_high": ["high"],
    "strong_buy_count": ["strong buy"],
    "buy_count": ["buy"],
    "hold_count": ["hold"],
    "sell_count": ["sell"],
    "strong_sell_count": ["strong sell"],
    "analyst_total": ["total"],

    # Fundamentals / statements
    "revenue": ["revenue", "total revenue"],
    "gross_profit": ["gross profit"],
    "operating_income": ["operating income"],
    "net_income": ["net income"],
    "eps": ["eps", "eps diluted", "diluted eps"],
    "free_cash_flow": ["free cash flow"],
    "operating_cash_flow": [
        "operating cash flow",
        "cash from operations",
        "net cash provided by operating activities",
    ],
    "capital_expenditures": ["capital expenditures", "capital expenditure"],
    "cash_and_equivalents": [
        "cash & equivalents",
        "cash and equivalents",
        "cash and cash equivalents",
    ],
    "total_assets": ["total assets"],
    "total_liabilities": ["total liabilities"],
    "total_debt": ["total debt", "long-term debt", "short term debt"],
    "shareholders_equity": [
        "total equity",
        "shareholders' equity",
        "total shareholders' equity",
    ],
    "market_cap": ["market cap", "market capitalization"],
    "pe_ratio": ["pe ratio", "p/e ratio"],
    "forward_pe": ["forward pe", "forward p/e"],
    "price_to_sales": ["price/sales", "price to sales", "ps ratio"],
    "price_to_book": ["price/book", "price to book", "pb ratio"],
    "profit_margin": ["profit margin"],
    "roe": ["return on equity", "roe"],
    "roa": ["return on assets", "roa"],
}


def now_text() -> str:
    try:
        current = datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        current = datetime.now()

    return current.strftime("%Y-%m-%d %H:%M:%S")


def clean_symbol(symbol: str) -> str:
    return str(symbol or "").upper().replace("$", "").strip()


def normalize_label(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_key(value: str) -> str:
    text = normalize_label(value).lower()
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9%/ ]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact_text(value: Any, max_chars: int = 220) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_chars:
        return text

    return text[: max_chars - 3].rstrip() + "..."


def safe_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").replace(",", "").strip()
        match = re.search(r"-?\d+", text)

        if not match:
            return default

        return int(match.group(0))

    except Exception:
        return default


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_cell = []
        self.current_row = []
        self.tables = []
        self.current_table = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "table":
            self.in_table = True
            self.current_table = []

        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []

        elif self.in_table and tag in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()

        if self.in_table and tag in {"td", "th"} and self.in_cell:
            value = normalize_label(" ".join(self.current_cell))
            self.current_row.append(value)
            self.current_cell = []
            self.in_cell = False

        elif self.in_table and tag == "tr" and self.in_row:
            if any(cell for cell in self.current_row):
                self.current_table.append(self.current_row)

            self.current_row = []
            self.in_row = False

        elif tag == "table" and self.in_table:
            if self.current_table:
                self.tables.append(self.current_table)

            self.current_table = []
            self.in_table = False


def strip_tags(raw_html: str) -> str:
    text = re.sub(
        r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>",
        " ",
        raw_html,
        flags=re.I,
    )
    text = re.sub(
        r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_title(raw_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.I | re.S)

    if not match:
        return ""

    return normalize_label(strip_tags(match.group(1)))


def extract_meta_description(raw_html: str) -> str:
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_html, flags=re.I | re.S)

        if match:
            return compact_text(html.unescape(match.group(1)), 500)

    return ""


def load_cache() -> dict:
    try:
        if not CACHE_FILE.exists():
            return {}

        with CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with CACHE_FILE.open("w", encoding="utf-8") as file:
            json.dump(cache, file, indent=2, sort_keys=True)

    except Exception:
        return


def cache_key(symbol: str, page: str) -> str:
    return f"{clean_symbol(symbol)}::{page}"


def get_cached_page(symbol: str, page: str) -> dict | None:
    cache = load_cache()
    key = cache_key(symbol, page)
    item = cache.get(key)

    if not isinstance(item, dict):
        return None

    fetched_at_epoch = item.get("fetched_at_epoch")

    try:
        age = time.time() - float(fetched_at_epoch)
    except Exception:
        return None

    if age > CACHE_TTL_SECONDS:
        return None

    return item


def set_cached_page(symbol: str, page: str, payload: dict) -> None:
    cache = load_cache()
    key = cache_key(symbol, page)
    cache[key] = payload
    save_cache(cache)


def build_url(symbol: str, page: str) -> str:
    symbol = clean_symbol(symbol).lower()
    path = PAGE_PATHS.get(page, "")

    if path:
        return f"{BASE_URL}/{symbol}/{path}"

    return f"{BASE_URL}/{symbol}/"


def fetch_page(symbol: str, page: str, force_refresh: bool = False) -> dict:
    symbol = clean_symbol(symbol)
    page = str(page or "overview").strip()

    if not force_refresh:
        cached = get_cached_page(symbol, page)

        if cached:
            cached["cache_hit"] = True
            return cached

    url = build_url(symbol, page)

    try:
        request = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )

        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")

        payload = {
            "symbol": symbol,
            "page": page,
            "url": url,
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "status": "ok",
            "html": raw,
        }

        set_cached_page(symbol, page, payload)
        return payload

    except HTTPError as error:
        return {
            "symbol": symbol,
            "page": page,
            "url": url,
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "status": "error",
            "error": f"HTTPError {error.code}",
            "html": "",
        }

    except URLError as error:
        return {
            "symbol": symbol,
            "page": page,
            "url": url,
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "status": "error",
            "error": f"URLError {error.reason}",
            "html": "",
        }

    except Exception as error:
        return {
            "symbol": symbol,
            "page": page,
            "url": url,
            "fetched_at": now_text(),
            "fetched_at_epoch": time.time(),
            "cache_hit": False,
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
            "html": "",
        }


def parse_tables(raw_html: str) -> list[list[list[str]]]:
    parser = TableParser()

    try:
        parser.feed(raw_html or "")
    except Exception:
        return []

    return parser.tables


def row_to_label_values(row: list[str]) -> tuple[str, list[str]]:
    if not row:
        return "", []

    label = normalize_label(row[0])
    values = [normalize_label(value) for value in row[1:] if normalize_label(value)]

    return label, values


def find_metric_from_tables(tables: list[list[list[str]]], aliases: list[str]) -> str:
    alias_keys = [normalize_key(alias) for alias in aliases]

    for table in tables:
        for row in table:
            label, values = row_to_label_values(row)

            if not label or not values:
                continue

            label_key = normalize_key(label)

            if any(alias == label_key or alias in label_key for alias in alias_keys):
                return values[0]

    return ""


def parse_page_summary(page_payload: dict) -> dict:
    raw = page_payload.get("html", "") or ""
    tables = parse_tables(raw)
    text = strip_tags(raw)

    return {
        "page": page_payload.get("page"),
        "url": page_payload.get("url"),
        "status": page_payload.get("status"),
        "error": page_payload.get("error", ""),
        "cache_hit": page_payload.get("cache_hit", False),
        "fetched_at": page_payload.get("fetched_at"),
        "title": extract_title(raw),
        "description": extract_meta_description(raw),
        "text": compact_text(text, 25000),
        "table_count": len(tables),
        "tables": tables[:10],
    }


def collect_metrics(page_summaries: dict[str, dict]) -> dict[str, str]:
    all_tables = []

    for page in page_summaries.values():
        if not isinstance(page, dict):
            continue

        tables = page.get("tables", [])

        if isinstance(tables, list):
            all_tables.extend(tables)

    metrics = {}

    for metric_name, aliases in METRIC_ALIASES.items():
        value = find_metric_from_tables(all_tables, aliases)

        if value:
            metrics[metric_name] = value

    return metrics


def first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            return normalize_label(match.group(1))

    return ""


def normalize_percent(value: str) -> str:
    value = normalize_label(value)

    if not value:
        return ""

    if value.endswith("%"):
        return value

    return f"{value}%"


def normalize_money(value: str) -> str:
    value = normalize_label(value)

    if not value:
        return ""

    if value.startswith("$"):
        return value

    return f"${value}"


def combined_page_text(page_summaries: dict[str, dict]) -> str:
    parts = []
    preferred_pages = ["forecast", "overview", "statistics"]

    for page_name in preferred_pages:
        page = page_summaries.get(page_name, {})

        if not isinstance(page, dict):
            continue

        parts.extend(
            [
                str(page.get("title", "")),
                str(page.get("description", "")),
                str(page.get("text", "")),
            ]
        )

    for page_name, page in page_summaries.items():
        if page_name in preferred_pages or not isinstance(page, dict):
            continue

        parts.extend(
            [
                str(page.get("title", "")),
                str(page.get("description", "")),
                str(page.get("text", "")),
            ]
        )

    return " ".join(parts)


def extract_recommendation_trend_from_rows(page_summaries: dict[str, dict]) -> dict[str, str]:
    rating_data = {}
    all_rows = []

    for page in page_summaries.values():
        if not isinstance(page, dict):
            continue

        raw_tables = page.get("tables", [])

        for table in raw_tables if isinstance(raw_tables, list) else []:
            for row in table if isinstance(table, list) else []:
                if isinstance(row, list) and row:
                    all_rows.append(row)

    for row in all_rows:
        label = normalize_key(row[0])
        values = [normalize_label(value) for value in row[1:] if normalize_label(value)]
        latest_value = values[-1] if values else ""

        if not latest_value:
            continue

        if label == "strong buy":
            rating_data["strong_buy_count"] = latest_value

        elif label == "buy":
            rating_data["buy_count"] = latest_value

        elif label == "hold":
            rating_data["hold_count"] = latest_value

        elif label == "sell":
            rating_data["sell_count"] = latest_value

        elif label == "strong sell":
            rating_data["strong_sell_count"] = latest_value

        elif label == "total":
            rating_data["analyst_total"] = latest_value

        elif "analyst consensus" in label or "average rating" in label:
            rating_data["analyst_consensus"] = latest_value

        elif "price target" in label:
            rating_data["price_target"] = latest_value

    return rating_data


def extract_forecast_rating_data(page_summaries: dict[str, dict]) -> dict[str, str]:
    rating_data = extract_recommendation_trend_from_rows(page_summaries)
    text = combined_page_text(page_summaries)

    consensus = first_match(
        text,
        [
            r'consensus rating of ["“]([^"”]+)["”]',
            r'average rating for [A-Z]+ stock is ["“]([^"”]+)["”]',
            r'average rating for .*? stock is ["“]([^"”]+)["”]',
            r'Analyst Consensus:\s*([A-Za-z ]+)',
            r'Analyst Consensus\s+([A-Za-z ]+?)\s+(?:Price Target|According|Stock Forecast|$)',
            r'consensus rating is ([A-Za-z ]+)',
            r'\b(Strong Buy|Buy|Hold|Sell|Strong Sell)\b',
        ],
    )

    if consensus:
        rating_data["analyst_consensus"] = consensus.strip(" .")

    analyst_total = first_match(
        text,
        [
            r'According to ([0-9,]+) analysts',
            r'According to ([0-9,]+) analysts polled',
            r'based on ([0-9,]+) analysts',
            r'([0-9,]+) analysts recommend',
        ],
    )

    if analyst_total:
        rating_data["analyst_total"] = analyst_total

    price_target = first_match(
        text,
        [
            r'average price target of \$?([0-9,.]+)',
            r'12-month stock price target is \$?([0-9,.]+)',
            r'average price target for .*? is \$?([0-9,.]+)',
            r'Price Target\s*\$?([0-9,.]+)',
        ],
    )

    if price_target:
        rating_data["price_target"] = normalize_money(price_target)

    upside = first_match(
        text,
        [
            r'which is an increase of ([+-]?[0-9,.]+%)',
            r'which is a decrease of ([+-]?[0-9,.]+%)',
            r'forecast is ([+-]?[0-9,.]+%) higher',
            r'forecast is ([+-]?[0-9,.]+%) lower',
            r'\(([+-]?[0-9,.]+%) upside\)',
            r'([+-]?[0-9,.]+%) from the latest price',
        ],
    )

    if upside:
        rating_data["price_target_upside"] = normalize_percent(upside)

    return rating_data


def fetch_stockanalysis_data(symbol: str, force_refresh: bool = False) -> dict:
    symbol = clean_symbol(symbol)

    if not symbol:
        return {
            "symbol": "",
            "available": False,
            "source": "StockAnalysis.com",
            "fetched_at": now_text(),
            "pages": {},
            "metrics": {},
            "errors": ["Missing symbol"],
        }

    pages = {}
    errors = []

    for page in PAGE_PATHS:
        payload = fetch_page(symbol, page, force_refresh=force_refresh)
        summary = parse_page_summary(payload)
        pages[page] = summary

        if payload.get("status") != "ok":
            errors.append(f"{page}: {payload.get('error', 'unknown error')}")

    metrics = collect_metrics(pages)
    metrics.update(extract_forecast_rating_data(pages))

    return {
        "symbol": symbol,
        "available": bool(
            metrics or any(page.get("status") == "ok" for page in pages.values())
        ),
        "source": "StockAnalysis.com",
        "fetched_at": now_text(),
        "pages": pages,
        "metrics": metrics,
        "errors": errors,
    }


def metric_line(metrics: dict, key: str, label: str) -> str:
    value = metrics.get(key)

    if not value:
        return ""

    return f"• {label}: {value}"


def build_stockanalysis_snapshot(symbol: str, force_refresh: bool = False) -> str:
    data = fetch_stockanalysis_data(symbol, force_refresh=force_refresh)
    metrics = data.get("metrics", {})

    if not data.get("available"):
        errors = data.get("errors") or ["No usable StockAnalysis data returned."]
        return (
            f"StockAnalysis Snapshot: {clean_symbol(symbol)}\n"
            "Status: unavailable\n\n"
            + "\n".join(f"• {error}" for error in errors[:5])
        )

    lines = [
        f"StockAnalysis Snapshot: {data['symbol']}",
        f"Source: {data['source']}",
        f"Fetched: {data['fetched_at']}",
        "",
        "Valuation / Market",
        metric_line(metrics, "market_cap", "Market Cap"),
        metric_line(metrics, "pe_ratio", "P/E"),
        metric_line(metrics, "forward_pe", "Forward P/E"),
        metric_line(metrics, "price_to_sales", "Price/Sales"),
        metric_line(metrics, "price_to_book", "Price/Book"),
        "",
        "Income Quality",
        metric_line(metrics, "revenue", "Revenue"),
        metric_line(metrics, "gross_profit", "Gross Profit"),
        metric_line(metrics, "operating_income", "Operating Income"),
        metric_line(metrics, "net_income", "Net Income"),
        metric_line(metrics, "eps", "EPS"),
        "",
        "Cash Flow / Balance Sheet",
        metric_line(metrics, "operating_cash_flow", "Operating Cash Flow"),
        metric_line(metrics, "free_cash_flow", "Free Cash Flow"),
        metric_line(metrics, "capital_expenditures", "Capital Expenditures"),
        metric_line(metrics, "cash_and_equivalents", "Cash & Equivalents"),
        metric_line(metrics, "total_debt", "Total Debt"),
        metric_line(metrics, "total_assets", "Total Assets"),
        metric_line(metrics, "total_liabilities", "Total Liabilities"),
    ]

    clean_lines = [
        line
        for line in lines
        if line is not None and str(line).strip() != ""
    ]

    if data.get("errors"):
        clean_lines.extend(
            [
                "",
                "Source Notes",
                *[f"• {error}" for error in data["errors"][:4]],
            ]
        )

    return "\n".join(clean_lines).strip()


def build_stockanalysis_rating_interpretation(metrics: dict) -> str:
    consensus = str(metrics.get("analyst_consensus") or "").lower()

    strong_buy = safe_int(metrics.get("strong_buy_count"))
    buy = safe_int(metrics.get("buy_count"))
    hold = safe_int(metrics.get("hold_count"))
    sell = safe_int(metrics.get("sell_count"))
    strong_sell = safe_int(metrics.get("strong_sell_count"))

    bullish = strong_buy + buy
    bearish = sell + strong_sell
    total = bullish + hold + bearish

    if "strong buy" in consensus:
        return "• Analyst setup is strongly bullish. Confirm with valuation, volume, filings, and macro risk."

    if "buy" in consensus:
        return "• Analyst setup leans bullish. Treat as supportive, not standalone confirmation."

    if "hold" in consensus:
        return "• Analyst setup is neutral. Require stronger Smart Money or technical confirmation."

    if "sell" in consensus:
        return "• Analyst setup is bearish. Treat as a risk flag unless other signals strongly offset it."

    if total > 0:
        if bullish >= max(hold + bearish, 1) * 2:
            return "• Analyst vote mix is strongly bullish. Confirm with Smart Money score, risk, and filings."

        if bullish > hold + bearish:
            return "• Analyst vote mix leans bullish. Useful support, but not a standalone buy signal."

        if hold >= bullish and hold >= bearish:
            return "• Analyst vote mix is mostly neutral. Wait for stronger confirmation."

        if bearish > bullish:
            return "• Analyst vote mix leans bearish. Treat as a risk flag."

    return "• Analyst setup is mixed or unavailable. Use /analyst, /scorecard, /risk, and /filing for confirmation."


def build_stockanalysis_rating_section(symbol: str, force_refresh: bool = False) -> str:
    symbol = clean_symbol(symbol)

    if not symbol:
        return (
            "StockAnalysis Rating\n"
            "Status: unavailable\n"
            "• Missing symbol."
        )

    data = fetch_stockanalysis_data(symbol, force_refresh=force_refresh)
    metrics = data.get("metrics", {}) if isinstance(data, dict) else {}

    if not isinstance(metrics, dict):
        metrics = {}

    consensus = metrics.get("analyst_consensus", "")
    price_target = metrics.get("price_target", "")
    upside = metrics.get("price_target_upside", "")

    strong_buy = metrics.get("strong_buy_count", "")
    buy = metrics.get("buy_count", "")
    hold = metrics.get("hold_count", "")
    sell = metrics.get("sell_count", "")
    strong_sell = metrics.get("strong_sell_count", "")
    total = metrics.get("analyst_total", "")

    return f"""
StockAnalysis Rating: {symbol}
Source: {data.get("source", "StockAnalysis.com") if isinstance(data, dict) else "StockAnalysis.com"}
Fetched: {data.get("fetched_at", now_text()) if isinstance(data, dict) else now_text()}

External Analyst Consensus
• Consensus: {consensus or "Unavailable"}
• Price Target: {price_target or "Unavailable"}
• Implied Upside/Downside: {upside or "Unavailable"}

Buy / Hold / Sell Mix
• Strong Buy: {strong_buy or "N/A"}
• Buy: {buy or "N/A"}
• Hold: {hold or "N/A"}
• Sell: {sell or "N/A"}
• Strong Sell: {strong_sell or "N/A"}
• Total Analysts: {total or "N/A"}

Interpretation
{build_stockanalysis_rating_interpretation(metrics)}
""".strip()