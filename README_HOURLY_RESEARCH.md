# Hourly AI research desk

The bot now runs two separate model roles every hour, including nights and weekends. The Discovery Agent searches public reports for potentially material developments. A separate Relevance Reviewer receives those leads and original-source excerpts, then recommends accept, hold or skip with a relevance score, reason and exact supporting quote. Neither model has Telegram, brokerage or scoring tools.

Coverage prioritizes the core companies and dated top opportunities, AI chips/cloud/infrastructure, IPOs, defense, drones and counter-drone systems, autonomy, cybersecurity, monetary policy, trade, energy and geopolitical supply chains. Search is restricted to the configured original company/agency domains, SEC, Reuters and AP. This is a bounded research scan, not complete coverage of all publications or IPOs.

## Evidence and handoff

1. Discovery uses the OpenAI Responses API's hosted `web_search` tool. Returned web candidate URLs must also appear in the API's retrieved search sources or citations. It receives a short list of already collected publisher reports as context and searches for additional reports.
2. Code makes at most six original-source HTTP reads per attempt. It checks the HTTPS host and redirects, matching original title, explicit publication timezone, 24-hour publication window and bounded source text. Secondary reports remain leads; they do not become confirmed stories. Routine help/documentation/service pages are screened out before source reads or a paid relevance review. SEC IPO links use the existing issuer/CIK/accession-verified IPO cache.
3. The reviewer makes one decision per candidate. Approval also requires a relevance score of at least 65, a verified original report and a quote of 20–500 characters copied exactly from its text. Model approval alone cannot pass these checks. Missing metadata, source denials, incomplete outputs and model failures withhold promotion.
4. Approved findings enter the existing cache-only news editor, intelligence context and five-minute company-alert scanner. Existing materiality, monitored-company, freshness, deduplication, pause and delivery limits still apply. An approved discovery is not automatically a channel message. Macro findings are available to the brief; market selloff alerts still require actual index quote thresholds.

The audit retains discovered URLs, publication and observation clocks, source excerpts and hashes, both model response IDs and token usage, final decisions and reasons for 30 days. `/researchdesk history` shows the latest 16 findings. The latest review of a URL takes precedence over an older approval. Brief/report/status rendering never starts a model request or source fetch. Existing investment scores, portfolio holdings and delivery receipts are unchanged.

Discovery now receives two complementary investor searches covering AI/capital markets and defense/macro/global risk, together with recently approved or skipped URLs. Search instructions exclude routine product help, tutorials and modification-time claims. Status distinguishes execution completion from editorial success and shows original-source checks, holds, skips and actual source-read counts. Zero approved findings is valid and does not establish that no market news exists.

## Original-publisher evidence alongside web discovery

The hourly desk also reads the same public publisher cache used by the brief. At most three dated, materially relevant original reports can join the existing eight-candidate batch. Sources are diversified before selection. Web results and existing follow-up slots take priority; publisher reports use remaining slots. Reusing a cached report is explicitly counted separately from a newly returned search lead.

Cached evidence must come from a configured original publisher, retain a matching company/agency-domain article link, have an original zoned publication within 24 hours and an observation within six hours, and contain usable report text. Secondary feeds, headline-only entries, failed/redirected sources, impossible clocks and routine scheduling are excluded. The oldest relevant feed/excerpt observation is retained; a new agent run cannot make old evidence fresh. Publisher names, feed identity and excerpt scope are preserved in the proof. Already approved or skipped reports are not repeatedly queued as new news.

Every publisher candidate still needs a new independent model review, a materiality decision and an exact evidence quote before approval. A held lead may recover from a still-valid publisher cache without another HTTP request, but never from its prior held text. This route performs no network fetch or source-cache write and stays within the two-model-request and eight-candidate limits. Reading an existing report does not establish a new announcement or a new publication date. Status shows cache coverage, selected publisher candidates and cached evidence used.

Confirmed publication ages beyond 24 hours are terminal **EXPIRED** outcomes, retained as dated history and removed from automatic follow-up. The original clock remains visible even when the primary document need not be downloaded. Missing, ambiguous or future clocks remain holds. Business overview/profile links are skipped as non-report pages; neither a company-domain URL nor a model-written headline establishes the existence of an announcement.

## Follow-up on held leads

### Resolve the actual original report

Publisher handoff now includes up to three fresh, dated original feed entries that need a release-body read, even when the headline lacks the editor's materiality keywords. An unread headline is a source reference, not verified report text. Code reads the exact release and requires a matching complete heading and release date. When a page only displays a date, its own original RSS/Atom entry supplies the zoned publication clock; a conflicting explicit page timestamp is never overridden. Native feed date labels are retained across UTC day boundaries. Original publication stays within 24 hours and the source observation within six hours.

