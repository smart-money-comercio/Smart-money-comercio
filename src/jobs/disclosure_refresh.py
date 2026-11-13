"""Bounded background refresh of SEC Form 4 and congressional disclosures."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from src.congress import congress_data as congress
from src.insiders import insider_data as sec
from src.intelligence import sec_contact, transaction_cache as cache
from src.intelligence.transaction_disclosures import NY, scope, scope_observations
from src.scoring.watchlist import WATCHLIST


CHECK_SECONDS = 900
SEC_BATCH = 8
SEC_WINDOW_DAYS = 7
SEC_SOURCE = "SEC Form 4"
FMP_SOURCE = "FMP House/Senate congressional disclosure endpoints"
STOCKWATCHER_SOURCE = "House/Senate Stock Watcher public JSON datasets"
CHAMBERS = ("House", "Senate")
LOG = logging.getLogger(__name__)


class BudgetExhausted(ValueError):
    pass


class Reader:
    def __init__(self, seconds, requests, user_agent, interval=0):
        self.deadline = time.monotonic() + seconds
        self.remaining = requests
        self.user_agent = user_agent
        self.interval = interval
        self.next_request = 0

    def text(self, url):
        delay = max(0, self.next_request - time.monotonic())
        if not self.remaining or time.monotonic() + delay >= self.deadline:
            raise BudgetExhausted("Request budget reached")
        if delay:
            time.sleep(delay)
        self.remaining -= 1
        self.next_request = time.monotonic() + self.interval
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json, application/xml, text/plain, */*"})
        with urlopen(request, timeout=max(.1, min(4, self.deadline - time.monotonic()))) as response:
            body = bytearray()
            while len(body) <= cache.MAX_BYTES:
                if time.monotonic() >= self.deadline:
                    raise BudgetExhausted("Request budget reached")
                chunk = response.read1(min(131072, cache.MAX_BYTES + 1 - len(body)))
                if not chunk:
                    return body.decode("utf-8-sig")
                body.extend(chunk)
        raise ValueError("Disclosure response exceeds its size limit")

    def json(self, url):
        return json.loads(self.text(url))


def retry_delay(error, now=None):
    if isinstance(error, HTTPError) and error.code in {401, 402, 403, 429}:
        delay = 3600 if error.code == 429 else 21600
        value = error.headers.get("Retry-After") if error.headers is not None else None
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            try:
                retry = parsedate_to_datetime(value)
                seconds = (retry - (now or datetime.now(timezone.utc))).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = delay
        return max(delay, min(86400, seconds))
    return 0


def error_reason(error):
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}"
    if isinstance(error, BudgetExhausted):
        return "Request budget reached"
    if isinstance(error, (URLError, OSError)):
        return "Source connection unavailable"
    return "Usable disclosure response unavailable"


def recent_filings(ticker, issuer, today, reader):
    payload = reader.json(sec.SUBMISSIONS_URL.format(cik=issuer["cik"]))
    envelope = payload.get("filings") if isinstance(payload, dict) else None
    recent = envelope.get("recent") if isinstance(envelope, dict) else None
    keys = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument")
    if (not isinstance(recent, dict) or any(not isinstance(recent.get(key), list) for key in keys)
            or len({len(recent[key]) for key in keys}) != 1):
        raise ValueError("Unrecognized SEC submissions response")
    if str(payload.get("cik", "")).zfill(10) != issuer["cik"]:
        raise ValueError("SEC submissions issuer does not match the request")
    earliest = (today - timedelta(days=SEC_WINDOW_DAYS - 1)).isoformat()
    latest = today.isoformat()
    return [row for row in sec.form4_filings(payload, ticker, issuer) if earliest <= row["filing_date"] <= latest]


def form4_rows(filing, reader):
    accession = filing["accession"]
    document = filing["primary_document"]
    if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) or not re.fullmatch(r"(?:xslF345X[0-9]+/)?[A-Za-z0-9_.-]+", document) or ".." in document:
        raise ValueError("Unrecognized SEC filing identifier")
    # The raw XML is beside the SEC stylesheet view. Some filings need the complete submission.
    primary = {**filing, "primary_document": document.rsplit("/", 1)[-1]}
    urls = (sec.build_filing_url(primary), sec.build_complete_submission_url(filing))
    for index, url in enumerate(urls):
        try:
            root = ET.fromstring(sec.extract_ownership_xml(reader.text(url)))
        except HTTPError as error:
            if error.code != 404 or index:
                raise
            continue
        except ET.ParseError:
            continue
        cik = sec.xml_find_text(root, ".//issuer/issuerCik")
        if (root.tag == "ownershipDocument" and cik.zfill(10) == filing["cik"]
                and sec.xml_find_text(root, "./documentType") == filing["form"]):
            return sec.form4_transactions(root, filing)
    raise ValueError("SEC ownership document could not be matched")


def refresh_sec(payload, now, cursor):
    agent = sec_contact.user_agent()
    if not agent:
        return None, cursor, 0, "limited", "Configure SEC_USER_AGENT for automatic Form 4 access"
    reader = Reader(seconds=24, requests=24, user_agent=agent, interval=.2)
    ticker_map = sec.load_company_ticker_map(reader=reader.json)
    tickers = {row["ticker"] for row in WATCHLIST if "ETF" not in row["category"].upper()}
    issuers = {}
    for ticker in sec.get_watchlist_symbols():
        issuer = ticker_map.get(ticker)
        if (ticker in tickers and isinstance(issuer, dict) and isinstance(issuer.get("cik"), str)
                and re.fullmatch(r"[0-9]{10}", issuer["cik"]) and int(issuer["cik"])):
            issuers.setdefault(issuer["cik"], (ticker, issuer))
    if not issuers:
        return None, cursor, 3600, "limited", "No tracked SEC issuer identifiers available"
    observations = scope_observations("sec", payload, now)
    previous = [row for row in cache.rows(payload) if isinstance(row.get("ticker"), str) and scope("sec", row)]
    known = {(scope("sec", row), row.get("accession")) for row in previous if isinstance(row.get("accession"), str)}
    today = now.astimezone(NY).date()
    current = now.timestamp()
    keys = list(issuers)
    due = keys[cursor % len(keys):] + keys[:cursor % len(keys)]
    due = [key for key in due if current - observations.get(key, {}).get("at", 0) >= sec.CACHE_TTL_SECONDS][:SEC_BATCH]
    added, checked = [], 0
    wait, reason = CHECK_SECONDS - 5, ""
    for key in due:
        ticker, issuer = issuers[key]
        cursor = (keys.index(key) + 1) % len(keys)
        try:
            filings = recent_filings(ticker, issuer, today, reader)
            for filing in filings:
                if (key, filing["accession"]) not in known:
                    added.extend(form4_rows(filing, reader))
                    known.add((key, filing["accession"]))
            observations[key] = {"at": current, "provider": SEC_SOURCE}
            checked += 1
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            reason = error_reason(error)
            delay = retry_delay(error, now)
            if delay or isinstance(error, BudgetExhausted):
                wait = delay or wait
                break
    covered = sum(current - observations.get(key, {}).get("at", 0) < sec.CACHE_TTL_SECONDS for key in keys)
    detail = f"{covered}/{len(keys)} issuers checked recently"
    if checked:
        detail += f"; {checked} updated, {len(added)} new transaction rows"
    if reason:
        detail += f"; {reason}"
    status = "pass" if covered == len(keys) and not reason else "limited"
    if not checked and not added:
        return None, cursor, wait, status, detail
    trades = sec.sort_trades(sec.dedupe_trades(added + previous))[:cache.MAX_ROWS]
    # A partial filing read can be saved for the next batch without advancing that issuer's clock.
    last_success = max((value["at"] for value in observations.values()), default=0)
    result = {"cached_at": last_success, "cached_at_iso": datetime.fromtimestamp(last_success, timezone.utc).isoformat(),
              "source": SEC_SOURCE, "records": len(trades), "tickers": sorted({row["ticker"] for row in trades}),
              "trades": trades, "observations": observations}
    return result, cursor, wait, status, detail


def fmp_rows(chamber, reader, today):
    endpoint = congress.HOUSE_LATEST_ENDPOINT if chamber == "House" else congress.SENATE_LATEST_ENDPOINT
    rows = []
    for page in range(max(1, min(congress.MAX_PAGES, 2))):
        try:
            payload = reader.json(congress.build_fmp_url(endpoint, page))
        except (OSError, ValueError, TypeError) as error:
            if any(congress.recently_filed(row, today) for row in rows):
                return rows, error
            raise
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ValueError("Unrecognized congressional disclosure response")
        rows.extend(trade for row in payload if (trade := congress.normalize_fmp_trade(row, chamber)))
        if len(payload) < congress.PAGE_LIMIT:
            break
    return rows, None


def stockwatcher_rows(chamber, reader):
    urls = congress.HOUSE_STOCKWATCHER_URLS if chamber == "House" else congress.SENATE_STOCKWATCHER_URLS
    for index, url in enumerate(urls):
        try:
            payload = reader.json(url)
            rows = congress.normalize_stockwatcher_payload(payload, chamber)
            if rows:
                return rows
        except (OSError, ValueError, TypeError) as error:
            if index == len(urls) - 1 or retry_delay(error) or isinstance(error, BudgetExhausted):
                raise
    return []


def chamber_rows(chamber, configured, reader, today):
    page_error = None
    if configured in {"auto", "fmp"} and congress.get_fmp_api_key():
        (rows, page_error), provider = fmp_rows(chamber, reader, today), "FMP"
    elif configured in {"auto", "stockwatcher", "stock_watcher"}:
        rows, provider = stockwatcher_rows(chamber, reader), "Stock Watcher"
    else:
        return None, "FMP_API_KEY required" if configured == "fmp" else "Unknown congressional provider"
    dated = [{**row, "chamber": chamber} for row in rows if congress.recently_filed(row, today)]
    if not dated:
        reason = f"{provider} has no current dated disclosures"
        if configured == "auto" and provider == "Stock Watcher":
            reason += "; configure FMP_API_KEY for the current feed"
        return None, reason
    return (dated, provider, page_error), ""


def refresh_chamber(payload, now, cursor, chamber, force):
    configured = congress.get_provider()
    if configured == "fmp" and not congress.get_fmp_api_key():
        return None, cursor, 0, "limited", "FMP_API_KEY required for the configured provider"
    observations = scope_observations("congress", payload, now)
    current = now.timestamp()
    today = now.astimezone(NY).date()
    prior = observations.get(chamber, {})
    wait = CHECK_SECONDS - 5
    if not force and current - prior.get("at", 0) < congress.CACHE_TTL_SECONDS:
        return None, cursor, wait, "pass", "Recent dated disclosures available"
    reader = Reader(seconds=9, requests=2, user_agent="SmartMoneyAI/1.0")
    try:
        result, reason = chamber_rows(chamber, configured, reader, today)
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        reason = error_reason(error)
        if isinstance(error, HTTPError) and error.code == 402 and configured in {"auto", "fmp"} and congress.get_fmp_api_key():
            reason += " from FMP (endpoint access denied)"
        return None, cursor, max(3600, retry_delay(error, now)), "limited", reason
    if not result:
        return None, cursor, 3600, "limited", reason

    incoming, provider, page_error = result
    trades = cache.rows(payload)
    earlier = [row for row in trades if scope("congress", row) == chamber and prior.get("provider") == provider
               and congress.recently_filed(row, today)]
    other = [row for row in trades if scope("congress", row) != chamber]
    ordered = congress.sort_trades(incoming + earlier)
    ordered.sort(key=lambda row: congress.parse_date_value(row.get("disclosure_date")), reverse=True)
    trades = other + ordered[:max(300, congress.STOCKWATCHER_MAX_RECORDS)]
    observations[chamber] = {"at": current, "provider": provider}
    source = FMP_SOURCE if any(value["provider"] == "FMP" for value in observations.values()) else STOCKWATCHER_SOURCE
    status, detail = "pass", "Dated disclosures updated"
    if page_error is not None:
        wait = max(3600, congress.CACHE_TTL_SECONDS, retry_delay(page_error, now))
        status, detail = "limited", f"Dated disclosures updated; additional FMP page {error_reason(page_error)}"
    return {"fetched_at": current, "source": source, "provider": configured, "observations": observations,
            "trades": trades[:cache.MAX_ROWS]}, cursor, wait, status, detail


def refresh_source(path, refresh, now, *, force=False, scope=""):
    started = now.timestamp()
    cursor, status, detail = cache.reserve(path, started, force=force, scope=scope)
    if cursor is None:
        return status, detail
    try:
        payload, revision = cache.read(path)
        snapshot, cursor, wait, status, detail = refresh(payload, now, cursor)
        if snapshot is not None and not cache.publish(path, snapshot, revision):
            status = "limited"
            detail = "Newer cache saved during refresh; automatic check will retry"
    except Exception as error:
        wait, status, detail = max(3600, retry_delay(error, now)), "limited", error_reason(error)
    cache.finish(path, started, started + wait, cursor, status, detail, scope=scope)
    return status, detail


def refresh_congress(now, *, force=False):
    path = congress.CACHE_FILE
    problems = []
    for chamber in CHAMBERS:
        try:
            status, detail = refresh_source(path, lambda payload, now, cursor: refresh_chamber(payload, now, cursor, chamber, force),
                                            now, force=force, scope=chamber)
        except (OSError, ValueError, sqlite3.Error) as error:
            status, detail = "limited", f"Refresh state unavailable ({type(error).__name__})"
        if status == "limited":
            problems.append(detail if detail.startswith(chamber + " ") else f"{chamber} {detail}")
    observations = scope_observations("congress", cache.read(path)[0], now)
    covered = sum(now.timestamp() - value["at"] <= congress.CACHE_MAX_AGE.total_seconds() for value in observations.values())
    detail = "; ".join([f"{covered}/2 chambers with current dated coverage", *problems])
    return ("pass" if covered == len(CHAMBERS) and not problems else "limited"), detail


def refresh_congress_now():
    return refresh_congress(datetime.now(timezone.utc), force=True)


def refresh_due(now=None):
    now = now or datetime.now(timezone.utc)
    checks, details = [], []
    for label, refresh in ((SEC_SOURCE, lambda: refresh_source(sec.CACHE_FILE, refresh_sec, now)), ("Congress", lambda: refresh_congress(now))):
        try:
            status, detail = refresh()
        except Exception as error:
            status, detail = "limited", f"Refresh state unavailable ({type(error).__name__})"
        checks.append(status)
        details.append(f"{label} — {detail}")
    return {"status": "limited" if "limited" in checks else "pass", "detail": " | ".join(details)}


async def disclosure_refresh_job(context):
    result = await asyncio.to_thread(refresh_due)
    LOG.info("Disclosure refresh %s — %s", result["status"], result["detail"])


def schedule_disclosure_refresh(app):
    if app.job_queue is None:
        LOG.warning("Background disclosure refresh unavailable because JobQueue is missing")
        return
    app.job_queue.run_repeating(disclosure_refresh_job, interval=CHECK_SECONDS, first=30, name="disclosure-refresh",
                                job_kwargs={"max_instances": 1, "coalesce": True, "misfire_grace_time": 180})
    print("Disclosure refresh scheduled. First check in 30 seconds, then every 15 minutes.")
