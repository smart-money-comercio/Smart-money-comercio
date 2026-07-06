import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError


FMP_BASE_URL = "https://financialmodelingprep.com/stable"
HOUSE_LATEST_ENDPOINT = f"{FMP_BASE_URL}/house-latest"
SENATE_LATEST_ENDPOINT = f"{FMP_BASE_URL}/senate-latest"

CAPITOL_TRADES_URL = "https://www.capitoltrades.com/trades"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_FILE = CACHE_DIR / "congress_trades_cache.json"
DEBUG_FILE = CACHE_DIR / "congress_debug.json"

CACHE_TTL_SECONDS = int(os.getenv("CONGRESS_CACHE_TTL_SECONDS", "43200"))
MAX_PAGES = int(os.getenv("CONGRESS_MAX_PAGES", "3"))
PAGE_LIMIT = int(os.getenv("CONGRESS_PAGE_LIMIT", "100"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("CONGRESS_REQUEST_TIMEOUT_SECONDS", "12"))

_MEMORY_CACHE = None


class LinkTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_link = False
        self.current_href = ""
        self.current_text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        self.in_link = True
        self.current_href = ""
        self.current_text = []

        for key, value in attrs:
            if key.lower() == "href":
                self.current_href = value or ""

    def handle_data(self, data):
        if self.in_link:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self.in_link:
            return

        text = clean_text(" ".join(self.current_text))

        if text:
            self.links.append(
                {
                    "href": self.current_href,
                    "text": text,
                }
            )

        self.in_link = False
        self.current_href = ""
        self.current_text = []

class PageTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_items = []

    def handle_data(self, data):
        text = clean_text(html.unescape(data))

        if text:
            self.text_items.append(text)
            
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


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 SmartMoneyAI/1.0",
            "Accept": "text/html,application/json,*/*",
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="replace")


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
            "securityDescription",
        ],
    )

    match = re.search(r"\(([A-Z]{1,8})\)", description.upper())

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
    return first_value(record, ["chamber", "body"]) or source


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
            "firstLast",
            "first_last",
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
            "securityDescription",
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
            "range",
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


def normalize_fmp_trade(record: dict, source: str) -> dict | None:
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
        "notes": "Fetched from FMP House/Senate congressional disclosure endpoint.",
        "source": source,
        "source_url": normalize_link(record),
    }


def fetch_fmp_endpoint(endpoint: str, source: str) -> tuple[list[dict], list[dict]]:
    api_key = get_fmp_api_key()

    if not api_key:
        return [], [
            {
                "source": source,
                "reason": "FMP_API_KEY is missing or not loaded",
            }
        ]

    trades = []
    debug_pages = []

    for page in range(MAX_PAGES):
        url = build_fmp_url(endpoint, page)

        try:
            payload = fetch_json(url)

        except HTTPError as error:
            debug_pages.append(
                {
                    "page": page,
                    "source": source,
                    "http_error": error.code,
                    "reason": str(error),
                }
            )
            break

        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            debug_pages.append(
                {
                    "page": page,
                    "source": source,
                    "error_type": type(error).__name__,
                    "reason": str(error),
                }
            )
            break

        except Exception as error:
            debug_pages.append(
                {
                    "page": page,
                    "source": source,
                    "error_type": type(error).__name__,
                    "reason": str(error),
                }
            )
            break

        if isinstance(payload, dict) and ("Error Message" in payload or "error" in payload):
            debug_pages.append(
                {
                    "page": page,
                    "source": source,
                    "api_error": payload,
                }
            )
            break

        records = extract_records(payload)

        debug_pages.append(
            {
                "page": page,
                "source": source,
                "payload_type": type(payload).__name__,
                "record_count": len(records) if isinstance(records, list) else 0,
                "sample_keys": list(records[0].keys()) if records and isinstance(records[0], dict) else [],
            }
        )

        if not records:
            break

        for record in records:
            if not isinstance(record, dict):
                continue

            normalized = normalize_fmp_trade(record, source)

            if normalized:
                trades.append(normalized)

        time.sleep(0.15)

    return trades, debug_pages


