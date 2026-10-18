"""Offline PDF extraction and explicit, reviewed claim imports. No model/API calls."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import re

from src.intelligence.research_store import ResearchError, import_document, validate_document


MAX_SOURCE_BYTES = 50 * 1024 * 1024
ACCOUNT_PATTERN = re.compile(r"\b(?:dividends received|trades made|account\s*(?:number|#)|your portfolio balance)\b", re.I)
QUARTER_RANGE = re.compile(
    r"\b(January|April|July|October)\s+1\s*[-–—]\s*"
    r"(March|June|September|December)\s+(?:30|31),?\s+(20\d{2})", re.I,
)
MONTH_QUARTER = {"january": 1, "april": 2, "july": 3, "october": 4}


def extract_pdf(path: Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".pdf" or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ResearchError("Expected a PDF source no larger than 50 MiB.")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ResearchError("PDF extraction needs pypdf. Run: python -m pip install -r requirements.txt") from None
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_SOURCE_BYTES:
            raise ResearchError("Expected a PDF source no larger than 50 MiB.")
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 500:
            raise ResearchError("Encrypted or oversized PDFs are not supported.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except ResearchError:
        raise
    except Exception:
        raise ResearchError("The PDF could not be read. No research data was changed.") from None
    if not any(text.strip() for text in pages):
        raise ResearchError("This PDF has no extractable text; OCR is required before import.")
    text = "\n".join(pages)
    if ACCOUNT_PATTERN.search(text):
        raise ResearchError("Private account documents are outside the public-research importer.")
    partial = "news for you" in text.lower() and ("more like this" in text.lower() or "trending now" in text.lower())
    return {"sha256": hashlib.sha256(raw).hexdigest(), "page_count": len(pages),
            "pages": pages, "completeness": "partial" if partial else "full"}


def find_period_conflicts(pages: list[str], declared_period: str | None) -> list[dict]:
    if not declared_period:
        return []
    expected = re.fullmatch(r"Q([1-4]) (20\d{2})", declared_period)
    if not expected:
        raise ResearchError("Expected a quarter such as Q3 2026.")
    expected_pair = (int(expected[1]), int(expected[2]))
    issues = []
    for index, text in enumerate(pages, 1):
        # Dates in source footnotes are common: require an explicit performance-period range
        # or an asset-return caption, not an arbitrary mention of an earlier quarter.
        pairs = [(MONTH_QUARTER[m[1].lower()], int(m[3])) for m in QUARTER_RANGE.finditer(text)]
        if re.search(r"asset.class returns|return ranges|portfolio.*Q[1-4]", text, re.I):
            pairs += [(int(q), int(year)) for q, year in re.findall(r"\bQ([1-4])\s+(20\d{2})\b", text)]
        if any(pair != expected_pair for pair in pairs):
            issues.append({"code": "period_conflict", "pages": [index]})
    return issues


def import_manifest(manifest: Path, source_pdf: Path | None = None) -> dict:
    try:
        if Path(manifest).stat().st_size > 2 * 1024 * 1024:
            raise ResearchError("Research manifests must be no larger than 2 MiB.")
        value = json.loads(Path(manifest).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ResearchError("The research manifest could not be read.") from None
    # Validate the public-only schema before processing any supplied PDF.
    document = validate_document(value)
    if source_pdf is not None:
        pdf = extract_pdf(source_pdf)
        if pdf["sha256"] != document["source"]["sha256"] or pdf["page_count"] != document["source"]["page_count"]:
            raise ResearchError("The PDF does not match this manifest's content hash and page count.")
        if pdf["completeness"] == "partial":
            document["source"]["completeness"] = "partial"
        document["issues"] += find_period_conflicts(pdf["pages"], document["source"].get("period"))
    return import_document(document)


def create_draft(source_pdf: Path, output: Path, period: str | None = None) -> dict:
    """The draft contains raw source text and is always private/unreviewed."""
    pdf = extract_pdf(source_pdf)
    output = Path(output)
    if output.exists():
        raise ResearchError("Draft destination already exists; choose a new filename.")
    output.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": 1, "visibility": "private_draft", "reviewed": False,
        "source": {"sha256": pdf["sha256"], "page_count": pdf["page_count"],
                   "completeness": pdf["completeness"], "period": period},
        "issues": find_period_conflicts(pdf["pages"], period), "claims": [],
        "extracted_pages": [{"page": n, "text": text} for n, text in enumerate(pdf["pages"], 1)],
    }
    # Exclusive creation never overwrites a prior draft. No source text is logged.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return {"pages": pdf["page_count"], "completeness": pdf["completeness"], "issues": len(value["issues"])}
