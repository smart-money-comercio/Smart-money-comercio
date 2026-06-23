import os
import requests
from dotenv import load_dotenv

load_dotenv()

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "SmartMoneyAI/1.0 contact@example.com"
)

HEADERS = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}


def get_company_tickers():
    url = "https://www.sec.gov/files/company_tickers.json"

    response = requests.get(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT
        },
        timeout=30
    )

    response.raise_for_status()
    return response.json()


def get_cik_for_ticker(ticker):
    ticker = ticker.upper()
    companies = get_company_tickers()

    for item in companies.values():
        if item["ticker"].upper() == ticker:
            return str(item["cik_str"]).zfill(10), item["title"]

    return None, None


def get_sec_filings(ticker, limit=10):
    cik, company_name = get_cik_for_ticker(ticker)

    if not cik:
        return {
            "found": False,
            "ticker": ticker.upper(),
            "error": "Ticker not found in SEC company ticker list"
        }

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()
    data = response.json()

    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])

    filings = []

    for i in range(min(limit, len(forms))):
        accession = accession_numbers[i]
        accession_clean = accession.replace("-", "")
        primary_document = primary_documents[i]

        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession_clean}/{primary_document}"
        )

        filings.append({
            "form": forms[i],
            "filing_date": filing_dates[i],
            "report_date": report_dates[i] if i < len(report_dates) else "N/A",
            "accession_number": accession,
            "document": primary_document,
            "url": filing_url
        })

    return {
        "found": True,
        "ticker": ticker.upper(),
        "company_name": company_name,
        "cik": cik,
        "filings": filings
    }