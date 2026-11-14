"""Read a bounded sample of original House periodic transaction reports."""

import csv
from datetime import timedelta
from http.client import HTTPException
from io import BytesIO, StringIO
import re
from urllib.error import HTTPError
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.congress import congress_data as congress
from src.intelligence.transaction_disclosures import MONEY_RANGE, congress_fields


HOST = "https://disclosures-clerk.house.gov/public_disc/"
INDEX_DAYS = 30
DOCUMENTS_PER_REFRESH = 10
MAX_PDF_BYTES = 2_000_000
MAX_INDEX_BYTES = 4_000_000
DATE = r"\d{1,2}/\d{1,2}/20\d{2}"
LAYOUT_AMOUNT = r"\$[\d,]+\s*[-–—]\s*\$[\d,]+"
TABLE_ROW = re.compile(
    r"^\s*(?:(?P<owner>SP|JT|DC|SELF)\s{2,})?(?P<asset>.+?)\s{2,}"
    r"(?P<action>P|S\s*\(partial\)|S|E)\s{2,}(?P<traded>" + DATE + r")\s{2,}"
    r"(?:(?P<notified>" + DATE + r")\s{2,})?(?P<amount>" + LAYOUT_AMOUNT + r"|\$[\d,]+\s*[-–—]|\$[\d,]+\s*or more)(?:\s{2,}.*|\s*)$", re.I,
)
STOCK = re.compile(r"^(?P<name>.+?)\s+\((?P<ticker>[A-Z][A-Z0-9.-]{0,9})\)\s*\[ST\]$", re.I)
CORPORATE_OR_AUTOMATIC = re.compile(r"\b(?:merger|corporate action|cash in lieu|mandatory|automatic|reinvest\w*|exercise[ds]?|"
                                     r"assignment|tender|conversion|options?|stock split|gift|transferred|dividend)\b", re.I)


def index_url(year):
    return f"{HOST}financial-pdfs/{year}FD.zip"


def document_url(year, document):
    return f"{HOST}ptr-pdfs/{year}/{document}.pdf"


