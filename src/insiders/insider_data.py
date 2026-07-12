import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scoring.watchlist import WATCHLIST


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_FILE = PROJECT_ROOT / "data" / "insider_trades_cache.json"
CIK_CACHE_FILE = PROJECT_ROOT / "data" / "sec_company_tickers_cache.json"

CACHE_TTL_SECONDS = int(os.getenv("INSIDER_CACHE_TTL_SECONDS", str(60 * 60 * 8)))
CIK_CACHE_TTL_SECONDS = int(os.getenv("SEC_CIK_CACHE_TTL_SECONDS", str(60 * 60 * 24 * 7)))

REQUEST_TIMEOUT = int(os.getenv("SEC_REQUEST_TIMEOUT", "8"))
REQUEST_DELAY_SECONDS = float(os.getenv("SEC_REQUEST_DELAY_SECONDS", "0.12"))

MAX_TICKERS = int(os.getenv("INSIDER_MAX_TICKERS", "80"))
MAX_FILINGS_PER_TICKER = int(os.getenv("INSIDER_MAX_FILINGS_PER_TICKER", "8"))

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "SmartMoneyAI/1.0 admin@example.com",
)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"


TRANSACTION_LABELS = {
    "P": "Open Market Purchase",
    "S": "Sale",
    "A": "Award / Grant",
    "M": "Option Exercise",
    "F": "Tax Withholding / Disposition",
    "G": "Gift",
    "D": "Disposition",
    "J": "Other",
}


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("$", "")


def clean_text(value: Any, max_length: int = 180) -> str:
    text = " ".join(str(value or "").split())

    if len(text) <= max_length:
        return text

    return text[: max_length - 3].rstrip() + "..."


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        text = str(value).replace(",", "").strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    number = safe_float(value, None)

    if number is None:
        return default

    return int(number)


def utc_now_ts() -> float:
    return time.time()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json_file(path: Path, default: Any):
    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    except Exception:
        return default


def write_json_file(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)

    except Exception:
        return


def sec_request(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Host": urllib.parse.urlparse(url).netloc,
        },
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read()

    time.sleep(REQUEST_DELAY_SECONDS)

    return raw


def fetch_json(url: str) -> dict:
    raw = sec_request(url)
    return json.loads(raw.decode("utf-8", errors="ignore"))


def fetch_text(url: str) -> str:
    raw = sec_request(url)
    return raw.decode("utf-8", errors="ignore")


def normalize_cik(value: Any) -> str:
    return str(value or "").strip().zfill(10)


def get_watchlist_symbols() -> list[str]:
    symbols = []

    for item in WATCHLIST:
        symbol = clean_symbol(item.get("ticker") or item.get("symbol"))
        if symbol and symbol not in symbols:
            symbols.append(symbol)

    return symbols[:MAX_TICKERS]


def load_company_ticker_map(force_refresh: bool = False) -> dict:
    cached = read_json_file(CIK_CACHE_FILE, {})

    if (
        not force_refresh
        and isinstance(cached, dict)
        and cached.get("cached_at")
        and utc_now_ts() - float(cached.get("cached_at", 0)) <= CIK_CACHE_TTL_SECONDS
        and isinstance(cached.get("tickers"), dict)
    ):
        return cached["tickers"]

    data = fetch_json(COMPANY_TICKERS_URL)
    ticker_map = {}

    for item in data.values():
        ticker = clean_symbol(item.get("ticker"))
        cik = normalize_cik(item.get("cik_str"))
        title = clean_text(item.get("title"), 160)

        if ticker and cik:
            ticker_map[ticker] = {
                "ticker": ticker,
                "cik": cik,
                "company": title,
            }

    write_json_file(
        CIK_CACHE_FILE,
        {
            "cached_at": utc_now_ts(),
            "cached_at_iso": iso_now(),
            "tickers": ticker_map,
        },
    )

    return ticker_map


def get_cik_for_ticker(ticker: str, force_refresh: bool = False) -> dict | None:
    symbol = clean_symbol(ticker)

    if not symbol:
        return None

    ticker_map = load_company_ticker_map(force_refresh=force_refresh)

    return ticker_map.get(symbol)


