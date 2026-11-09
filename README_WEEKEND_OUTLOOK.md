# Weekend Outlook — editorial rules 30

New builds use narration revision 2: publication wording is grammatical, technical names have explicit spoken forms, and calendar gaps are summarized once while the written five-day grid stays complete. All spoken words, including the edition title, are inside the JSON scenes. Existing editions retain revision 1 and their exact hashes. See `README_WEEKEND_NARRATION.md` for paired-export, native media preflight and reviewed-renderer sibling instructions. `/weekendstatus` displays the narration revision.

The SQLite cleanup correction explicitly closes the corruption-test connection before temporary-file cleanup. A regression retains connection references across the save, read, corruption and reuse fixtures, so garbage collection cannot conceal an open handle. This corrects the Windows installer check; the production store already closes its connections explicitly.

`/weekend` builds a separate Saturday/Sunday research edition using New York dates. It combines true weekly benchmark price returns, one business theme from concrete original disclosures, company follow-up questions, the coming Monday–Friday calendar and conditional scenarios. It is available on demand; no new public delivery job is installed.

## Commands

| Command | Behavior |
| --- | --- |
| `/weekend [refresh]` | Builds an edition, or reuses a current PASS edition for up to 30 minutes. `refresh` re-runs the bounded checks while preserving HTTP cooldowns. |
| `/weekendstatus` | Reads the latest recorded edition and displays evidence, dates, held reviews, quality and current export readiness. No network refresh. |
| `/weekendvoiceover` | Downloads a source-reviewed plain narration file from a current PASS edition. |
| `/weekendexport` | Downloads schema-2 segments and source metadata, marked `edition_type: weekend_outlook` and `mode: draft_review_required`. |

Run `/rundailyagent` first when publisher leads or the calendar snapshot are stale, then `/weekend refresh`. The outlook reads the current shared publisher cache rather than starting another publisher-wide scan. Weekly discovery also reads up to 50 prior daily editions for selected, source-checked disclosures published during this week. These records supply discovery leads; stale observations require a new original article read. Cached bodies with concrete verified facts and reviewed disclosures take priority over headline-only leads, so a prolific or low-yield feed does not consume the six-review budget first. Up to six original disclosure bodies are reviewed, with at most six additional article reads and three weekly benchmark chart reads. Existing timeouts, size bounds and source cooldowns apply. A fresh cached original body keeps its original observation clock; a stale body requires a new original read.

## Evidence and horizons

- Weekly market returns use dated closing bars for the prior Friday and the completed Friday. Friday's daily return is shown separately. Monday, range-baseline and adjusted-close substitutions are excluded. Returns exclude dividends. The first release holds a benchmark if either exact Friday is unavailable, including holiday cases; it does not guess a replacement holiday close.
- The weekly disclosure window starts Monday at midnight New York time and ends at generation. Saturday/Sunday updates retain their own dates and are labeled as weekend updates. The daily editor's 24-hour rule stays intact.
- Each admitted original body must match its publisher, complete title and original publication evidence, have a source observation within six hours, and yield at least two concrete fact fields. The selected theme uses up to three distinct publishers. Program stages, existing contract values, planned work and confirmed orders keep their source qualifications.
- A theme is analyst interpretation of the selected disclosures. Base, stronger and weaker cases are conditions to check, without probabilities, target prices or stock-move causation.
- Calendar entries must have publisher-verified macro times or issuer-confirmed notice evidence. Only the coming Monday–Friday appears in the main calendar. A later issuer event may appear in a separate horizon up to 14 days after that Friday. For a November 8 build, November 17 falls beyond November 9–13. Estimated earnings dates are excluded. Initial claims, continuing claims and the four-week average at the same verified DOL time are grouped as one weekly claims release. Missing days mean missing verified coverage.

## Quality, storage and export

PASS requires at least two verified weekly benchmark series, a qualified original-source theme, a bounded complete report and narration of 300–1,200 spoken words. Narration duration uses 160 words/minute. Incomplete evidence produces a visible CHECK review copy; it cannot be exported as a current PASS episode. Calendar coverage remains explicitly limited.

The separate `WEEKEND_STATE_FILE` defaults to `data/weekend_outlook.sqlite3`, retaining at most 40 editions within 90 days. Reads are read-only. Report, input, source and script hashes bind the edition. Validation re-derives prices, facts, theme, report and narration from the admitted proof; hashes alone are insufficient. Archived editions remain readable, while current exports require the same New York weekend, an edition no older than eight hours and observations no older than six hours. Daily edition history is not rewritten.

CLI export uses the latest recorded current PASS edition and creates new JSON and narration files:

```bash
.venv/bin/python scripts/export_weekend_outlook.py --output /tmp/weekend_outlook.json
```

The exported source map contains URLs, original publication dates where known, observation clocks and source hashes. Original article bodies remain internal. Calendar event times are not represented as article publication times. The new edition type requires an adapter review before using an existing daily media pipeline. No audio generation, video render or upload is triggered.

Offline checks: `python scripts/check_weekend_outlook.py` and `python scripts/check_weekend_outlook.py --windows-socketpair`. Deployment preflight isolates weekend state along with the existing daily and alert state. A frozen rules-29 report and voiceover retain their exact hashes and schema-2 export, alongside earlier compatibility fixtures.