def fetch_fmp_congress_trades() -> list[dict]:
    trades = []

    house_trades, house_debug = fetch_fmp_endpoint(HOUSE_LATEST_ENDPOINT, "House")
    senate_trades, senate_debug = fetch_fmp_endpoint(SENATE_LATEST_ENDPOINT, "Senate")

    trades.extend(house_trades)
    trades.extend(senate_trades)

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


def parse_capitol_trades_link(link: dict) -> dict | None:
    text = html.unescape(clean_text(link.get("text", "")))
    href = link.get("href") or ""

    if not re.match(r"^(buy|sell|exchange)\b", text, flags=re.IGNORECASE):
        return None

    ticker_match = re.search(r"\b([A-Z][A-Z0-9./-]{0,8}):US\b", text)

    if not ticker_match:
        return None

    ticker = ticker_match.group(1).replace("/", ".")

    before_ticker = text[: ticker_match.start()].strip()
    after_ticker = text[ticker_match.end():].strip()

    first_space = before_ticker.find(" ")

    if first_space == -1:
        return None

    transaction_raw = before_ticker[:first_space]
    description = before_ticker[first_space + 1:].strip()

    tail_match = re.search(
        r"(?P<politician>.+?)\s+"
        r"(?P<party>Democrat|Republican|Independent)\s+"
        r"(?P<chamber>House|Senate)\s+"
        r"(?P<state>[A-Z]{2})\s+"
        r"(?P<amount>[0-9.,]+[KMB]?\s*[–-]\s*[0-9.,]+[KMB]?|[0-9.,]+[KMB]?)$",
        after_ticker,
        flags=re.IGNORECASE,
    )

    if not tail_match:
        return None

    transaction = normalize_transaction(transaction_raw)
    amount = tail_match.group("amount").replace("–", "-")
    chamber = tail_match.group("chamber")
    politician = clean_text(tail_match.group("politician"))
    party = tail_match.group("party")
    state = tail_match.group("state")

    source_url = ""

    if href:
        if href.startswith("http"):
            source_url = href
        else:
            source_url = urllib.parse.urljoin(CAPITOL_TRADES_URL, href)

    return {
        "politician": politician,
        "chamber": chamber,
        "ticker": ticker,
        "transaction": transaction,
        "sector": description or "Capitol Trades Disclosure",
        "amount_range": amount,
        "disclosure_date": "Latest",
        "transaction_date": "Unknown",
        "owner": "Unknown",
        "committee_relevance": classify_committee_relevance(description),
        "signal": "Actual Congress Disclosure",
        "notes": f"Fetched from Capitol Trades public latest trades page. Party: {party}. State: {state}.",
        "source": "Capitol Trades",
        "source_url": source_url,
    }

def is_capitol_ticker_token(value: str) -> bool:
    text = clean_text(value)

    if text == "N/A":
        return False

    return bool(re.match(r"^[A-Z][A-Z0-9./-]{0,8}:US$", text))