A company news index or investor-site mirror can resolve to a specific report in the same publisher's feed. Matching requires a unique, specific title or URL-slug match; an issuer name or one shared topic is insufficient. The audit retains both the discovered URL and the original release actually reviewed. When needed, a configured original feed can be read once during the attempt without writing the news cache. Feed and article reads share the existing six-read budget; publisher candidates share the eight-candidate cap. A publisher denial is not followed by attempts to bypass it.

The independent reviewer still must approve materiality and provide an exact source quote. Its bound review allows a material development to reach the editor even when the original title does not contain an announcement keyword. The quote, reason, model-response ID, original text and source clocks remain inspectable in the editorial record. Headline-only or failed reads cannot establish approval.

The review handoff now provides up to six contiguous source passages per candidate, with a combined 2,000-character budget. The structured model response selects a passage ID from the supplied set; code resolves it to the exact original text for that candidate. Unknown IDs, another candidate's passage, a low relevance score or an explicit reviewer HOLD cannot establish approval. Legacy literal quotes remain readable and must still match the original source exactly; paraphrases and excerpts joined with ellipses are not automatically repaired. History shows a separate publication-gate explanation when code withholds an accept recommendation.

New event profiles distinguish a reported defense test, a planned test, an AI infrastructure expansion and a technology collaboration. Reported in-flight retargeting is retained only when an admitted excerpt explicitly supports it. Analysis focuses on repeat validation, procurement, funded orders, production timing, power, financing and customer commitments as appropriate. Test results and expansion plans do not establish orders, deployed capability or booked revenue. Profiles use schema 3; saved schema 1 and 2 records keep their original facts and classification. Request, source-read and narration limits are unchanged.

Calendars, investor FAQs, FAQ indexes, topic pages and recurring price dashboards are background inputs, so they leave the news follow-up queue without a source read. Existing calendar evidence supplies scheduled events to the brief. A rediscovered held URL consumes the same three-retry allowance instead of resetting it; canonical and discovered release aliases do not create duplicate retries. Previous audit records remain intact.

A source failure or incomplete review can leave a useful lead on HOLD. The next hourly attempt can revisit up to two of the latest held findings even when discovery returns an empty list. Older, unresolved findings are prioritized when space remains in the eight-candidate batch. Current search results take up to eight slots; a full new batch leaves no retry slots. Approved or skipped decisions suppress an older hold, and SEC index/document aliases share one identity.

Automatic follow-up is limited to three retries per finding within 24 hours of its original discovery. A known original publication older than 24 hours is ineligible. The initial discovery time is preserved, and each follow-up records its own last-checked time, retry count and link to the prior review. Existing records without these fields remain readable and can receive bounded follow-up.

Every follow-up revalidates original evidence through a fresh HTTP check or a still-valid independent publisher cache, then passes reviewable evidence through a new independent relevance review. Previous HOLD decisions or stale source text cannot establish approval. All work shares the existing hourly attempt, two-model-request, eight-candidate and six-source-read caps; a full SEC verification still consumes two source reads. An expired SEC acceptance is retired after the metadata read. A model/search failure does not trigger additional model requests. Report/status rendering never runs the queue.

Status separates current search leads from held findings revisited. History identifies first discovery and last check and explicitly labels older entries when the latest empty scan recorded no decisions. Historical entries are preserved; deploying this change does not itself recheck or publish them. The next eligible hourly attempt performs the follow-up.

## SEC current-report leads

SEC 8-K, 8-K/A, 6-K and 6-K/A leads can now be verified independently of the IPO cache. Filing-index, primary-document and inline-viewer URLs resolve through the issuer's authoritative SEC submissions JSON. The accession, primary-document path, issuer CIK, registrant name, form and explicit acceptance timestamp must match the actual inline-XBRL document. The event date, filing-date label and model-written title never establish publication time or issuer identity. Unsupported forms or reports without usable issuer identity remain held.

Each current-report verification uses **two** of the existing six source reads: submissions metadata and the primary document. No index-page read, extra model request or increase in the hourly budget is added. SEC reads use `SEC_USER_AGENT` when configured and never bypass a denial. Reads and redirects stay within the original permitted authority.

Only admitted, materially relevant financing disclosures enter the brief's **IPO & Capital Markets** section. A current report is distinct from an IPO milestone. GPU lease financing keeps its expected aggregate principal payments separate from annual expense, revenue and valuation; forward-looking and conditional wording is retained. These SEC findings can feed cached research and the brief; the existing market/company/IPO alert rules still determine which events may notify. `/storylog` keeps the publication decision separately from `/researchdesk history`. Index and document URLs share one filing identity for deduplication and newer holds supersede older approvals.

