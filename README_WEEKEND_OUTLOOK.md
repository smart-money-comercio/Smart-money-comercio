# Weekend Outlook — editorial rules 32

The lead puts the weekly return and Friday's move next to one question grounded in the selected business disclosures. The narration features up to three upcoming checks and explains what each could tell readers. The written edition includes the dated five-day calendar, later issuer notices, weekly benchmark comparisons and source links.

An original prospectus or issuer announcement can supply an indicative AI IPO range and proposed symbol for the week's lead. The weekly check uses the existing SEC contact and submits no orders or alerts. It reads the latest applicable registration document for the configured default issuers with an SEC CIK. It can also show compute and infrastructure commitments when the same original passage states the total and the portion due over twelve months. Proposed offering terms are conditional. Only confirmed dates and times appear in the calendar. When SEC access or the original evidence is limited, the outlook can use other qualified disclosures.

Rules-30 and rules-31 records can still be checked against their original wording and hashes. Current exports carry a `weekend_rules` field. JSON schema 2 and narration revision 2 still define the media pairing. The Ubuntu updater upgrades the previously installed weekend preview runner by its known source hash.

New builds use narration revision 2: publication wording is grammatical, technical names have explicit spoken forms, and calendar gaps are summarized once while the written five-day grid stays complete. All spoken words, including the edition title, are inside the JSON scenes. Existing editions retain revision 1 and their exact hashes. See `README_WEEKEND_NARRATION.md` for paired-export, native media preflight and reviewed-renderer sibling instructions. `/weekendstatus` displays the narration revision.

The SQLite cleanup correction explicitly closes the corruption-test connection before temporary-file cleanup. A regression retains connection references across the save, read, corruption and reuse fixtures, so garbage collection cannot conceal an open handle. This corrects the Windows installer check; the production store already closes its connections explicitly.

The Telegram edition uses the date in New York.

- **Saturday Review** opens with weekly and Friday benchmark returns. It follows with up to two original disclosures from the completed week and the next evidence to check for each. Different business topics get preference when the available disclosures support them.
- **Sunday Outlook** opens with a short takeaway on the most relevant verified catalyst and the evidence that could change the outlook. Premarket watch gives the dated cash close as a reference for futures, ETFs, volatility and rates when fresh readings arrive. The Monday–Friday calendar uses New York times and questions for key releases. Week-ahead intelligence explains where the verified calendar can test the same economic or business question across releases. Military innovation follows public funding, adoption and delivery evidence for defense AI, drones and cybersecurity. Publisher gaps are labeled, and conditional financing and later issuer dates have their own sections when they qualify.

The scheduled Telegram post uses its configured time and recipients. It draws on the checked Weekend Outlook evidence for each weekend edition and sends the Daily Brief on weekdays. The job can reuse a current PASS record or refresh the publisher calendar and leads before building a new one. It announces when an edition is unavailable. `/weekend` previews the day's edition, and the admin command `/senddaily` posts it to the configured destinations.

## Commands

| Command | Behavior |
| --- | --- |
| `/weekend [refresh]` | Previews the Saturday Review or Sunday Outlook. It can reuse a current PASS record for up to 30 minutes. `refresh` re-runs the bounded checks while preserving HTTP cooldowns. |
| `/weekendstatus` or `/weekend status` | Reads the latest recorded edition and displays evidence, dates, held reviews, quality and current export readiness. |
| `/weekendvoiceover` or `/weekend voiceover` | Downloads a source-reviewed plain narration file from a current PASS edition. |
| `/weekendexport` or `/weekend export` | Downloads schema-2 segments and source metadata, marked `edition_type: weekend_outlook` and `mode: draft_review_required`. |

The `/weekend` command reads the shared publisher cache. When using this command with stale publisher leads or calendar data, run `/rundailyagent` first, then `/weekend refresh`. Weekly discovery also reads up to 50 prior daily editions for selected, source-checked disclosures published during this week. These records supply discovery leads for rechecking. Cached bodies with concrete verified facts and reviewed disclosures take priority over headline-only leads, so a prolific or low-yield feed does not consume the six-review budget first. Up to six original disclosure bodies are reviewed, with at most six additional article reads and three weekly benchmark chart reads. Existing timeouts, size bounds and source cooldowns apply. A fresh cached original body keeps its original observation clock. A stale body requires a new original read.

## Evidence and horizons

- Weekly market returns use dated closing bars for the prior Friday and the completed Friday. Friday's daily return is shown separately. Monday, range-baseline and adjusted-close substitutions are excluded. Returns exclude dividends. The first release holds a benchmark if either exact Friday is unavailable, including holiday cases; it does not guess a replacement holiday close.
- The weekly disclosure window starts Monday at midnight New York time and ends at generation. Saturday/Sunday updates retain their own dates and are labeled as weekend updates. The daily editor's 24-hour rule stays intact.
- Each admitted original body must match its publisher, complete title and original publication evidence, have a source observation within six hours, and yield at least two concrete fact fields. The selected theme uses up to three distinct publishers. Program stages, existing contract values, planned work and confirmed orders keep their source qualifications.
- A theme is analyst interpretation of the selected disclosures. Base, stronger and weaker cases are conditions to check, without probabilities, target prices or stock-move causation.
- Calendar entries must have publisher-verified macro times or issuer-confirmed notice evidence. Only the coming Monday–Friday appears in the main calendar. A later issuer event may appear in a separate horizon up to 14 days after that Friday. For a November 8 build, November 17 falls beyond November 9–13. Estimated earnings dates are excluded. Initial claims, continuing claims and the four-week average at the same verified DOL time are grouped as one weekly claims release. Missing days mean missing verified coverage.
- When a previously verified issuer notice drops out of the current feed, the outlook can recheck up to three original issuer pages from recent Daily Briefs and Weekend Outlooks. It keeps the original publication date and records the observation time from the recheck. The date and any previously verified time must match, and current publisher conflicts and cancellations still apply. Recheck failures appear in `/weekend status`.

## Quality, storage and export

PASS requires at least two verified weekly benchmark series, a qualified original-source theme, a bounded complete report and narration of 160–1,200 spoken words for rules 32. Older records use their original 300-word minimum. Narration duration uses 160 words/minute. Incomplete evidence produces a CHECK review copy and the current PASS export requires verified evidence. Calendar coverage remains explicitly limited.

The separate `WEEKEND_STATE_FILE` defaults to `data/weekend_outlook.sqlite3`, retaining at most 40 editions within 90 days. Reads are read-only. Report, input, source and script hashes bind the edition. Validation re-derives prices, facts, theme, report and narration from the admitted proof; hashes alone are insufficient. Archived editions remain readable, while current exports require the same New York weekend, an edition no older than eight hours and observations no older than six hours. Daily edition history is not rewritten.

CLI export uses the latest recorded current PASS edition and creates new JSON and narration files:

```bash
.venv/bin/python scripts/export_weekend_outlook.py --output /tmp/weekend_outlook.json
```

The exported source map contains URLs, original publication dates where known, observation clocks and source hashes. Original article bodies remain internal. Calendar event times are not represented as article publication times. The new edition type requires an adapter review before using an existing daily media pipeline. No audio generation, video render or upload is triggered.

Offline checks: `python scripts/check_weekend_outlook.py` and `python scripts/check_weekend_outlook.py --windows-socketpair`. Deployment preflight isolates weekend state along with the existing daily and alert state. A frozen rules-29 report and voiceover retain their exact hashes and schema-2 export, alongside earlier compatibility fixtures.
