# Special alerts and agent integration

This update includes the pending Document Research integration and adds a separate five-minute event monitor. It starts with the bot after deployment and uses the existing watchlist-alert destination, daily-report destination, or admin chat in that order. Set `TELEGRAM_SPECIAL_ALERT_CHAT_ID` to choose a separate destination.

## Default triggers

| Event | Trigger |
| --- | --- |
| Company development | A dated company/news headline describing a product or concept reveal, a scheduled reveal, or production/first deliveries. |
| Market selloff | S&P 500 down at least 1.5% or Nasdaq Composite down at least 2% against the previous session close. |
| Severe selloff | S&P 500 down at least 3% or Nasdaq Composite down at least 4%. |
| Persistent selling | Two consecutive negative sessions with a compounded S&P 500 decline of at least 3% or Nasdaq decline of at least 4%. |

Companies start with TSLA, NVDA, MSFT, AVGO, PLTR, AVAV, KTOS and CRWD. Use `SPECIAL_ALERT_SYMBOLS` to change that list (maximum 20). Company-news checks also run outside market hours and on weekends. Market alerts require timestamps from the current regular session and allow 20 minutes after the provider's session close for delayed closing quotes. Holidays, early closes and daylight-saving changes use the session metadata supplied with the index quotes.

## How the existing agent participates

The monitor sends qualifying evidence through `src.agents.analyst_agent.run_analyst_agent(..., event_context=...)`. This is the project's existing deterministic analyst agent. It adds an event-specific interpretation, the existing Score Risk / Setup Risk labels where covered, and validation steps. A product reveal preserves its concept/announcement stage. Headline reports retain a company-confirmation-pending label. The agent leaves numerical scores unchanged.

The same evidence and review are saved once per event in a local SQLite store. The daily-agent workflow has a **Special Alerts Agent** step, and the context registry, `/report`, `/analyst`, `/tradeplan`, and active `/scorecard` builder read that store. Those readers use cached evidence without fetching feeds or sending another alert. No additional AI API call, key or model subscription is required.

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
- Company feeds use Yahoo ticker RSS and a best-effort Tesla IR RSS source. Official company links are distinguished from news reports. Undated items, speculation, fan renderings and competitor announcements are excluded where detected. Updated timestamps alone do not establish a new publication date.
- This is a headline monitor. Source coverage, headline wording, outages and delayed quotes limit detection. A five-minute scan interval is not a five-minute end-to-end delivery guarantee.
- Each destination has durable delivery receipts. Successful sends are suppressed across restarts; failed sends retry when still eligible. A higher market severity or company confirmation can generate a follow-up. Company stories about known products are grouped for 48 hours; unfamiliar product wording may still require manual review.
- Each destination receives at most three company messages per scan; queued eligible events remain candidates on later scans. Market warnings take priority.
- SQLite leases prevent overlapping sends. A process failure after Telegram accepts a message but before its receipt is saved can still cause a repeat. Telegram sending has no exactly-once transaction with the local store.
- Runtime SQLite files are ignored by Git and included in the deployment's existing data-folder backups. No account balances, personal holdings or private PDFs are added to alert data.

## Configuration

Optional server `.env` settings, with defaults:

```dotenv
SPECIAL_ALERTS_ENABLED=true
SPECIAL_ALERT_INTERVAL_SECONDS=300
SPECIAL_ALERT_SYMBOLS=TSLA,NVDA,MSFT,AVGO,PLTR,AVAV,KTOS,CRWD
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

The combined installer accepts the reviewed pre-research source versions and the reviewed research-patched versions. It stops on unfamiliar edits, preserves Windows Python line endings, keeps Bash scripts on LF, and rolls back interrupted file replacements. It neither commits nor deploys code.

Run from the Windows project folder:

```powershell
python "$env:USERPROFILE\Downloads\install_research_and_special_alerts.py"
if ($LASTEXITCODE -ne 0) { throw "Installer stopped; review its output." }
python -m pip install -r requirements.txt
python scripts/check_special_alerts.py
python scripts/check_research_integration.py
python scripts/check_report_consistency.py
git diff --stat
git status --short
```

After committing and deploying through the existing workflow, check `/specialalerts`, `/specialalerts preview`, `/agentstatus`, and `/reportcheck`. The daily-agent status gains its event-review step after its next run. Automatic messages begin only when the updated bot is running with a configured destination. Tests use offline fixtures and mocked Telegram delivery; they do not establish live-feed coverage or a server deployment.
