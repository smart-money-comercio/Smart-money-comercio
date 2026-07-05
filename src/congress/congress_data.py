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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_FILE = CACHE_DIR / "congress_trades_cache.json"

FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
CACHE_TTL_SECONDS = int(os.getenv("CONGRESS_CACHE_TTL_SECONDS", "43200"))
MAX_PAGES = int(os.getenv("CONGRESS_MAX_PAGES", "3"))
PAGE_LIMIT = int(os.getenv("CONGRESS_PAGE_LIMIT", "100"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("CONGRESS_REQUEST_TIMEOUT_SECONDS", "12"))

_MEMORY_CACHE = None


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return " ".join(str(value).strip().split())


def clean_upper(value: Any) -> str:
    return clean_text(value).upper()


def first_value(record: dict, keys: list[str]) -> str:
    for key in keys:
        value = record.get(key)

        if value not in [None, ""]:
            return clean_text(value)

    return ""


def build_url(endpoint: str, page: int) -> str:
    query = {
        "page": page,
        "limit": PAGE_LIMIT,
        "apikey": FMP_API_KEY,
    }

    return f"{endpoint}?{urllib.parse.urlencode(query)}"


def fetch_json(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SmartMoneyAI/1.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = response.read().decode("utf-8")

    return json.loads(payload)


def extract_ticker(record: dict) -> str:
    direct = first_value(
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

    if direct:
        return clean_upper(direct).replace("$", "")

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
        ],
    )

    match = re.search(r"\(([A-Z]{1,6})\)", description.upper())

    if match:
        return match.group(1)

    return ""


def normalize_transaction(value: Any) -> str:
    text = clean_upper(value)

    if text in {"P", "BUY"} or "PURCHASE" in text or "BUY" in text:
        return "Purchase"

    if text in {"S", "SELL"} or "SALE" in text or "SELL" in text:
        return "Sale"

    if "EXCHANGE" in text:
        return "Exchange"

    return clean_text(value) or "Other"


def normalize_chamber(source: str, record: dict) -> str:
    chamber = first_value(record, ["chamber", "body"])

    if chamber:
        return chamber

    return source


def normalize_politician(record: dict) -> str:
    direct = first_value(
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
        ],
    )

    if direct:
        return direct

    first_name = first_value(record, ["firstName", "first_name"])
    last_name = first_value(record, ["lastName", "last_name"])

    full_name = " ".join(part for part in [first_name, last_name] if part)

    return full_name or "Unknown"


def normalize_sector(record: dict) -> str:
    return first_value(
        record,
        [
            "sector",
            "assetType",
            "asset_type",
            "assetDescription",
            "asset_description",
            "assetName",
            "asset_name",
            "description",
            "security",
        ],
    ) or "Congress Disclosure"


def normalize_amount(record: dict) -> str:
    return first_value(
        record,
        [
            "amount",
            "amountRange",
            "amount_range",
            "transactionAmount",
            "transaction_amount",
            "value",
            "valueRange",
            "value_range",
        ],
    ) or "Unknown"


def normalize_date(record: dict, keys: list[str]) -> str:
    return first_value(record, keys) or "Unknown"


def normalize_owner(record: dict) -> str:
    return first_value(
        record,
        [
            "owner",
            "ownership",
            "ownerType",
            "owner_type",
            "assetOwner",
            "asset_owner",
        ],
    ) or "Unknown"


def normalize_link(record: dict) -> str:
    return first_value(
        record,
        [
            "link",
            "url",
            "documentUrl",
            "document_url",
            "filingUrl",
            "filing_url",
            "sourceUrl",
            "source_url",
        ],
    )


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


def normalize_trade(record: dict, source: str) -> dict | None:
    ticker = extract_ticker(record)

    if not ticker:
        return None

    transaction = normalize_transaction(
        first_value(
            record,
            [
                "transaction",
                "transactionType",
                "transaction_type",
                "type",
                "action",
            ],
        )
    )

    sector = normalize_sector(record)

    disclosure_date = normalize_date(
        record,
        [
            "disclosureDate",
            "disclosure_date",
            "filingDate",
            "filing_date",
            "filedDate",
            "filed_date",
            "dateReceived",
            "publicationDate",
        ],
    )

    transaction_date = normalize_date(
        record,
        [
            "transactionDate",
            "transaction_date",
            "tradeDate",
            "trade_date",
            "date",
        ],
    )

    return {
        "politician": normalize_politician(record),
        "chamber": normalize_chamber(source, record),
        "ticker": ticker,
        "transaction": transaction,
        "sector": sector,
        "amount_range": normalize_amount(record),
        "disclosure_date": disclosure_date,
        "transaction_date": transaction_date,
        "owner": normalize_owner(record),
        "committee_relevance": classify_committee_relevance(sector),
        "signal": "Actual Congress Disclosure",
        "notes": "Fetched from live/cached congressional disclosure data.",
        "source": source,
        "source_url": normalize_link(record),
        "raw": record,
    }


def fetch_endpoint(endpoint: str, source: str) -> list[dict]:
    if not FMP_API_KEY:
        return []

    trades = []

    for page in range(MAX_PAGES):
        url = build_url(endpoint, page)

        try:
            payload = fetch_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            break
        except Exception:
            break

        if isinstance(payload, dict):
            if "Error Message" in payload or "error" in payload:
                break

            records = (
                payload.get("data")
                or payload.get("results")
                or payload.get("historical")
                or []
            )

        elif isinstance(payload, list):
            records = payload

        else:
            records = []

        if not records:
            break

        for record in records:
            if not isinstance(record, dict):
                continue

            normalized = normalize_trade(record, source)

            if normalized:
                trades.append(normalized)

        time.sleep(0.15)

    return trades


def fetch_live_congress_trades() -> list[dict]:
    trades = []

    trades.extend(fetch_endpoint(HOUSE_LATEST_ENDPOINT, "House"))
    trades.extend(fetch_endpoint(SENATE_LATEST_ENDPOINT, "Senate"))

    trades.sort(
        key=lambda trade: (
            str(trade.get("disclosure_date", "")),
            str(trade.get("transaction_date", "")),
            str(trade.get("ticker", "")),
        ),
        reverse=True,
    )

    if trades:
        save_cache(trades)
        return trades

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


def save_cache(trades: list[dict]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        payload = {
            "fetched_at": time.time(),
            "source": "Financial Modeling Prep House/Senate congressional disclosure endpoints",
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


# Compatibility only. Use get_congress_trades().
CONGRESS_TRADES = []