# Dated document research

This feature adds sourced background to `/report`, `/tradeplan SYMBOL`, and the active `/scorecard SYMBOL` command. Use `/research` or `/research MSFT` to inspect eligible claims, expiry, source issues, and cached market confirmation.

The bundled source contains four reviewed paraphrases from the public Empower Q3 2026 market outlook. Its publication date is unknown; September 30 is its reporting-period date, and October 16 is the date this copy became available to this project. Page 18 has conflicting Q2/Q3 period labels and supplies no active claim. The reviewed background expires December 29, 2026 unless replaced by newer reviewed evidence.

Score Risk, Setup Risk, numerical scores, and ranking weights retain their existing definitions. Historical research opinions do not cast live theme or risk votes. This release adds explanations, provenance, and freshness checks.

## Setup and verification

From the repository:

```powershell
python -m pip install -r requirements.txt
python scripts/check_research_integration.py
python scripts/check_report_consistency.py
python scripts/import_research.py --seed
```

`pypdf` is used only for PDF import. Normal report generation uses standard-library code and ready JSON records, with no new model calls or API keys. If pypdf is absent, the research checks explicitly skip the four PDF extraction cases; install requirements and rerun to exercise them.

After the normal Git push and server update, verify in Telegram:

```text
/research
/research MSFT
/reportcheck
/report
/tradeplan MSFT
/scorecard MSFT
```

Look for a sourced, dated research line in Theme Read, Market Backdrop in the single-company reports, and Research Context: PASS in the quality card. A PASS validates output structure; it does not certify the research's investment merit. `/research` shows whether evidence is ACTIVE, INACTIVE, DISABLED, or UNAVAILABLE.

## Importing another PDF

PDF text extraction deliberately creates a private, unreviewed draft. It does not invent investment conclusions from a headline or automatically publish extracted text.

```powershell
python scripts/import_research.py --draft "C:\Users\josej\Downloads\market_outlook.pdf" --period "Q4 2026"
```

Drafts go under the ignored `data/research/drafts` directory. Prepare a separate, reviewed JSON manifest using `resources/research/empower_q3_2026.json` as the schema example. Paraphrase selected relevant findings, supply the exact source hash and page count from the draft, and remove all raw text and contact/account details. Set each claim's own data-as-of and expiry dates. Do not mark an unconfirmed forecast as an observation. Keep newsletter previews partial.

Import and bind the manifest to the exact source bytes:

```powershell
python scripts/import_research.py "C:\path\reviewed_manifest.json" --source "C:\path\market_outlook.pdf"
```

An existing reviewed manifest can also be imported without re-extracting its PDF. The source hash and page references remain mandatory. Source publication dates can be null when unknown. New runtime records are known only from their import time, regardless of an earlier date supplied in the manifest. Research facts are source-reported until independently corroborated; the importer does not independently verify the publisher's claims.

Runtime imports are stored in `data/research/public_store.json` and are intentionally ignored by Git. To distribute a new sanitized, reviewed public source with the bot, put its manifest under `resources/research/` and include that exact file in the normal reviewed commit. Raw PDFs, draft files, and private account documents do not belong there.

## Source handling

- Full reports, newsletters, research notes, and article previews have distinct source types.
- Partial previews supply no active claims, even if they include plausible headlines.
- Claims touching a page with a period conflict are withheld; unaffected pages remain available.
- Facts/observations, estimates, opinions, and forecasts retain their type and date.
- Quarterly research has a maximum 90-day review horizon. Other sources and forecasts have a maximum 14-day horizon.
- Duplicate content hashes and event IDs do not multiply signal weight.
- Expired, ambiguous, contradicted, superseded, or not-yet-available claims are excluded from active explanations.
- Personal account documents are rejected by this public-only importer. It does not calculate returns, import holdings, or publish private income figures.

## Market observations

The backdrop reads the existing Morning Brief cache and displays the cache timestamp explicitly. These are cached daily/last-session observations, not a new streaming feed. TLT is labeled a bond-price proxy. No Treasury yield is inferred from TLT; direct yields remain unverified in this release. Missing, non-finite, future-dated, and older-than-six-hour caches are labeled unavailable or stale.

The daily report attaches research after the existing summary rewrites and keeps the Theme Read line budget. If the final report has no space within its character limit, it omits the addition and does not claim Document Research was used. Full eligible research remains accessible with `/research`.

## Storage and operation

Reads perform no writes or network calls. Runtime imports use a single-writer lock and atomic replacement. Failed writes preserve the prior file. Malformed stored data fails closed with UNAVAILABLE rather than silently reporting an all-clear market assessment.

Optional environment settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `RESEARCH_ENABLED` | `1` | Set to `0` to disable research explanations. |
| `RESEARCH_STORE_FILE` | `data/research/public_store.json` under the project root | Runtime reviewed public records. |
| `RESEARCH_SEED_DIR` | `resources/research` under the project root | Versioned, reviewed public manifests. |

The existing source refresh job validates the cache-only research context, and deployment preflight runs the research regression checks. This release does not change quarterly return calculations or build historical portfolio attribution; those remain separate follow-up work.
