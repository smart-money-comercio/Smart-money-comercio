import os
import re
import requests
from dotenv import load_dotenv
from openai import OpenAI

from src.sec.sec_data import get_sec_filings, SEC_USER_AGENT

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def clean_filing_text(raw_text):
    text = re.sub(r"<script.*?</script>", " ", raw_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&quot;", '"')
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def fetch_filing_text(url):
    response = requests.get(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT
        },
        timeout=45
    )

    response.raise_for_status()

    return clean_filing_text(response.text)

def normalize_form_type(form_filter):
    if not form_filter:
        return None

    form_filter = form_filter.upper().replace(" ", "")

    aliases = {
        "10K": "10-K",
        "10Q": "10-Q",
        "8K": "8-K",
        "FORM4": "4"
    }

    return aliases.get(form_filter, form_filter)


def find_filing(ticker, form_filter=None):
    data = get_sec_filings(ticker, limit=100)

    if not data["found"]:
        return None, None

    filings = data["filings"]

    if form_filter:
        form_filter = normalize_form_type(form_filter)

        for filing in filings:
            filing_form = filing["form"].upper()

            if (
                filing_form == form_filter
                or filing_form.startswith(form_filter + "/")
            ):
                return data, filing

        return data, None

    return data, filings[0] if filings else None

def summarize_sec_filing(ticker, form_filter=None):
    data, filing = find_filing(ticker, form_filter)

    if not data:
        return {
            "found": False,
            "error": "Company not found"
        }

    if not filing:
        return {
            "found": False,
            "error": f"No filing found for form type: {form_filter}"
        }

    filing_text = fetch_filing_text(filing["url"])

    # Keep the request controlled so the summary stays fast and affordable.
    filing_text = filing_text[:18000]

    prompt = f"""
You are the SEC Filing Analyst for Smart Money AI.

Summarize this SEC filing in plain English for an individual investor.

Ticker: {data['ticker']}
Company: {data['company_name']}
Form: {filing['form']}
Filed: {filing['filing_date']}
Report Date: {filing['report_date']}

Filing text:
{filing_text}

Return a concise, user-friendly summary with these sections:

1. What was filed
2. Why it matters
3. Key business or financial highlights
4. Risks or red flags
5. Smart Money AI takeaway

Use simple language.
Avoid legal jargon.
Maximum 250 words.
End with: "This is research, not financial advice."
"""

    response = client.responses.create(
        model="gpt-5",
        input=prompt
    )

    return {
        "found": True,
        "ticker": data["ticker"],
        "company_name": data["company_name"],
        "form": filing["form"],
        "filing_date": filing["filing_date"],
        "report_date": filing["report_date"],
        "url": filing["url"],
        "summary": response.output_text
    }