# Special alerts and agent integration

This update includes the pending Document Research integration and adds a separate five-minute event monitor. It starts with the bot after deployment and uses the existing watchlist-alert destination, daily-report destination, or admin chat in that order. Set `TELEGRAM_SPECIAL_ALERT_CHAT_ID` to choose a separate destination.

## Default triggers

| Event | Trigger |
| --- | --- |
| Company development | A dated product/concept reveal, production/first deliveries, concrete contract/partnership, financial results, guidance change, announced acquisition, or specified business risk. Routine earnings scheduling and price chatter are excluded. |
| Market selloff | S&P 500 down at least 1.5% or Nasdaq Composite down at least 2% against the previous session close. |
| Severe selloff | S&P 500 down at least 3% or Nasdaq Composite down at least 4%. |
| Persistent selling | Two consecutive negative sessions with a compounded S&P 500 decline of at least 3% or Nasdaq decline of at least 4%. |

Core companies start with TSLA, NVDA, MSFT, AVGO, PLTR, AVAV, KTOS and CRWD. Use `SPECIAL_ALERT_SYMBOLS` to change that list (maximum 20). The monitor also reads the top 10 companies from the existing `data/opportunity_score_memory.json`, deduplicates them with the core list, and bounds coverage to 30 symbols. It never reruns rankings to choose companies during a scan. Ranking snapshots must have a valid date within four calendar days and finite scores; unavailable, malformed, future-dated or older snapshots leave the core list active. The date and selected companies are shown in status and preview. `SPECIAL_ALERT_TOP_COUNT=0` disables ranked additions; values from 1 to 10 set their limit. Company-news checks also run outside market hours and on weekends. Market alerts require timestamps from the current regular session and allow 20 minutes after the provider's session close for delayed closing quotes. Holidays, early closes and daylight-saving changes use the session metadata supplied with the index quotes.

## How the existing agent participates

The monitor sends qualifying evidence through `src.agents.analyst_agent.run_analyst_agent(..., event_context=...)`. This is the project's existing deterministic analyst agent. It adds an event-specific interpretation, the existing Score Risk / Setup Risk labels where covered, and validation steps. A product reveal preserves its concept/announcement stage. Headline reports retain a company-confirmation-pending label. The agent leaves numerical scores unchanged.

Reviews use event-specific checks: contracts focus on funding and recognition, results on margins and cash flow, guidance on changed assumptions, and risks on operational exposure. The same evidence and review are saved once per event in a local SQLite store. The daily-agent workflow has a **Special Alerts Agent** step, and the context registry, `/report`, `/analyst`, `/tradeplan`, and active `/scorecard` builder read that store. Those readers use cached evidence without fetching feeds or sending another alert. No additional AI API call, key or model subscription is required.

`/rundailyagent` refreshes the Morning Brief cache before a live report build; deployment dry runs skip this network step. If refresh fails, stale or future-dated macro percentages and headline themes are withheld from current report signals. Independent watchlist quotes remain separate. The workflow status shows a short report-build result and all final checks; the complete report is sent separately once. Previously saved status records with an embedded report are summarized when displayed.

Watchlist daily returns use the dated prior trading-session close, never the starting close of Yahoo's multi-day chart. The shared quote reader preserves the regular-session timestamp and date, rejects unavailable or stale session data, and permits the last completed session after hours. The daily snapshot shows its watchlist scope and quote dates, excludes failed or older-session quotes from the newest dated snapshot, and feeds these corrected returns into existing breadth, ranking, and alert rules. A bearish watchlist can still differ from a positive index; the update does not force them to agree.

Fresh market stress can affect the integrated summary's risk posture. It expires with its quote freshness window. A valid below-threshold scan from both main indexes clears active market stress. Company context expires with the original publication time, rather than becoming fresh each scan. Dated history remains available for 24 hours through the command. Internal records are retained for up to 30 days.

## Telegram controls

```text
/specialalerts
/specialalerts preview
/specialalerts history
/specialalerts on
/specialalerts off
```

`preview` shows current candidates and the agent review in the requesting chat; it does not publish to the alert channel, change event memory or consume delivery receipts. `on` and `off` require an existing admin's private chat. A server-level `SPECIAL_ALERTS_ENABLED=false` setting takes precedence over the on command. Paused monitors remain scheduled so they can resume without restarting.

## Source and delivery behavior