def index_rows(data, year, today):
    if len(data) > MAX_INDEX_BYTES:
        raise ValueError("House Clerk index exceeds its size limit")
    try:
        with ZipFile(BytesIO(data)) as archive:
            files = [item for item in archive.infolist() if item.filename.casefold() == f"{year}fd.txt"]
            if len(files) != 1 or files[0].file_size > MAX_INDEX_BYTES:
                raise ValueError("House Clerk filing index unavailable")
            with archive.open(files[0]) as stream:
                raw = stream.read(MAX_INDEX_BYTES + 1)
    except (BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError("Unreadable House Clerk filing archive") from error
    if len(raw) > MAX_INDEX_BYTES:
        raise ValueError("House Clerk filing table exceeds its size limit")
    rows = csv.DictReader(StringIO(raw.decode("utf-8-sig", errors="replace")), delimiter="\t")
    required = {"First", "Last", "FilingType", "FilingDate", "DocID"}
    if not required <= set(rows.fieldnames or []):
        raise ValueError("Unrecognized House Clerk index columns")
    results = []
    for row in rows:
        if row["FilingType"] != "P" or not re.fullmatch(r"[0-9]{5,12}", row["DocID"] or ""):
            continue
        filed = congress.parse_date_value(row["FilingDate"]).date()
        if not today - timedelta(days=INDEX_DAYS) <= filed <= today:
            continue
        name = " ".join(filter(None, (row["First"], row["Last"]))).strip()
        if name:
            results.append({"name": name, "filed": filed.isoformat(), "doc_id": row["DocID"], "year": year,
                            "district": (row.get("StateDst") or "").strip().upper()})
    return results


def words(value):
    return set(re.findall(r"[\w'-]+", value.casefold())) - {"hon", "mr", "mrs", "ms", "dr", "rep"}


def verified_report(text, entry):
    # Modern reports have a printed filing ID. The index supplies the filed date.
    report = re.search(r"\bFiling ID\s*#\s*([0-9]+)\b", text, re.I)
    name = re.search(r"^\s*Name:\s*(.+?)\s*$", text, re.I | re.M)
    status = re.search(r"^\s*Status:\s*Member\b", text, re.I | re.M)
    district = re.search(r"^\s*State\s*/\s*District:\s*([A-Z]{2}-?[0-9]{2})\b", text, re.I | re.M)
    if (not report or report[1] != entry["doc_id"] or not name or not status
            or not words(entry["name"]) <= words(name[1])):
        raise ValueError("House Clerk document does not match the index")
    if district and entry["district"] and district[1].upper().replace("-", "") != entry["district"].replace("-", ""):
        raise ValueError("House Clerk district disagrees with the report")
    return " ".join(name[1].split()).removeprefix("Hon. ")


def trade_blocks(text):
    start, tail = None, []
    for line in text.splitlines():
        row = TABLE_ROW.match(line)
        if row:
            if start is not None:
                yield start, tail
            start, tail = row, []
        elif start is not None:
            if re.match(r"\s*(?:\* For the complete list|Investment Vehicle Details|Initial Public Offerings|Digitally Signed|I CERTIFY|Filing ID)", line, re.I):
                yield start, tail
                start, tail = None, []
            else:
                tail.append(line)
    if start is not None:
        yield start, tail


def trade_row(row, tail, filer, entry):
    asset, amount = row["asset"], row["amount"]
    details = []
    for line in tail:
        clean = line.strip()
        if not clean:
            continue
        # A wrapped cell can continue before the notes and status on that row.
        columns = re.split(r"\s{2,}", clean)
        if not details and amount.rstrip().endswith(("-", "–", "—")) and re.fullmatch(r"\$[\d,]+", columns[-1]):
            amount += " " + columns.pop()
        if not details and "[" not in asset and columns and not re.match(r"(?:Filing Status|Description|Subholding|Comments):", columns[0], re.I):
            if re.fullmatch(r"[\w .,()'&/-]{1,100}(?:\s+\[[A-Z]{1,4}\])?", columns[0]):
                asset += " " + columns.pop(0)
        details.extend(columns)
    stock = STOCK.fullmatch(" ".join(asset.split()))
    extra = " ".join(details)
    statuses = re.findall(r"\bFiling Status:\s*(\w+)", extra, re.I)
    if (not stock or not MONEY_RANGE.fullmatch(amount) or row["action"].upper() == "E"
            or [value.casefold() for value in statuses] != ["new"]
            or CORPORATE_OR_AUTOMATIC.search(stock["name"] + " " + extra)):
        return None
    ticker = congress.clean_ticker(stock["ticker"].upper())
    filed = congress.parse_date_value(entry["filed"]).date()
    traded = congress.parse_date_value(row["traded"]).date()
    owner = {"SP": "spouse", "JT": "joint", "DC": "dependent child", "SELF": "self", "": "self"}[(row["owner"] or "").upper()]
    if not ticker or not 0 <= (filed - traded).days <= congress.MAX_TRADE_AGE.days:
        return None
    trade = {"ticker": ticker, "politician": filer, "chamber": "House", "owner": owner,
             "transaction": "Purchase" if row["action"].upper() == "P" else "Sale",
             "transaction_date": traded.isoformat(), "disclosure_date": entry["filed"],
             "amount_range": amount, "asset_type": "ST", "sector": stock["name"][:180],
             "source": congress.HOUSE_CLERK_PROVIDER, "source_url": document_url(entry["year"], entry["doc_id"]),
             "signal": "Original House filing", "committee_relevance": "Unknown"}
    try:
        trade["amount_range"] = congress_fields(trade)["amount_range"]
    except (ValueError, TypeError):
        return None
    return trade


def document_rows(raw, entry):
    if len(raw) > MAX_PDF_BYTES or not raw.startswith(b"%PDF-"):
        raise ValueError("Unusable House Clerk report response")
    try:
        pdf = PdfReader(BytesIO(raw), strict=False)
        if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 12:
            raise ValueError("House Clerk report outside the automated reading limits")
        text = "\n".join(page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False) or "" for page in pdf.pages)
    except (PdfReadError, NotImplementedError, RecursionError) as error:
        raise ValueError("House Clerk PDF text unavailable") from error
    if len(text) > 150_000:
        raise ValueError("House Clerk report text exceeds its size limit")
    name = verified_report(text, entry)
    blocks = list(trade_blocks(text))
    if not blocks:
        raise ValueError("House Clerk transaction table is unreadable")
    return [trade for row, tail in blocks if (trade := trade_row(row, tail, name, entry))]


def read_recent(reader, today, seen, cursor):
    years = {today.year, (today - timedelta(days=INDEX_DAYS)).year}
    entries = {}
    for year in sorted(years, reverse=True):
        try:
            data = reader.bytes(index_url(year), same_host=True, max_bytes=MAX_INDEX_BYTES)
        except HTTPError as error:
            if error.code == 404 and year == today.year and len(years) > 1:
                continue
            raise
        for entry in index_rows(data, year, today):
            entries[document_url(year, entry["doc_id"])] = entry
    ordered = sorted((url for url in entries if url not in seen), key=lambda url: (entries[url]["filed"], entries[url]["doc_id"]), reverse=True)
    if not ordered:
        return [], {}, 0, 0, 0, None
    start = cursor % len(ordered)
    batch = (ordered[start:] + ordered[:start])[:DOCUMENTS_PER_REFRESH]
    rows, reviewed, failures = [], {}, 0
    blocked = None
    for url in batch:
        try:
            entry = entries[url]
            rows.extend(document_rows(reader.bytes(url, same_host=True, max_bytes=MAX_PDF_BYTES), entry))
            reviewed[url] = entry["filed"]
        except (OSError, HTTPException, ValueError, TypeError) as error:
            failures += 1
            if isinstance(error, HTTPError) and error.code in {401, 402, 403, 429}:
                blocked = error
                break
    return rows, reviewed, failures, len(ordered) - len(reviewed), start + failures, blocked
