# Premarket risk desk — editorial rules 26

The existing Telegram bot now schedules checks at **08:45 and 09:15 America/New_York**, plus an outcome review at **16:20**. The local wall times follow US daylight saving changes. Weekday callbacks still require current provider session evidence; absent, stale or closed-market prices cannot become a risk reading. The current regular-session monitor, ranking scores and daily narration remain unchanged.

## Data and decisions

- Fixed universe: SPY, QQQ, SMH, Nasdaq-100 and S&P futures, NVDA, AMD, AVGO, ARM, QCOM, MSFT, TSLA and PLTR. Each snapshot makes at most 13 chart requests with four workers. A separate Qualcomm SEC route makes at most three requests when `SEC_USER_AGENT` is configured. The after-close review makes at most three ETF requests: at most 35 scheduled requests/day, with no background retry loop. Private admin previews have a three-minute cooldown.
- Current prices require two consecutive completed five-minute bars from today's premarket window, within 15 minutes of the check. Yahoo's extended-hours volume is frequently zero; volume is explicitly unverified and supplies no risk vote. These are observations from one provider, not independent corroboration.
- All changes use the exact last five-minute bar of the previous US cash session. The provider's dated schedules handle early closes. Futures changes use that same cash-close time, **not exchange settlement**. Continuous futures are withheld during March/June/September/December 8–22 to avoid interpreting a roll as a market move. ETF evidence remains available.
- Splits or distributions after the baseline, malformed identity, mismatched sessions, incomplete baselines, inconsistent bars, future timestamps and unusually large gaps are held. Missing data is `LIMITED`, not a calm signal. Premarket quote collection makes no requests outside 08:00–09:30 Eastern.
- Original-disclosure support uses fresh verified publisher bodies already in the news cache, plus a bounded QCOM 8-K/Exhibit 99.1 reader. It checks the issuer, accession, original acceptance clock, linked exhibit and release date. The source text and its hash are retained. No `SEC_USER_AGENT` or an inaccessible SEC source produces a visible coverage limit. An Arm price gap does not establish that its original financial release was read. Speculation, generic risk factors and positive results do not supply negative business facts.

Version-1 starting thresholds: a Nasdaq futures decline of at least 0.5% with at least 0.35 percentage points of S&P underperformance; technology ETF weakness of at least 0.75% with relative weakness, or SMH down at least 1.5%; broad ETF weakness (SPY at least 0.75%, QQQ at least 1%); three of five chip companies down at least 3%. A single qualifying price category yields `WATCH`. Two categories, or a category plus a matching original negative disclosure, yield `ELEVATED`. SPY down at least 1.5% and QQQ down at least 2%, together with substantial semiconductor weakness, yield `SEVERE`. Both completed bars must support the decline. Correlated observations are not treated as independent probabilities.

These thresholds are starting rules, not a fitted or validated forecasting model. They describe observed pre-open risk. Later direction, size and business causes remain uncertain.

## Ledger and delivery

`/premarket` shows status. `/premarket history` shows six recent decisions, including `NONE` and `LIMITED`. `/premarket review` scores each day once against the later regular-session intraday low and close. Any qualifying pre-open warning is retained; without a warning, the latest recorded slot determines the input status. A quiet second slot does not erase an earlier warning, and a recovering close does not erase an earlier stress breach. Fixed review thresholds are SPY -1.5%, QQQ -2% or SMH -3% versus the prior regular close. All three dated outcome inputs must pass validation. The review separates warnings followed by stress, warnings without a threshold breach, missed breaches, input limitations and days without a premarket record. No validated prediction accuracy or investment return is inferred.

Every scheduled slot preserves its first snapshot, source bars, disclosure text, configuration, grade, reasons and SHA-256 identity. Refreshing cannot rewrite an earlier assessment. Slot dates and clocks are checked independently. Delivery receipts are separate: `pending` is uncertain, `sent` means Telegram accepted the send, and `failed` records a failed attempt. A repeated job does not refetch or resend; an equal/lower grade is suppressed for the same destination/day after a pending or successful send. A higher grade may alert at the second slot. A failed send may retry using the next slot's fresh assessment. No warning sends after the open or after its evidence expires.

`/premarket preview`, `on` and `off` require a private admin chat. Preview replies only to that request and changes no scheduled ledger or channel receipt. The monitor respects the existing special-alert master pause and environment switch. It uses the existing alert destinations. The snapshot/outcome ledger retains 90 days; outcome review is operational monitoring, not a retrospective claim that an alert was delivered.

## Configuration

Optional settings: `PREMARKET_ENABLED` (default true), `PREMARKET_STATE_FILE` (default `data/premarket.sqlite3`), `PREMARKET_MAX_QUOTE_AGE_SECONDS` (default/max 900), `PREMARKET_CHIP_GAP_PERCENT` (3), `PREMARKET_TECH_GAP_PERCENT` (0.75), and `PREMARKET_BROAD_GAP_PERCENT` (0.75). Existing `SEC_USER_AGENT` enables the QCOM SEC read; no placeholder contact is supplied. No new Python dependency, cron entry or service is required.

After deploying, check `/premarket`, `/specialalerts`, `/editorstatus` and `/rundailyagent`. Outside the pre-open window a preview reports that limitation without fetching prices. A successful installation does not establish live provider access or Telegram delivery; inspect the next scheduled slot and its receipts. Saved rules 19–25 editions and schema-2 private-review video exports keep their earlier hashes and evidence.

## Offline validation

```bash
.venv/bin/python scripts/check_premarket_risk.py
.venv/bin/python scripts/check_premarket_risk.py --windows-socketpair
.venv/bin/python scripts/check_premarket_operations.py
.venv/bin/python scripts/check_premarket_operations.py --windows-socketpair
bash deployment/preflight_check.sh
```

All input scenarios are explicitly synthetic. Tests use isolated state, blocked external networking and mocked Telegram sends. The frozen rules-25 edition verifies that historical narration and export still reproduce exactly.