def get_recent_form4_filings(ticker: str, force_refresh: bool = False) -> list[dict]:
    cik_info = get_cik_for_ticker(ticker, force_refresh=force_refresh)

    if not cik_info:
        return []

    cik = cik_info["cik"]
    url = SUBMISSIONS_URL.format(cik=cik)

    try:
        payload = fetch_json(url)
    except Exception:
        return []

    recent = payload.get("filings", {}).get("recent", {})

    forms = recent.get("form") or []
    accession_numbers = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    primary_documents = recent.get("primaryDocument") or []

    filings = []

    for index, form in enumerate(forms):
        if str(form).upper() not in {"4", "4/A"}:
            continue

        accession = accession_numbers[index] if index < len(accession_numbers) else ""
        filing_date = filing_dates[index] if index < len(filing_dates) else ""
        report_date = report_dates[index] if index < len(report_dates) else ""
        primary_document = primary_documents[index] if index < len(primary_documents) else ""

        if not accession or not primary_document:
            continue

        filings.append(
            {
                "ticker": clean_symbol(ticker),
                "cik": cik,
                "company": cik_info.get("company", ""),
                "form": str(form).upper(),
                "accession": accession,
                "filing_date": filing_date,
                "report_date": report_date,
                "primary_document": primary_document,
            }
        )

        if len(filings) >= MAX_FILINGS_PER_TICKER:
            break

    return filings


def build_filing_url(filing: dict) -> str:
    cik_no_zeros = str(int(filing["cik"]))
    accession_no_dashes = str(filing["accession"]).replace("-", "")
    primary_document = filing["primary_document"]

    return (
        f"{ARCHIVES_BASE_URL}/"
        f"{cik_no_zeros}/"
        f"{accession_no_dashes}/"
        f"{primary_document}"
    )


def xml_find_text(node: ET.Element, path: str, default: str = "") -> str:
    found = node.find(path)

    if found is None or found.text is None:
        return default

    return clean_text(found.text, 240)


def parse_owner_relationship(root: ET.Element) -> dict:
    owner = root.find(".//reportingOwner")
    relationship = root.find(".//reportingOwnerRelationship")

    owner_name = ""
    role = "Insider"

    if owner is not None:
        owner_name = xml_find_text(owner, ".//rptOwnerName", "")

    if relationship is not None:
        is_director = xml_find_text(relationship, ".//isDirector", "0") == "1"
        is_officer = xml_find_text(relationship, ".//isOfficer", "0") == "1"
        is_ten_percent = xml_find_text(relationship, ".//isTenPercentOwner", "0") == "1"
        officer_title = xml_find_text(relationship, ".//officerTitle", "")

        role_parts = []

        if officer_title:
            role_parts.append(officer_title)
        elif is_officer:
            role_parts.append("Officer")

        if is_director:
            role_parts.append("Director")

        if is_ten_percent:
            role_parts.append("10% Owner")

        if role_parts:
            role = " / ".join(role_parts)

    return {
        "insider_name": owner_name or "Unknown Insider",
        "role": role,
    }


def classify_transaction(code: str, acquired_disposed: str = "") -> tuple[str, str]:
    code = clean_text(code, 10).upper()
    acquired_disposed = clean_text(acquired_disposed, 10).upper()

    label = TRANSACTION_LABELS.get(code, f"Code {code or 'Unknown'}")

    if code == "P":
        return label, "Bullish Purchase"

    if code == "S":
        return label, "Sale"

    if code == "F":
        return label, "Tax / Withholding"

    if code == "M":
        return label, "Option Exercise"

    if code == "A":
        return label, "Award / Grant"

    if code == "G":
        return label, "Gift"

    if acquired_disposed == "A":
        return label, "Acquired"

    if acquired_disposed == "D":
        return label, "Disposed"

    return label, "Neutral"


