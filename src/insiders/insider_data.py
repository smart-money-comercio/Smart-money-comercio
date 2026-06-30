import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_FILE = CACHE_DIR / "insider_trades_cache.json"

CACHE_TTL_SECONDS = int(os.getenv("INSIDER_CACHE_TTL_SECONDS", "43200"))
SEC_SLEEP_SECONDS = float(os.getenv("SEC_SLEEP_SECONDS", "0.12"))
SEC_TIMEOUT_SECONDS = int(os.getenv("SEC_TIMEOUT_SECONDS", "10"))
MAX_FORM4_PER_TICKER = int(os.getenv("INSIDER_MAX_FORM4_PER_TICKER", "4"))

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "SmartMoneyAI/1.0 contact@example.com",
)


FALLBACK_TICKERS = [
    "NVDA",
    "MSFT",
    "AVGO",
    "META",
    "AMZN",
    "GOOGL",
    "AMD",
    "AAPL",
    "TSLA",
    "SHOP",
    "NFLX",
    "PLTR",
    "LMT",
    "NOC",
    "RTX",
    "GD",
    "HII",
    "AVAV",
    "KTOS",
    "RKLB",
    "ONDS",
    "CRWD",
    "PANW",
    "FTNT",
    "ZS",
    "QQQ",
    "VOO",
    "ITA",
    "CIBR",
    "SCHD",
    "VYM",
    "JNJ",
    "PG",
    "KO",
    "PEP",
    "ABBV",
    "O",
    "VZ",
    "T",
    "MO",
    "XOM",
    "CVX",
]


_MEMORY_CACHE = None


