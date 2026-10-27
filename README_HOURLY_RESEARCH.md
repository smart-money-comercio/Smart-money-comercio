# Hourly AI research desk

The bot now runs two separate model roles every hour, including nights and weekends. The Discovery Agent searches public reports for potentially material developments. A separate Relevance Reviewer receives those leads and original-source excerpts, then recommends accept, hold or skip with a relevance score, reason and exact supporting quote. Neither model has Telegram, brokerage or scoring tools.

Coverage prioritizes the core companies and dated top opportunities, AI chips/cloud/infrastructure, IPOs, defense, drones and counter-drone systems, autonomy, cybersecurity, monetary policy, trade, energy and geopolitical supply chains. Search is restricted to the configured original company/agency domains, SEC, Reuters and AP. This is a bounded research scan, not complete coverage of all publications or IPOs.

## Evidence and handoff

1. Discovery uses the OpenAI Responses API's hosted `web_search` tool. Returned candidate URLs must also appear in the API's retrieved search sources or citations.
2. Code makes at most six original-source HTTP reads per attempt. It checks the HTTPS host and redirects, matching original title, explicit publication timezone, 24-hour publication window and bounded source text. Secondary reports remain leads; they do not become confirmed stories. Routine help/documentation/service pages are screened out before source reads or a paid relevance review. SEC IPO links use the existing issuer/CIK/accession-verified IPO cache.
3. The reviewer makes one decision per candidate. Approval also requires a relevance score of at least 65, a verified original report and a quote of 20–500 characters copied exactly from its text. Model approval alone cannot pass these checks. Missing metadata, source denials, incomplete outputs and model failures withhold promotion.
4. Approved findings enter the existing cache-only news editor, intelligence context and five-minute company-alert scanner. Existing materiality, monitored-company, freshness, deduplication, pause and delivery limits still apply. An approved discovery is not automatically a channel message. Macro findings are available to the brief; market selloff alerts still require actual index quote thresholds.

The audit retains discovered URLs, publication and observation clocks, source excerpts and hashes, both model response IDs and token usage, final decisions and reasons for 30 days. `/researchdesk history` shows the latest 16 findings. The latest review of a URL takes precedence over an older approval. Brief/report/status rendering never starts a model request or source fetch. Existing investment scores, portfolio holdings and delivery receipts are unchanged.

Discovery now receives two complementary investor searches covering AI/capital markets and defense/macro/global risk, together with recently approved or skipped URLs. Search instructions exclude routine product help, tutorials and modification-time claims. Status distinguishes execution completion from editorial success and shows original-source checks, holds, skips and actual source-read counts. Zero approved findings is valid and does not establish that no market news exists.

## SEC current-report leads

SEC 8-K, 8-K/A, 6-K and 6-K/A leads can now be verified independently of the IPO cache. Filing-index, primary-document and inline-viewer URLs resolve through the issuer's authoritative SEC submissions JSON. The accession, primary-document path, issuer CIK, registrant name, form and explicit acceptance timestamp must match the actual inline-XBRL document. The event date, filing-date label and model-written title never establish publication time or issuer identity. Unsupported forms or reports without usable issuer identity remain held.

Each current-report verification uses **two** of the existing six source reads: submissions metadata and the primary document. No index-page read, extra model request or increase in the hourly budget is added. SEC reads use `SEC_USER_AGENT` when configured and never bypass a denial. Reads and redirects stay within the original permitted authority.

Only admitted, materially relevant financing disclosures enter the brief's **IPO & Capital Markets** section. A current report is distinct from an IPO milestone. GPU lease financing keeps its expected aggregate principal payments separate from annual expense, revenue and valuation; forward-looking and conditional wording is retained. These SEC findings can feed cached research and the brief; the existing market/company/IPO alert rules still determine which events may notify. `/storylog` keeps the publication decision separately from `/researchdesk history`. Index and document URLs share one filing identity for deduplication and newer holds supersede older approvals.

## Runtime and cost limits

At most one attempt per UTC hour is claimed atomically in `data/hourly_research.sqlite3`, including manual runs and service restarts. A failed run waits until the next hour. The scheduled job begins 90 seconds after startup and repeats every 3,600 seconds; overlapping runs are suppressed. Work runs outside Telegram's event loop.

Each attempt uses at most **two model requests**, **two hosted web-search tool calls**, **eight leads**, **six original-source HTTP reads**, and **4,000 output tokens per model request**. An empty discovery needs only one model request. Client timeouts are 45 seconds and automatic SDK retries are disabled; source reads have ten-second timeouts. These are request limits, not a guaranteed dollar ceiling or end-to-end deadline. Model tokens and web search are billed to the configured OpenAI API account; a ChatGPT subscription does not supply API credits. Review usage and billing after the first live run.

The two roles default to the project's existing `gpt-5` model and reuse the server's `OPENAI_API_KEY`. Each role can use a different model through configuration. Missing API access produces a LIMITED run with no accepted findings. The discovery model must support Responses web search and structured outputs; the reviewer needs structured outputs.

```dotenv
HOURLY_RESEARCH_ENABLED=true
RESEARCH_DISCOVERY_MODEL=gpt-5
RESEARCH_REVIEW_MODEL=gpt-5
# HOURLY_RESEARCH_STATE_FILE=/path/writable/by/smartmoney/hourly_research.sqlite3
SPECIAL_ALERT_CONFIRMED_ONLY=true
```

`/researchdesk run`, `/researchdesk on` and `/researchdesk off` require an admin's private chat. The pause is persistent; the environment master switch takes precedence. An unreadable pause/state database prevents paid work. `/researchdesk status` and `/researchdesk history` only read cached state. The daily-agent workflow displays the latest cached research-desk result without rerunning the models.

Company alerts now require original company confirmation by default. Previously stored headline events remain available in dated history but no longer supply current agent/report context under this policy. `SPECIAL_ALERT_CONFIRMED_ONLY=false` explicitly restores legacy headline alerts. The default source gaps remain visible; no attempt is made to bypass publisher access restrictions.

## IPO financial analysis

New SEC reads retain financial-table evidence from the bounded first megabyte of the prospectus. The parser binds revenue, operating loss, net loss, operating cash flow and financing-related fair-value changes to explicit periods and units. Annual and interim results are kept separate; conflicting values and ambiguous, pro forma or unsupported currency tables are withheld. Revenue growth uses comparable annual periods. Reported net loss is never substituted for cash burn. Customer concentration and governance disclosures are retained only when the excerpt explicitly supports them; missing disclosures are not invented. Historical IPO evidence remains readable.

The brief places IPO milestones and this analysis in **IPO & Capital Markets**, separate from **Global and Defense Watch**. Its existing 3,800-character limit, 60-second minimum narration and 15–30-second market segment remain enforced. Complete stories are omitted if necessary to fit; partial source facts are not truncated into new claims.

## Verify and operate

Run `python scripts/check_hourly_research.py` and its `--windows-socketpair` variant. Offline tests use synthetic sources and mocked model responses, including failure and publication-blocking cases. They do not establish live model or publisher availability. Deployment preflight uses temporary research state and must not create a production database as root. The service user (`smartmoney`) needs write access to its data directory and SQLite file.

After deploying, use `/researchdesk run`, `/researchdesk status` and `/researchdesk history` in the admin's private chat. A manual run consumes that hour's attempt. Then use `/rundailyagent`, `/reportcheck`, `/specialalerts preview` and `/storylog` to inspect downstream results. A quiet or source-limited hour can legitimately approve no stories.

API references: [Web search](https://developers.openai.com/api/docs/guides/tools-web-search) and [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