- Index returns are computed from the correct dated daily closes; Yahoo's range-start close is not used as yesterday's close. Two-session returns are compounded, not added.
- Quotes older than 20 minutes, future timestamps, missing prices and missing prior-session closes are rejected. Unavailable data is displayed as unavailable.
- Morning Brief, daily-report macro context and company research backdrops use the same dated regular-session return parser as watchlist quotes. Cache rows retain the original chart evidence and are revalidated when read; a new cache timestamp cannot make an old quote current. Legacy rows without dated evidence are withheld until the next refresh. Backdrops show the quote session and source time separately from the cache refresh time.
- Completed S&P 500, Nasdaq, Dow and Russell cash-index quotes can have source timestamps after the close. Report readers accept those updates only when the source identifies a daily cash index without extended-hours data and its price agrees with the same session's dated daily closing bar at the source's stated precision. Original quote timestamps are retained. The special-alert monitor's regular-session window and quote-age limits remain unchanged.
- Each selected company retains its Yahoo headline feed. NVIDIA and Microsoft additionally use their official newsroom/blog feeds, with company attribution based on the verified publisher and company-domain article links. This permits issuer headlines that omit the company name without promoting unrelated or third-party articles to confirmed announcements.
- Palantir uses the public release service observed in its investor website. Explicitly zoned original release dates are accepted. When the service supplies a date without a timezone, it is only a candidate-selection hint: the exact original release timestamp must be verified from matching publication metadata on the linked wire release. Modified dates, page refreshes and unrelated titles never establish freshness. If that timestamp cannot be verified, the release is withheld, the limitation is shown, and independent headline monitoring continues.
- Status and preview show headline and official-source health for every selected company. Companies without an official adapter are explicitly marked as headline coverage only. A reachable feed or index does not confirm a particular news headline or guarantee all material events will be detected.
- Company feeds use Yahoo ticker RSS and a best-effort Tesla IR source. If Tesla's RSS endpoint fails (including HTTP 403/404), the monitor tries the public IR homepage and up to three discovered release pages on the same HTTPS host. It uses the release page's original publication time, never the earnings-calendar date or fetch time. Missing or ambiguous release dates are unavailable, not fresh evidence. Headline feeds keep running when official pages fail; status and preview show TSLA headline availability separately from the confirmation source, with actual HTTP codes for failures.
- Official company links are distinguished from news reports. The public-page fallback marks only the release it actually read as official; it does not promote Yahoo headlines to confirmed announcements. Undated items, speculation, fan renderings and competitor announcements are excluded where detected. Updated timestamps alone do not establish a new publication date.
- This is a headline monitor. Source coverage, headline wording, outages and delayed quotes limit detection. A five-minute scan interval is not a five-minute end-to-end delivery guarantee.
- Each destination has durable delivery receipts. Successful sends are suppressed across restarts; failed sends retry when still eligible. A higher market severity or company confirmation can generate a follow-up. Company stories about known products are grouped for 48 hours; unfamiliar product wording may still require manual review.
- Each destination receives at most three company messages per scan; queued eligible events remain candidates on later scans. Market warnings take priority.
- SQLite leases prevent overlapping sends. A process failure after Telegram accepts a message but before its receipt is saved can still cause a repeat. Telegram sending has no exactly-once transaction with the local store.
- Runtime SQLite files are ignored by Git and included in the deployment's existing data-folder backups. No account balances, personal holdings or private PDFs are added to alert data.
- Deployment preflight uses a temporary special-alert database and removes it on exit, so checks run with `sudo` cannot create a root-owned production alert store. The runtime database must remain writable by the bot's service user (normally `smartmoney`).

## Configuration

Optional server `.env` settings, with defaults:

```dotenv
SPECIAL_ALERTS_ENABLED=true
SPECIAL_ALERT_INTERVAL_SECONDS=300
SPECIAL_ALERT_SYMBOLS=TSLA,NVDA,MSFT,AVGO,PLTR,AVAV,KTOS,CRWD
SPECIAL_ALERT_TOP_COUNT=10
SPECIAL_ALERT_SP500_DROP=1.5
SPECIAL_ALERT_NASDAQ_DROP=2
SPECIAL_ALERT_SP500_SEVERE_DROP=3
SPECIAL_ALERT_NASDAQ_SEVERE_DROP=4
SPECIAL_ALERT_SP500_TWO_SESSION_DROP=3
SPECIAL_ALERT_NASDAQ_TWO_SESSION_DROP=4
SPECIAL_ALERT_MAX_QUOTE_AGE_SECONDS=1200
SPECIAL_ALERT_NEWS_MAX_HOURS=6
# TELEGRAM_SPECIAL_ALERT_CHAT_ID=@your_channel
```

Thresholds are positive magnitudes. Invalid or nonfinite configuration uses the documented defaults. The scan interval is bounded to 60–3600 seconds and the quote-age setting to at most 30 minutes. Environment changes require a bot restart.

## Install and verify

Use the repository's existing GitHub review and `deployment/update_bot.sh` deployment workflow. The deployment preflight runs the offline company-alert check alongside the existing special-alert, daily-agent and quote checks.

From a project checkout, the focused checks are:

```text
python -m pip install -r requirements.txt
python scripts/check_company_alerts.py
python scripts/check_special_alerts.py
python scripts/check_research_integration.py
python scripts/check_report_consistency.py
python scripts/check_daily_agent_delivery.py
python scripts/check_watchlist_quotes.py
```

The GitHub alert-regression workflow runs these checks on Linux/Python 3.12 and Windows/Python 3.14. Tests use synthetic publisher evidence and mocked delivery; source reachability checks do not send alerts.

After committing and deploying through the existing workflow, check `/specialalerts`, `/specialalerts preview`, `/agentstatus`, and `/reportcheck`. The daily-agent status gains its event-review step after its next run. Automatic messages begin only when the updated bot is running with a configured destination. Tests use offline fixtures and mocked Telegram delivery; they do not establish live-feed coverage or a server deployment.