def get_headers() -> dict:
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json,text/xml,application/xml,*/*",
    }


def sleep_for_sec_rate_limit() -> None:
    if SEC_SLEEP_SECONDS > 0:
        time.sleep(SEC_SLEEP_SECONDS)


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers=get_headers())

    with urllib.request.urlopen(request, timeout=SEC_TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_json(url: str) -> dict:
    payload = fetch_url(url)
    return json.loads(payload.decode("utf-8"))


def normalize_cik(cik) -> str:
    return str(cik).strip().zfill(10)


def clean_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper().replace("$", "")


def get_watchlist_tickers() -> list[str]:
    try:
        from src.scoring.watchlist import WATCHLIST

        tickers = [
            clean_ticker(stock.get("ticker"))
            for stock in WATCHLIST
            if isinstance(stock, dict) and stock.get("ticker")
        ]

        unique_tickers = sorted(set(tickers))

        if unique_tickers:
            return unique_tickers

    except Exception:
        pass

    return FALLBACK_TICKERS


def load_ticker_cik_map() -> dict[str, str]:
    data = fetch_json(SEC_TICKERS_URL)
    ticker_map = {}

    for item in data.values():
        ticker = clean_ticker(item.get("ticker"))
        cik = item.get("cik_str")

        if ticker and cik:
            ticker_map[ticker] = normalize_cik(cik)

    return ticker_map


def get_recent_form4_filings(cik: str) -> list[dict]:
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    data = fetch_json(url)

    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_documents = recent.get("primaryDocument", [])

    filings = []

    for index, form_type in enumerate(forms):
        if form_type not in {"4", "4/A"}:
            continue

        accession = accession_numbers[index] if index < len(accession_numbers) else ""
        filing_date = filing_dates[index] if index < len(filing_dates) else ""
        document = primary_documents[index] if index < len(primary_documents) else ""

        if not accession or not document:
            continue

        filings.append(
            {
                "form": form_type,
                "accession": accession,
                "filing_date": filing_date,
                "document": document,
            }
        )

        if len(filings) >= MAX_FORM4_PER_TICKER:
            break

    return filings


def build_filing_url(cik: str, filing: dict) -> str:
    accession_no_dashes = filing["accession"].replace("-", "")
    document = urllib.parse.quote(filing["document"], safe="/")

    return SEC_ARCHIVES_URL.format(
        cik=str(int(cik)),
        accession=accession_no_dashes,
        document=document,
    )


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def find_first_text(root, name: str) -> str:
    for element in root.iter():
        if local_name(element.tag) == name and element.text:
            return element.text.strip()

    return ""


def find_children_by_name(root, name: str) -> list:
    return [
        element
        for element in root.iter()
        if local_name(element.tag) == name
    ]


def get_child_text(parent, child_name: str) -> str:
    for child in parent.iter():
        if local_name(child.tag) == child_name and child.text:
            return child.text.strip()

    return ""


def parse_float(value: str):
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def amount_to_range(amount: float | None) -> str:
    if amount is None:
        return "Unknown"

    if amount >= 10_000_000:
        return "$10M+"
    if amount >= 5_000_000:
        return "$5M - $10M"
    if amount >= 2_000_000:
        return "$2M - $5M"
    if amount >= 1_000_000:
        return "$1M - $2M"
    if amount >= 500_000:
        return "$500K - $1M"
    if amount >= 250_000:
        return "$250K - $500K"
    if amount >= 100_000:
        return "$100K - $250K"
    if amount >= 50_000:
        return "$50K - $100K"

    return "Under $50K"


def transaction_label(code: str) -> str:
    clean_code = str(code or "").strip().upper()

    if clean_code == "P":
        return "Purchase"

    if clean_code == "S":
        return "Sale"

    return f"Other ({clean_code})" if clean_code else "Other"


def get_reporting_owner_role(root) -> str:
    relationship_nodes = find_children_by_name(root, "reportingOwnerRelationship")

    if not relationship_nodes:
        return "Insider"

    relationship = relationship_nodes[0]

    officer_title = get_child_text(relationship, "officerTitle")
    is_director = get_child_text(relationship, "isDirector")
    is_officer = get_child_text(relationship, "isOfficer")
    is_ten_percent_owner = get_child_text(relationship, "isTenPercentOwner")

    title_upper = officer_title.upper()

    if "CEO" in title_upper or "CHIEF EXECUTIVE" in title_upper:
        return "CEO"

    if "CFO" in title_upper or "CHIEF FINANCIAL" in title_upper:
        return "CFO"

    if "COO" in title_upper or "CHIEF OPERATING" in title_upper:
        return "COO"

    if officer_title:
        return officer_title

    if is_director in {"1", "true", "True"}:
        return "Director"

    if is_ten_percent_owner in {"1", "true", "True"}:
        return "10% Owner"

    if is_officer in {"1", "true", "True"}:
        return "Officer"

    return "Insider"


def parse_form4_transactions(xml_payload: bytes, fallback_ticker: str, filing: dict, source_url: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_payload)
    except ET.ParseError:
        return []

    ticker = clean_ticker(find_first_text(root, "issuerTradingSymbol") or fallback_ticker)
    owner_name = find_first_text(root, "rptOwnerName")
    insider_role = get_reporting_owner_role(root)

    transactions = []

    for transaction in find_children_by_name(root, "nonDerivativeTransaction"):
        code = get_child_text(transaction, "transactionCode")
        label = transaction_label(code)

        if label not in {"Purchase", "Sale"}:
            continue

        transaction_date = get_child_text(transaction, "transactionDate")
        shares = parse_float(get_child_text(transaction, "transactionShares"))
        price = parse_float(get_child_text(transaction, "transactionPricePerShare"))

        amount = None
        if shares is not None and price is not None:
            amount = shares * price

        transactions.append(
            {
                "insider": insider_role,
                "insider_name": owner_name or "Unknown",
                "ticker": ticker,
                "transaction": label,
                "transaction_code": code,
                "amount_range": amount_to_range(amount),
                "amount_estimate": round(amount, 2) if amount is not None else None,
                "shares": shares,
                "price": price,
                "sector": "SEC Form 4",
                "date": transaction_date or filing.get("filing_date") or "Unknown",
                "filing_date": filing.get("filing_date", "Unknown"),
                "form": filing.get("form", "4"),
                "accession": filing.get("accession", ""),
                "source_url": source_url,
                "signal": "Actual SEC Form 4",
                "notes": "Parsed from SEC Form 4 non-derivative transaction data.",
            }
        )

    return transactions


def fetch_form4_transactions_for_ticker(ticker: str, ticker_cik_map: dict[str, str]) -> list[dict]:
    clean = clean_ticker(ticker)
    cik = ticker_cik_map.get(clean)

    if not cik:
        return []

    try:
        filings = get_recent_form4_filings(cik)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []
    except Exception:
        return []

    trades = []

    for filing in filings:
        source_url = build_filing_url(cik, filing)

        try:
            sleep_for_sec_rate_limit()
            xml_payload = fetch_url(source_url)
            trades.extend(
                parse_form4_transactions(
                    xml_payload=xml_payload,
                    fallback_ticker=clean,
                    filing=filing,
                    source_url=source_url,
                )
            )
        except Exception:
            continue

    return trades


def load_cache() -> list[dict] | None:
    if not CACHE_FILE.exists():
        return None

    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    fetched_at = payload.get("fetched_at", 0)
    trades = payload.get("trades", [])

    if not isinstance(trades, list):
        return None

    age = time.time() - float(fetched_at or 0)

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
            "source": "SEC Form 4 via EDGAR submissions API",
            "trades": trades,
        }
        CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def fetch_live_insider_trades(tickers: list[str] | None = None) -> list[dict]:
    symbols = tickers or get_watchlist_tickers()
    symbols = sorted(set(clean_ticker(symbol) for symbol in symbols if clean_ticker(symbol)))

    try:
        ticker_cik_map = load_ticker_cik_map()
    except Exception:
        return load_stale_cache()

    trades = []

    for symbol in symbols:
        sleep_for_sec_rate_limit()
        trades.extend(fetch_form4_transactions_for_ticker(symbol, ticker_cik_map))

    if trades:
        trades.sort(
            key=lambda trade: (
                str(trade.get("date", "")),
                str(trade.get("ticker", "")),
            ),
            reverse=True,
        )
        save_cache(trades)
        return trades

    return load_stale_cache()


def get_insider_trades(tickers: list[str] | None = None, force_refresh: bool = False) -> list[dict]:
    global _MEMORY_CACHE

    if _MEMORY_CACHE is not None and not force_refresh:
        return _MEMORY_CACHE

    if not force_refresh:
        cached = load_cache()

        if cached is not None:
            _MEMORY_CACHE = cached
            return _MEMORY_CACHE

    _MEMORY_CACHE = fetch_live_insider_trades(tickers)
    return _MEMORY_CACHE


# Compatibility only. The scoring module should call get_insider_trades().
INSIDER_TRADES = []