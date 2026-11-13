import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.intelligence import transaction_cache


FMP_BASE_URL = "https://financialmodelingprep.com/stable"
HOUSE_LATEST_ENDPOINT = f"{FMP_BASE_URL}/house-latest"
SENATE_LATEST_ENDPOINT = f"{FMP_BASE_URL}/senate-latest"

HOUSE_STOCKWATCHER_URLS = [
    "https://housestockwatcher.com/api",
    "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
]

SENATE_STOCKWATCHER_URLS = [
    "https://raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/master/aggregate/all_transactions.json",
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_FILE = CACHE_DIR / "congress_trades_cache.json"

CACHE_TTL_SECONDS = int(os.getenv("CONGRESS_CACHE_TTL_SECONDS", "43200"))
MAX_PAGES = int(os.getenv("CONGRESS_MAX_PAGES", "3"))
PAGE_LIMIT = int(os.getenv("CONGRESS_PAGE_LIMIT", "100"))
STOCKWATCHER_MAX_RECORDS = int(os.getenv("STOCKWATCHER_MAX_RECORDS", "250"))

FMP_SOURCE = "FMP House/Senate congressional disclosure endpoints"
STOCKWATCHER_SOURCE = "House/Senate Stock Watcher public JSON datasets"
CONGRESS_PROVIDERS = {FMP_SOURCE: "FMP", STOCKWATCHER_SOURCE: "Stock Watcher"}
CHAMBERS = ("House", "Senate")
MAX_FEED_AGE = timedelta(days=30)
MAX_TRADE_AGE = timedelta(days=60)
CACHE_MAX_AGE = timedelta(hours=36)
NY = ZoneInfo("America/New_York")


def get_provider() -> str:
    return os.getenv("CONGRESS_DATA_PROVIDER", "auto").strip().lower() or "auto"


def get_fmp_api_key() -> str:
    return os.getenv("FMP_API_KEY", "").strip()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def clean_upper(value: Any) -> str:
    return clean_text(value).upper()


INVALID_TICKER_TOKENS = {
    "",
    "--",
    "N/A",
    "N.A",
    "NA",
    "NONE",
    "UNKNOWN",
    "RECEIVED",
    "EXCHANGED",
    "EXCHANGE",
    "CALLABLE",
    "MATURES",
    "RATE",
    "COUPON",
    "BOND",
    "BONDS",
    "NOTE",
    "NOTES",
    "TREASURY",
    "T-BILL",
}


def clean_ticker(value: Any) -> str:
    text = clean_upper(value)
    text = text.replace("$", "").replace(":US", "").replace("/", ".")

    if text in INVALID_TICKER_TOKENS:
        return ""

    if not re.match(r"^[A-Z][A-Z0-9.-]{0,9}$", text):
        return ""

    return text


def first_value(record: dict, keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value not in [None, ""]:
            return clean_text(value)
    return ""


def build_fmp_url(endpoint: str, page: int) -> str:
    query = {
        "page": page,
        "limit": PAGE_LIMIT,
        "apikey": get_fmp_api_key(),
    }
    return f"{endpoint}?{urllib.parse.urlencode(query)}"


def extract_records(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        return (
            payload.get("data")
            or payload.get("results")
            or payload.get("historical")
            or payload.get("items")
            or []
        )

    return []


def normalize_transaction(value: Any) -> str:
    text = clean_upper(value)

    if "PURCHASE" in text or text in {"P", "BUY"} or "BUY" in text:
        return "Purchase"

    if "SALE" in text or text in {"S", "SELL"} or "SELL" in text:
        return "Sale"

    if "EXCHANGE" in text:
        return "Exchange"

    return clean_text(value) or "Other"


def normalize_amount(value: Any) -> str:
    text = clean_text(value)

    if not text or text.upper() in {"--", "N/A", "NONE"}:
        return "Unknown"

    return text.replace("–", "-")

def parse_date_value(value: Any) -> datetime:
    text = clean_text(value)

    if not text or text.upper() in {"UNKNOWN", "N/A", "--"}:
        return datetime.min

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text, re.ASCII):
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return datetime.min

    formats = [
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ]

    for date_format in formats:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue

    return datetime.min


def congress_chamber(value: Any) -> str | None:
    return {"house of representatives": "House", "house": "House", "senate": "Senate"}.get(clean_text(value).casefold())


def transaction_dates(row: dict, as_of):
    filed = parse_date_value(row.get("disclosure_date")).date()
    traded = parse_date_value(row.get("transaction_date")).date()
    if datetime.min.date() < traded <= filed <= as_of:
        return traded, filed
    return None


def recently_filed(row: dict, as_of) -> bool:
    dates = transaction_dates(row, as_of)
    return bool(dates and as_of - dates[1] <= MAX_FEED_AGE)


def trade_sort_datetime(trade: dict) -> datetime:
    transaction_date = parse_date_value(trade.get("transaction_date"))
    disclosure_date = parse_date_value(trade.get("disclosure_date"))

    if transaction_date != datetime.min:
        return transaction_date

    return disclosure_date


def is_trade_recent_enough(trade: dict) -> bool:
    min_year = int(os.getenv("CONGRESS_MIN_YEAR", "2020"))
    trade_date = trade_sort_datetime(trade)

    if trade_date == datetime.min:
        return True

    return trade_date.year >= min_year

def classify_committee_relevance(sector: str) -> str:
    text = clean_upper(sector)

    high_keywords = [
        "DEFENSE",
        "AEROSPACE",
        "MISSILE",
        "CYBER",
        "SEMICONDUCTOR",
        "AI",
        "ARTIFICIAL INTELLIGENCE",
        "ENERGY",
        "HEALTHCARE",
        "PHARMA",
        "BANK",
        "FINANCIAL",
    ]

    medium_keywords = [
        "CLOUD",
        "SOFTWARE",
        "TECH",
        "INDUSTRIAL",
        "TELECOM",
        "INFRASTRUCTURE",
    ]

    if any(keyword in text for keyword in high_keywords):
        return "High"

    if any(keyword in text for keyword in medium_keywords):
        return "Medium"

    return "Unknown"


def extract_ticker_from_description(description: str) -> str:
    match = re.search(r"\(([A-Z]{1,8})\)", clean_upper(description))
    if match:
        return clean_ticker(match.group(1))
    return ""


def sort_trades(trades: list[dict]) -> list[dict]:
    clean_trades = []

    seen = set()

    for trade in trades:
        ticker = clean_ticker(trade.get("ticker"))

        if not ticker:
            continue

        trade["ticker"] = ticker

        if not is_trade_recent_enough(trade):
            continue

        dedupe_key = (
            trade.get("politician"),
            trade.get("ticker"),
            trade.get("transaction"),
            trade.get("amount_range"),
            trade.get("transaction_date"),
            trade.get("owner"),
        )

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        clean_trades.append(trade)

    clean_trades.sort(
        key=lambda trade: (
            trade_sort_datetime(trade),
            str(trade.get("ticker", "")),
        ),
        reverse=True,
    )

    return clean_trades

def normalize_fmp_trade(record: dict, source: str) -> dict | None:
    description = first_value(
        record,
        [
            "assetDescription",
            "asset_description",
            "asset",
            "assetName",
            "asset_name",
            "description",
            "security",
            "securityName",
            "securityDescription",
        ],
    )

    ticker = clean_ticker(
        first_value(
            record,
            [
                "symbol",
                "ticker",
                "assetSymbol",
                "asset_symbol",
                "securityTicker",
                "security_ticker",
            ],
        )
    )

    if not ticker:
        ticker = extract_ticker_from_description(description)

    if not ticker:
        return None

    politician = first_value(
        record,
        [
            "politician",
            "representative",
            "senator",
            "name",
            "member",
            "memberName",
            "member_name",
            "office",
            "firstLast",
            "first_last",
        ],
    ) or " ".join(filter(None, (first_value(record, ["firstName", "first_name"]),
                               first_value(record, ["lastName", "last_name"])))) or "Unknown"

    sector = description or first_value(record, ["sector", "assetType", "asset_type"]) or "Congress Disclosure"

    return {
        "politician": politician,
        "chamber": first_value(record, ["chamber", "body"]) or source,
        "ticker": ticker,
        "transaction": normalize_transaction(
            first_value(record, ["transaction", "transactionType", "transaction_type", "type", "action"])
        ),
        "sector": sector,
        "asset_type": first_value(record, ["assetType", "asset_type", "securityType", "security_type"]),
        "amount_range": normalize_amount(
            first_value(record, ["amount", "amountRange", "amount_range", "value", "valueRange", "value_range", "range"])
        ),
        "disclosure_date": first_value(
            record,
            ["disclosureDate", "disclosure_date", "filingDate", "filing_date", "filedDate", "dateReceived"],
        ) or "Unknown",
        "transaction_date": first_value(record, ["transactionDate", "transaction_date", "tradeDate", "date"]) or "Unknown",
        "owner": first_value(record, ["owner", "ownership", "ownerType", "assetOwner"]) or "Unknown",
        "committee_relevance": classify_committee_relevance(sector),
        "signal": "Actual Congress Disclosure",
        "notes": "Fetched from FMP congressional disclosure endpoint.",
        "source": source,
        "source_url": first_value(record, ["link", "url", "documentUrl", "filingUrl", "sourceUrl"]),
    }


def build_person_name(record: dict) -> str:
    first_name = first_value(record, ["first_name", "firstName"])
    last_name = first_value(record, ["last_name", "lastName"])

    if first_name or last_name:
        return clean_text(f"{first_name} {last_name}")

    return first_value(
        record,
        ["senator", "representative", "politician", "name", "office"],
    ) or "Unknown"


def normalize_stockwatcher_trade(record: dict, chamber: str) -> dict | None:
    ticker = clean_ticker(first_value(record, ["ticker", "symbol"]))

    description = first_value(
        record,
        [
            "asset_description",
            "assetDescription",
            "asset",
            "asset_name",
            "assetName",
            "security",
            "issuer",
        ],
    )

    if not ticker:
        ticker = extract_ticker_from_description(description)

    if not ticker:
        return None

    sector = description or first_value(record, ["asset_type", "assetType"]) or "Stock Watcher Disclosure"

    return {
        "politician": build_person_name(record),
        "chamber": chamber,
        "ticker": ticker,
        "transaction": normalize_transaction(first_value(record, ["type", "transaction", "transaction_type"])),
        "sector": sector,
        "asset_type": first_value(record, ["asset_type", "assetType", "security_type", "securityType"]),
        "amount_range": normalize_amount(first_value(record, ["amount", "amount_range", "amountRange", "value"])),
        "disclosure_date": first_value(
            record,
            [
                "disclosure_date",
                "disclosureDate",
                "date_recieved",
                "date_received",
                "filing_date",
                "filingDate",
            ],
        ) or "Unknown",
        "transaction_date": first_value(
            record,
            [
                "transaction_date",
                "transactionDate",
                "trade_date",
                "tradeDate",
            ],
        ) or "Unknown",
        "owner": first_value(record, ["owner", "ownership"]) or "Unknown",
        "committee_relevance": classify_committee_relevance(sector),
        "signal": "Actual Congress Disclosure",
        "notes": "Fetched from public Stock Watcher JSON dataset.",
        "source": f"{chamber} Stock Watcher",
        "source_url": first_value(record, ["ptr_link", "ptrLink", "url", "link"]) or (
             HOUSE_STOCKWATCHER_URLS[0] if chamber == "House" else SENATE_STOCKWATCHER_URLS[0]
        ),
    }


def normalize_stockwatcher_payload(payload, chamber: str) -> list[dict]:
    trades = []
    records = payload if isinstance(payload, list) else extract_records(payload)

    for record in records:
        if not isinstance(record, dict):
            continue

        nested_transactions = record.get("transactions")

        if isinstance(nested_transactions, list):
            base = {
                key: value
                for key, value in record.items()
                if key != "transactions"
            }

            for transaction in nested_transactions:
                if not isinstance(transaction, dict):
                    continue

                merged = {**base, **transaction}
                trade = normalize_stockwatcher_trade(merged, chamber)

                if trade:
                    trades.append(trade)

        else:
            trade = normalize_stockwatcher_trade(record, chamber)

            if trade:
                trades.append(trade)

    return trades


def _snapshot():
    try:
        return transaction_cache.read(CACHE_FILE)
    except OSError:
        return {}, None


def _current_rows(payload, now):
    from src.intelligence.transaction_disclosures import scope_observations

    observations = scope_observations("congress", payload, now)
    today = now.astimezone(NY).date()
    result = []
    for row in transaction_cache.rows(payload):
        observation = observations.get(congress_chamber(row.get("chamber")))
        if not observation or now.timestamp() - observation["at"] > CACHE_MAX_AGE.total_seconds():
            continue
        seen = datetime.fromtimestamp(observation["at"], NY).date()
        dates = transaction_dates(row, seen)
        if dates and today - dates[1] <= MAX_FEED_AGE and today - dates[0] <= MAX_TRADE_AGE and clean_ticker(row.get("ticker")):
            result.append(row)
    return result, observations


@lru_cache(maxsize=2)
def _scoring_payload(path, revision):
    try:
        return transaction_cache.read(path)[0]
    except OSError:
        return {}


def cached_coverage(now=None):
    now = now or datetime.now(timezone.utc)
    payload, _ = _snapshot()
    current, observations = _current_rows(payload, now)
    records = transaction_cache.rows(payload)
    lines = []
    for chamber in CHAMBERS:
        observed = observations.get(chamber)
        chamber_rows = [row for row in records if congress_chamber(row.get("chamber")) == chamber]
        dated = max((parse_date_value(row.get("disclosure_date")) for row in chamber_rows), default=datetime.min)
        status = ("Current" if now.timestamp() - observed["at"] <= CACHE_MAX_AGE.total_seconds() else "Stale") if observed else "Unavailable"
        detail = f" | {observed['provider']}" if observed else ""
        if dated != datetime.min:
            detail += f" | Latest cached disclosure {dated.date().isoformat()}"
        elif chamber_rows:
            traded = max(parse_date_value(row.get("transaction_date")) for row in chamber_rows)
            if traded != datetime.min:
                detail += f" | Latest cached trade {traded.date().isoformat()} | Disclosure dates unavailable"
        lines.append(f"{chamber} — {status}{detail}")
    if not current:
        lines.append("Congress input is neutral (50/100) while recent dated trade evidence is unavailable.")
    return current, "\n".join(lines)


def get_congress_trades(force_refresh: bool = False) -> list[dict]:
    if force_refresh:
        from src.jobs.disclosure_refresh import refresh_congress_now

        refresh_congress_now()
        return cached_coverage()[0]
    try:
        revision = transaction_cache.revision(CACHE_FILE.stat())
    except OSError:
        return []
    payload = _scoring_payload(CACHE_FILE, revision)
    return [dict(row) for row in _current_rows(payload, datetime.now(timezone.utc))[0]]


CONGRESS_TRADES = []