def parse_form4_xml(xml_text: str, filing: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    issuer_symbol = clean_symbol(xml_find_text(root, ".//issuerTradingSymbol", filing.get("ticker")))
    issuer_name = xml_find_text(root, ".//issuerName", filing.get("company", ""))
    owner_info = parse_owner_relationship(root)

    transactions = []

    for node in root.findall(".//nonDerivativeTransaction"):
        transaction_date = xml_find_text(node, ".//transactionDate/value", "")
        code = xml_find_text(node, ".//transactionCoding/transactionCode", "")
        acquired_disposed = xml_find_text(node, ".//transactionAmounts/transactionAcquiredDisposedCode/value", "")
        shares = safe_float(xml_find_text(node, ".//transactionAmounts/transactionShares/value", ""), 0) or 0
        price = safe_float(xml_find_text(node, ".//transactionAmounts/transactionPricePerShare/value", ""), None)
        shares_owned = safe_float(xml_find_text(node, ".//postTransactionAmounts/sharesOwnedFollowingTransaction/value", ""), None)
        ownership = xml_find_text(node, ".//ownershipNature/directOrIndirectOwnership/value", "")

        transaction_label, signal = classify_transaction(code, acquired_disposed)
        value = shares * price if price is not None else None

        if shares <= 0 and value is None:
            continue

        transactions.append(
            {
                "ticker": issuer_symbol or clean_symbol(filing.get("ticker")),
                "company": issuer_name or filing.get("company", ""),
                "cik": filing.get("cik"),
                "form": filing.get("form", "4"),
                "accession": filing.get("accession"),
                "filing_date": filing.get("filing_date"),
                "report_date": filing.get("report_date"),
                "date": transaction_date or filing.get("report_date") or filing.get("filing_date"),
                "transaction_date": transaction_date,
                "transaction_code": code,
                "transaction": transaction_label,
                "signal": signal,
                "acquired_disposed": acquired_disposed,
                "shares": round(shares, 2),
                "price": round(price, 4) if price is not None else None,
                "value": round(value, 2) if value is not None else None,
                "shares_owned_after": round(shares_owned, 2) if shares_owned is not None else None,
                "ownership": ownership,
                "insider_name": owner_info["insider_name"],
                "insider": owner_info["insider_name"],
                "role": owner_info["role"],
                "source": "SEC Form 4",
                "url": build_filing_url(filing),
            }
        )

    return transactions


def fetch_form4_transactions_for_filing(filing: dict) -> list[dict]:
    url = build_filing_url(filing)

    try:
        xml_text = fetch_text(url)
    except Exception:
        return []

    return parse_form4_xml(xml_text, filing)


def dedupe_trades(trades: list[dict]) -> list[dict]:
    seen = set()
    deduped = []

    for trade in trades:
        key = (
            clean_symbol(trade.get("ticker")),
            trade.get("accession"),
            trade.get("insider_name"),
            trade.get("transaction_code"),
            trade.get("date"),
            trade.get("shares"),
            trade.get("price"),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(trade)

    return deduped


def sort_trades(trades: list[dict]) -> list[dict]:
    return sorted(
        trades,
        key=lambda trade: (
            str(trade.get("filing_date") or ""),
            safe_float(trade.get("value"), 0) or 0,
        ),
        reverse=True,
    )


def load_cached_trades() -> list[dict] | None:
    payload = read_json_file(CACHE_FILE, {})

    if not isinstance(payload, dict):
        return None

    cached_at = safe_float(payload.get("cached_at"), 0) or 0

    if utc_now_ts() - cached_at > CACHE_TTL_SECONDS:
        return None

    trades = payload.get("trades")

    if isinstance(trades, list):
        return trades

    return None


def write_trade_cache(trades: list[dict]) -> None:
    tickers = sorted({clean_symbol(trade.get("ticker")) for trade in trades if trade.get("ticker")})

    write_json_file(
        CACHE_FILE,
        {
            "cached_at": utc_now_ts(),
            "cached_at_iso": iso_now(),
            "source": "SEC Form 4",
            "tickers": tickers,
            "records": len(trades),
            "trades": trades,
        },
    )


def fetch_live_insider_trades(symbols: list[str] | None = None, force_refresh_ciks: bool = False) -> list[dict]:
    if symbols is None:
        symbols = get_watchlist_symbols()

    all_trades = []

    for symbol in symbols[:MAX_TICKERS]:
        ticker = clean_symbol(symbol)

        if not ticker:
            continue

        filings = get_recent_form4_filings(ticker, force_refresh=force_refresh_ciks)

        for filing in filings:
            all_trades.extend(fetch_form4_transactions_for_filing(filing))

    return sort_trades(dedupe_trades(all_trades))


def get_insider_trades(force_refresh: bool = False, symbols: list[str] | None = None) -> list[dict]:
    """
    Main public function used by /insiders and scoring.

    Default behavior:
    - Use cache if fresh.
    - Refresh from current SEC Form 4 filings when requested or cache is stale.
    - Never raise to callers; returns [] if SEC is unavailable.
    """
    if not force_refresh:
        cached = load_cached_trades()

        if cached is not None:
            return cached

    try:
        trades = fetch_live_insider_trades(symbols=symbols)
    except Exception:
        cached_payload = read_json_file(CACHE_FILE, {})
        cached_trades = cached_payload.get("trades", []) if isinstance(cached_payload, dict) else []
        return cached_trades if isinstance(cached_trades, list) else []

    write_trade_cache(trades)
    return trades


def get_insider_trades_for_symbol(ticker: str, force_refresh: bool = False) -> list[dict]:
    symbol = clean_symbol(ticker)

    if not symbol:
        return []

    if force_refresh:
        return get_insider_trades(force_refresh=True, symbols=[symbol])

    trades = get_insider_trades(force_refresh=False)

    filtered = [
        trade
        for trade in trades
        if clean_symbol(trade.get("ticker")) == symbol
    ]

    if filtered:
        return filtered

    return get_insider_trades(force_refresh=True, symbols=[symbol])


# Backward-compatible aliases
get_live_insider_trades = get_insider_trades
refresh_insider_trades = lambda: get_insider_trades(force_refresh=True)