def parse_party_chamber_state(value: str) -> dict:
    text = clean_text(value)

    match = re.match(
        r"^(Democrat|Republican|Independent)\s+(House|Senate)\s+([A-Z]{2})$",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return {
            "party": "Unknown",
            "chamber": "Unknown",
            "state": "Unknown",
        }

    return {
        "party": match.group(1).title(),
        "chamber": match.group(2).title(),
        "state": match.group(3).upper(),
    }


def normalize_capitol_amount(value: str) -> str:
    text = clean_text(value).replace("–", "-")

    if not text:
        return "Unknown"

    parts = [part.strip() for part in text.split("-")]

    normalized_parts = []

    for part in parts:
        if not part:
            continue

        if not part.startswith("$"):
            part = f"${part}"

        normalized_parts.append(part)

    if len(normalized_parts) == 2:
        return f"{normalized_parts[0]} - {normalized_parts[1]}"

    if len(normalized_parts) == 1:
        return normalized_parts[0]

    return text


def find_transaction_index(tokens: list[str], start_index: int, max_lookahead: int = 14) -> int | None:
    transaction_words = {"buy", "sell", "exchange", "purchase", "sale"}

    end_index = min(len(tokens), start_index + max_lookahead)

    for index in range(start_index, end_index):
        token = clean_text(tokens[index]).lower()

        if token in transaction_words:
            return index

    return None


def parse_capitol_trades_from_tokens(tokens: list[str]) -> list[dict]:
    trades = []
    seen = set()

    for index, token in enumerate(tokens):
        if not is_capitol_ticker_token(token):
            continue

        if index < 3:
            continue

        politician = clean_text(tokens[index - 3])
        party_line = clean_text(tokens[index - 2])
        issuer = clean_text(tokens[index - 1])
        ticker = token.replace(":US", "").replace("/", ".")

        party_info = parse_party_chamber_state(party_line)

        if party_info["chamber"] == "Unknown":
            continue

        transaction_index = find_transaction_index(tokens, index + 1)

        if transaction_index is None:
            continue

        transaction_raw = tokens[transaction_index]
        transaction = normalize_transaction(transaction_raw)

        owner = "Unknown"

        if transaction_index - 1 > index:
            owner_candidate = clean_text(tokens[transaction_index - 1])

            if owner_candidate.lower() not in {"days", "day"} and not owner_candidate.isdigit():
                owner = owner_candidate

        amount = "Unknown"

        if transaction_index + 1 < len(tokens):
            amount = normalize_capitol_amount(tokens[transaction_index + 1])

        published = "Unknown"

        if index + 2 < len(tokens):
            published = clean_text(tokens[index + 2])

        transaction_date = "Unknown"

        if index + 3 < len(tokens):
            transaction_date = clean_text(tokens[index + 3])

            if index + 4 < len(tokens) and re.match(r"^\d{4}$", clean_text(tokens[index + 4])):
                transaction_date = f"{transaction_date} {clean_text(tokens[index + 4])}"

        dedupe_key = (
            politician,
            ticker,
            transaction,
            amount,
            transaction_date,
            owner,
        )

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)

        trades.append(
            {
                "politician": politician,
                "chamber": party_info["chamber"],
                "ticker": ticker,
                "transaction": transaction,
                "sector": issuer or "Capitol Trades Disclosure",
                "amount_range": amount,
                "disclosure_date": published,
                "transaction_date": transaction_date,
                "owner": owner,
                "committee_relevance": classify_committee_relevance(issuer),
                "signal": "Actual Congress Disclosure",
                "notes": (
                    "Fetched from Capitol Trades public latest trades page. "
                    f"Party: {party_info['party']}. State: {party_info['state']}."
                ),
                "source": "Capitol Trades",
                "source_url": CAPITOL_TRADES_URL,
            }
        )

    return trades

def fetch_capitol_trades_public() -> list[dict]:
    try:
        page = fetch_text(CAPITOL_TRADES_URL)

    except Exception as error:
        append_debug(
            "capitoltrades",
            {
                "ok": False,
                "provider": "capitoltrades",
                "error_type": type(error).__name__,
                "reason": str(error),
            },
        )
        return []

    parser = PageTextParser()
    parser.feed(page)

    trades = parse_capitol_trades_from_tokens(parser.text_items)

    append_debug(
        "capitoltrades",
        {
            "ok": bool(trades),
            "provider": "capitoltrades",
            "normalized_trade_count": len(trades),
            "sample_tokens": parser.text_items[:80],
            "sample_trades": trades[:3],
        },
    )

    return sort_trades(trades)


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


def fetch_live_congress_trades() -> list[dict]:
    provider = get_provider()

    provider_debug = {
        "requested_provider": provider,
        "timestamp": time.time(),
    }

    append_debug("provider", provider_debug)

    trades = []

    if provider in {"auto", "fmp"}:
        trades = fetch_fmp_congress_trades()

        if trades:
            save_cache(trades, source="FMP House/Senate congressional disclosure endpoints")
            return trades

        if provider == "fmp":
            return load_stale_cache()

    if provider in {"auto", "capitoltrades", "capitol_trades"}:
        trades = fetch_capitol_trades_public()

        if trades:
            save_cache(trades, source="Capitol Trades public latest trades page")
            return trades

        if provider in {"capitoltrades", "capitol_trades"}:
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


# Compatibility only. Use get_congress_trades().
CONGRESS_TRADES = []