## Runtime and cost limits

The existing live research-quote refresh can leave up to three large-move attention tasks in `data/market_event_checks.json` (`MARKET_EVENT_STATE_FILE` overrides the path). The next eligible hourly scan receives the issuer, quote session, quote timestamp, observation time and repeat-check status, and searches original earnings, guidance, regulatory and corporate-action disclosures within its existing two searches. These tasks remain usable for at most one hour as dated research cues; they do not refresh an old quote or establish a cause. Alphabet share classes share issuer attention while the exact quoted share class stays in the edition proof. This temporarily extends that scan's issuer coverage without changing watchlists, alert subscriptions or numerical rankings.

No extra model request, hosted search or source-read allowance is added. The live quote path itself can make up to three additional same-provider quote reads, with repeat evidence reused for 15 minutes. Status shows the scan's actual attention tasks. Rendering the daily news brief, research-desk status or decision history never initiates these checks.

At most one attempt per UTC hour is claimed atomically in `data/hourly_research.sqlite3`, including manual runs and service restarts. A failed run waits until the next hour. The scheduled job begins 90 seconds after startup and repeats every 3,600 seconds; overlapping runs are suppressed. Work runs outside Telegram's event loop.

Each attempt uses at most **two model requests**, **two hosted web-search tool calls**, **eight total candidates**, **six original-source HTTP reads**, and **4,000 output tokens per model request**. When no reviewable candidates remain after source checks, only the discovery request is needed. Client timeouts are 45 seconds and automatic SDK retries are disabled; source reads have ten-second timeouts. These are request limits, not a guaranteed dollar ceiling or end-to-end deadline. Model tokens and web search are billed to the configured OpenAI API account; a ChatGPT subscription does not supply API credits. Review usage and billing after the first live run.

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

Additional original feeds cover AMD Investor Relations, CACI Investor Relations and Northrop Grumman Investor Relations. The Northrop IR feed complements the newsroom index; an unavailable newsroom remains visible even when its IR feed works. Each feed keeps its original zoned publication clock and issuer authority checks. Quiet, old, blocked or undated items do not become fresh news. These publishers use the existing refresh and independent-review path, with no added model requests, automatic alert-universe expansion or change to delivery receipts. News rendering remains cache-only.

Alternate sources also cover Broadcom's original financial-news index, AeroVironment's corporate RSS feed and Kratos's corporate newsroom. Broadcom and Kratos index evidence requires exact release titles, original zoned clocks and identified article bodies. Kratos's article URL, WebPage metadata identity, publisher title and visible heading must agree; unrelated page dates and modification clocks remain unusable. Each blocked IR feed keeps a separate health record. These sources join the existing cache-only handoff and the same independent relevance review, within the existing two-request and six-source-read hourly limits. Source availability and editorial relevance remain separate checks.

Fed statements can use their publisher's explicit release date, US Eastern release clock and exact heading alongside the matching original feed. The reader recognizes Fed press-release body containers and excludes navigation and footer text. Conflicting metadata, title, date or DST offset remains a hold. News refresh can read at most one fresh Fed statement body; report rendering stays cache-only, and the research desk retains its existing six-read and two-model-request budgets. Source access errors remain visible; this reader does not bypass publisher blocks.

Treasury's dated official release index and Palantir's issuer-linked wire publication clocks join the existing publisher-cache handoff. Original Treasury bodies must match the listed title and clock; Palantir wire records must match the exact issuer-linked release ID and full title. Clock provenance is retained separately from the issuer URL and checked with the research proof. This adds no model requests and does not expand wire services into general original-company authorities. Apple update-only feed entries remain held for an original publication time. The desk's six source reads and two model requests per UTC hour are unchanged.

Run `python scripts/check_hourly_research.py` and its `--windows-socketpair` variant. Offline tests use synthetic sources and mocked model responses, including failure and publication-blocking cases. They do not establish live model or publisher availability. Deployment preflight uses temporary research state and must not create a production database as root. The service user (`smartmoney`) needs write access to its data directory and SQLite file.

After deploying, use `/researchdesk run`, `/researchdesk status` and `/researchdesk history` in the admin's private chat. A manual run consumes that hour's attempt. Then use `/rundailyagent`, `/reportcheck`, `/specialalerts preview` and `/storylog` to inspect downstream results. A quiet or source-limited hour can legitimately approve no stories.

API references: [Web search](https://developers.openai.com/api/docs/guides/tools-web-search) and [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
