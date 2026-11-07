# Dated market evidence — editorial rules 29

Rules 29 strengthens the market inputs used by the daily brief. It is preparation for a Weekend Outlook; it does not introduce a scheduled weekend edition or change notification permissions.

## Closing prices and sessions

New chart evidence uses explicit quote schema 2. A late cash-index quote still requires the correct instrument, native exchange schedule, original source timestamp, a single dated closing bar, original price precision and a dated previous-session close. Its matching allowance is at most one displayed tick, also capped at one basis point of the index price, with only machine-rounding tolerance. This accounts for two rounded representations without rounding or replacing either stored source value. Equities and ETFs cannot use the late-index exception.

The captured Nasdaq failure was a metadata price of 24579.424 against a dated daily close of 24579.4296875, with price precision 2. Their difference exceeded the old half-tick allowance while remaining below one displayed tick. The new source version accepts that narrowly bounded case. Larger conflicts, missing corroborating bars, duplicated dates, wrong instruments and stale or future timestamps remain unavailable. The sampled Russell response passed the old check, so the production omission is not assigned an unverified cause.

Completed equity prices are checked against a usable current closing bar. A material move without that bar stays qualified; a conflicting bar is rejected. A later dated session with a null close cannot silently make an earlier quote the latest baseline. New benchmark inputs use one session, and the full report aligns macro prices with watchlist breadth. Older sessions are withheld instead of being relabeled as the newest date. Source clocks and cache-observation clocks remain separate. No weekday or holiday date is invented.

## Bounded recovery and diagnostics

A normal read uses Yahoo's primary chart endpoint. Core S&P 500, Nasdaq and Russell benchmark transport failures or HTTP 500/502/503/504 can use one alternate Yahoo chart endpoint. The Morning Brief refresh shares at most two such extra reads. This is recovery within one provider, not independent corroboration. A stock failure, invalid source proof, HTTP 403/404/429, malformed response or conflicting clock does not start that recovery. HTTP 403/429 cooldowns persist across normal reads and restarts; reading a cooldown does not renew the observation clock.

The bounded source-health file, `data/market_quote_status.json` by default, records the latest attempts, original quote session/time, result and retry deadline. `/editorstatus` saves a current health snapshot with each new edition and shows core benchmark checks and up to three limited company quotes. These records explain missing input; they do not establish market causes, delivery receipts or investment outcomes. A failed diagnostic write cannot reject an otherwise usable quote. Preflight uses an isolated health path.

## Corporate actions and price returns

New chart requests explicitly ask for split events. Event checks inspect both dated reads and the interval after the prior closing date through the quoted session date. A fully dated older split, or a future planned action, does not explain Friday's daily return. An action within the return interval, an undated/conflicting action, or missing split-query coverage stays under review. Two matching equity/ETF returns of 25 percent or more still require independent price-basis review.

The adapter marks these percentages unusable for ordinary quote consumers. They do not enter daily breadth, movers or the price-based ranking inputs. Their original evidence remains available to the bounded event verifier and source-health diagnostics. Clear dated repeats are described as same-provider checks, and cannot establish why a price changed.

The code does not divide a previous close again or substitute dividend-adjusted data. Yahoo distinguishes its split-adjusted Close from Adj Close, which also incorporates distributions: https://finance.yahoo.com/quote/%5EGSPC/history/ and https://help.yahoo.com/kb/SLN28256.html. This pipeline measures price returns, not total investment returns.

## Compatibility and validation

Previously stored quote schema 1 and event/context schema 1 retain their original checks. New evidence and event/context schema 2 carry explicit qualifications. A frozen rules-28 edition preserves its exact report, voiceover and schema-2 export hashes, alongside the earlier archive fixtures. The existing premarket source parser and schedule remain unchanged. Scoring formulas are unchanged; corrected or withheld price inputs can change breadth and ranking results.

```bash
.venv/bin/python scripts/check_market_resilience.py
.venv/bin/python scripts/check_market_resilience.py --windows-socketpair
```

The 51 new offline tests cover native-close precision, source identity and clocks, current/previous bars, malformed and duplicate evidence, bounded request recovery, HTTP cooldowns, both-read action checks, interval scoping, quarantined returns, session alignment, immutable archives and complete new-edition quality. They accompany the cumulative editorial, source, premarket, voiceover and media-export tests and deployment preflight. No live Telegram send, paid narration, video render or upload is part of these checks.
