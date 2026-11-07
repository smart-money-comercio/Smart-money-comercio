# Official source coverage — editorial rules 28

This update adds bounded readers for Eaton's official news index and CrowdStrike's corporate newsroom. CrowdStrike's investor-relations route retains its own status and cooldown. An alternate corporate route does not turn a blocked investor feed into an available feed.

Each new reader requests its index and at most three distinct original articles. The configured HTTPS host and release path, exact final URL, canonical identity, one complete article headline, identified article body, original zoned publication and fresh observation must agree. Short index captions are discovery cues, not admitted headlines. Eaton's source-specific Article metadata and CrowdStrike's exact-URL WebPage metadata provide original clocks; `dateModified`, Atom update timestamps, date-only values and fetch times cannot provide them. Navigation and footer text are excluded from the bounded release excerpt. Missing or conflicting evidence remains limited. Cached corporate evidence binds the title, URL, text hash, metadata and clocks again before admission.

`/editorstatus` now distinguishes a dated listing, a dated original body, a fresh original body and unavailable/unverified evidence. The issuer count groups routes by company, so adding a second route cannot inflate the number of companies covered. A readable older body is dated context and cannot become fresh news. Verified read totals describe reader operations; they are not a promise of fresh or selected stories.

The preparation audit verified three dated original bodies from each of Eaton and CrowdStrike. CrowdStrike’s exact metadata site suffix is separated from the complete H1 headline while keeping the original URL and clock bindings. Server access is still verified by the next live refresh. Apple's sampled Atom feed exposed update timestamps and its article exposed only a publication date. That does not establish an original zoned time; the existing clock requirement remains in place. HTTP 403/429 cooldowns remain effective, including with force refresh.

## SEC contact setup

Run the interactive helper locally on the Linux server, using the actual environment file read by the bot:

```bash
sudo /opt/smart-money-comercio/.venv/bin/python /opt/smart-money-comercio/scripts/configure_sec_contact.py --env-file /opt/smart-money-comercio/.env
sudo systemctl restart smart-money-ai-bot.service
```

The helper prompts for an administrative email with hidden input, writes an identified `SEC_USER_AGENT`, and never prints the address or makes a network request. A valid existing primary or alias is retained; `--replace` requests a change and `--check` checks without writing. Duplicate settings, a symbolic-link file and concurrent changes require local review. An atomic replacement preserves unrelated settings, encoding, line endings and existing mode/ownership; a private backup retains the previous environment. Do not commit the environment or its backups.

The news earnings backup, hourly filing reader and premarket earnings reader share contact-format validation. Missing or placeholder configuration prevents their SEC requests. Format validation does not verify mailbox ownership or prove SEC access. Local configuration failures can be rechecked immediately after setup; HTTP access cooldowns are retained. The status cards show configuration state without the contact. SEC's published access guidance is at https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data.

## Narration and compatibility

New editions use disclosure presentation version 2. Maintenance stories get a short business-oriented lead, the full sourced details in the body, and a distinct order-value/delivery follow-up. The designation still does not establish funded orders or revenue. Stored rules-27 and earlier reports, scripts, evidence and schema-2 media exports are validated under their original presentation versions. No premarket schedule, notification permission, risk score or allocation weight changes in this update.

## Checks

```bash
.venv/bin/python scripts/check_source_coverage.py
.venv/bin/python scripts/check_source_coverage.py --windows-socketpair
```

The 45 offline cases cover the real refresh dispatch, complete source titles, exact URLs, original clocks, body isolation, request bounds, HTTP cooldowns, cached-proof tampering, route-versus-issuer coverage, private contact setup and new editions. The frozen rules-27 regression preserves its report and voiceover hashes and schema-2 export. The existing editorial, premarket and evidence suites and deployment preflight remain required.
