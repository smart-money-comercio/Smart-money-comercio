import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError


FMP_BASE_URL = "https://financialmodelingprep.com/stable"
HOUSE_LATEST_ENDPOINT = f"{FMP_BASE_URL}/house-latest"
SENATE_LATEST_ENDPOINT = f"{FMP_BASE_URL}/senate-latest"

HOUSE_STOCKWATCHER_URL = (
    "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
)
SENATE_STOCKWATCHER_URL = (
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_FILE = CACHE_DIR / "congress_trades_cache.json"
DEBUG_FILE = CACHE_DIR / "congress_debug.json"

CACHE_TTL_SECONDS = int(os.getenv("CONGRESS_CACHE_TTL_SECONDS", "43200"))
MAX_PAGES = int(os.getenv("CONGRESS_MAX_PAGES", "3"))
PAGE_LIMIT = int(os.getenv("CONGRESS_PAGE_LIMIT", "100"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("CONGRESS_REQUEST_TIMEOUT_SECONDS", "15"))
STOCKWATCHER_MAX_RECORDS = int(os.getenv("STOCKWATCHER_MAX_RECORDS", "250"))

_MEMORY_CACHE = None


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


def clean_ticker(value: Any) -> str:
    text = clean_upper(value).replace("$", "").replace(":US", "")
    text = text.replace("/", ".")
    if text in {"", "--", "N/A", "NONE", "UNKNOWN"}:
        return ""
    return text


def first_value(record: dict, keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value not in [None, ""]:
            return clean_text(value)
    return ""


def write_debug(payload: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        DEBUG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def append_debug(provider: str, payload: dict) -> None:
    existing = {}

    try:
        if DEBUG_FILE.exists():
            existing = json.loads(DEBUG_FILE.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

    existing[provider] = payload
    write_debug(existing)


def fetch_json(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SmartMoneyAI/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = response.read().decode("utf-8", errors="replace")

    return json.loads(payload)


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
    trades.sort(
        key=lambda trade: (
            str(trade.get("disclosure_date", "")),
            str(trade.get("transaction_date", "")),
            str(trade.get("ticker", "")),
        ),
        reverse=True,
    )
    return trades


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
    ) or "Unknown"

    sector = description or first_value(record, ["sector", "assetType", "asset_type"]) or "Congress Disclosure"

    return {
        "politician": politician,
        "chamber": first_value(record, ["chamber", "body"]) or source,
        "ticker": ticker,
        "transaction": normalize_transaction(
            first_value(record, ["transaction", "transactionType", "transaction_type", "type", "action"])
        ),
        "sector": sector,
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


def fetch_fmp_endpoint(endpoint: str, source: str) -> tuple[list[dict], list[dict]]:
    if not get_fmp_api_key():
        return [], [{"source": source, "reason": "FMP_API_KEY is missing"}]

    trades = []
    debug_pages = []

    for page in range(MAX_PAGES):
        try:
            payload = fetch_json(build_fmp_url(endpoint, page))

        except HTTPError as error:
            debug_pages.append(
                {"page": page, "source": source, "http_error": error.code, "reason": str(error)}
            )
            break

        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            debug_pages.append(
                {"page": page, "source": source, "error_type": type(error).__name__, "reason": str(error)}
            )
            break

        except Exception as error:
            debug_pages.append(
                {"page": page, "source": source, "error_type": type(error).__name__, "reason": str(error)}
            )
            break

        records = extract_records(payload)

        debug_pages.append(
            {
                "page": page,
                "source": source,
                "record_count": len(records) if isinstance(records, list) else 0,
                "sample_keys": list(records[0].keys()) if records and isinstance(records[0], dict) else [],
            }
        )

        if not records:
            break

        for record in records:
            if not isinstance(record, dict):
                continue

            trade = normalize_fmp_trade(record, source)

            if trade:
                trades.append(trade)

    return trades, debug_pages


def fetch_fmp_congress_trades() -> list[dict]:
    house_trades, house_debug = fetch_fmp_endpoint(HOUSE_LATEST_ENDPOINT, "House")
    senate_trades, senate_debug = fetch_fmp_endpoint(SENATE_LATEST_ENDPOINT, "Senate")

    trades = house_trades + senate_trades

    append_debug(
        "fmp",
        {
            "ok": bool(trades),
            "provider": "fmp",
            "fmp_key_loaded": bool(get_fmp_api_key()),
            "normalized_trade_count": len(trades),
            "house_pages": house_debug,
            "senate_pages": senate_debug,
        },
    )

    return sort_trades(trades)


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
            HOUSE_STOCKWATCHER_URL if chamber == "House" else SENATE_STOCKWATCHER_URL
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


def fetch_stockwatcher_congress_trades() -> list[dict]:
    debug = {
        "provider": "stockwatcher",
        "house_url": HOUSE_STOCKWATCHER_URL,
        "senate_url": SENATE_STOCKWATCHER_URL,
    }

    trades = []

    try:
        house_payload = fetch_json(HOUSE_STOCKWATCHER_URL)
        house_trades = normalize_stockwatcher_payload(house_payload, "House")
        trades.extend(house_trades)
        debug["house_ok"] = True
        debug["house_count"] = len(house_trades)
        debug["house_payload_type"] = type(house_payload).__name__
        if isinstance(house_payload, list) and house_payload:
            debug["house_sample_keys"] = list(house_payload[0].keys())
    except Exception as error:
        debug["house_ok"] = False
        debug["house_error_type"] = type(error).__name__
        debug["house_error"] = str(error)

    try:
        senate_payload = fetch_json(SENATE_STOCKWATCHER_URL)
        senate_trades = normalize_stockwatcher_payload(senate_payload, "Senate")
        trades.extend(senate_trades)
        debug["senate_ok"] = True
        debug["senate_count"] = len(senate_trades)
        debug["senate_payload_type"] = type(senate_payload).__name__
        if isinstance(senate_payload, list) and senate_payload:
            debug["senate_sample_keys"] = list(senate_payload[0].keys())
    except Exception as error:
        debug["senate_ok"] = False
        debug["senate_error_type"] = type(error).__name__
        debug["senate_error"] = str(error)

    trades = sort_trades(trades)

    if STOCKWATCHER_MAX_RECORDS > 0:
        trades = trades[:STOCKWATCHER_MAX_RECORDS]

    debug["ok"] = bool(trades)
    debug["normalized_trade_count"] = len(trades)
    debug["sample_trades"] = trades[:3]

    append_debug("stockwatcher", debug)

    return trades


def fetch_live_congress_trades() -> list[dict]:
    provider = get_provider()

    append_debug(
        "provider",
        {
            "requested_provider": provider,
            "timestamp": time.time(),
            "order": "auto = fmp, then stockwatcher",
        },
    )

    if provider in {"auto", "fmp"}:
        fmp_trades = fetch_fmp_congress_trades()

        if fmp_trades:
            save_cache(fmp_trades, source="FMP House/Senate congressional disclosure endpoints")
            return fmp_trades

        if provider == "fmp":
            return load_stale_cache()

    if provider in {"auto", "stockwatcher", "stock_watcher"}:
        stockwatcher_trades = fetch_stockwatcher_congress_trades()

        if stockwatcher_trades:
            save_cache(stockwatcher_trades, source="House/Senate Stock Watcher public JSON datasets")
            return stockwatcher_trades

        if provider in {"stockwatcher", "stock_watcher"}:
            return load_stale_cache()

    return load_stale_cache()


def load_cache() -> list[dict] | None:
    if not CACHE_FILE.exists():
        return None

    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    fetched_at = float(payload.get("fetched_at", 0) or 0)
    trades = payload.get("trades", [])

    if not isinstance(trades, list):
        return None

    age = time.time() - fetched_at

    if age <= CACHE_TTL_SECONDS:
        return trades

    return None


def load_stale_cache() -> list[dict]:
    if not CACHE_FILE.exists():
        return []

    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        trades = payload.get("trades", [])
        return trades if isinstance(trades, list) else []
    except Exception:
        return []


def save_cache(trades: list[dict], source: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        payload = {
            "fetched_at": time.time(),
            "source": source,
            "provider": get_provider(),
            "trades": trades,
        }

        CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    except Exception:
        pass


def get_congress_trades(force_refresh: bool = False) -> list[dict]:
    global _MEMORY_CACHE

    if _MEMORY_CACHE is not None and not force_refresh:
        return _MEMORY_CACHE

    if not force_refresh:
        cached = load_cache()

        if cached is not None:
            _MEMORY_CACHE = cached
            return _MEMORY_CACHE

    _MEMORY_CACHE = fetch_live_congress_trades()
    return _MEMORY_CACHE


CONGRESS_TRADES = []