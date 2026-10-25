# Smart Money Daily News Brief

`/report`, `/brief` and `/newsbrief` return a concise news edition suitable for reading aloud and later adapting for YouTube or a podcast. The existing scheduled daily delivery and `/rundailyagent` use that same edition. This update creates text only; it does not generate audio, publish a video or create another scheduled send.

The edition is capped at 3,800 characters and uses short paragraphs under Market Update, Companies in Focus, What's Ahead, What We're Watching and Research Notes. It keeps the report's generation time and the quoted regular-session date separate. Weekend and after-hours prices are described as a completed session. Returns without a dated quote session are withheld. Watchlist breadth is explicitly watchlist breadth rather than a claim about the whole market. TLT remains a bond-price proxy, not verified Treasury-yield data.

The news edition is rendered from the same validated detailed report. `/fullreport` retains the research tables, scores, trade-plan snapshot, allocation, source context and validation commands. Quality checks recognize both formats; the news edition has its own structure, date/greeting, length and source-qualification checks. It does not present numerical research rankings as confirmed entries or change stock scores. Important cached market alerts retain their dated source evidence and do not establish the cause of a price move.

## Company catalyst brief

`/catalysts` covers the configured core companies plus up to ten dated cached top opportunities, using the same universe as special alerts. `/catalysts MSFT` narrows that brief to a monitored company. An outside symbol is identified as outside the current coverage rather than being silently scored. Core coverage includes TSLA, NVDA, MSFT, AVGO, PLTR, AVAV, KTOS and CRWD by default. Additional opportunities depend on valid cached rankings, whose date is shown.

The brief joins the existing calendar, numerical ranking snapshot and active sourced-event cache. Earnings dates remain Nasdaq estimates pending company confirmation. Conflicting dates are shown as conflicts, incomplete coverage is distinct from an empty result, headline-only reports remain unconfirmed by the company, and a market event is kept separate from company-specific news. The analyst agent explains the next research checks without adding score changes, risk votes or symbol votes. Fresh price and volume confirmation still require a separate check.

Calendar Review and direct report builds now warm five business days, so later-week catalysts can feed the brief, existing trade plans and scorecards. The compact calendar in `/fullreport` still displays two days. Company Catalyst Review runs after the daily report has refreshed ranking memory. Company brief readers fetch no network data, do not rescore, do not send to a channel, and open the existing SQLite event database read-only. A missing database is not created by the reader. Calendar age, ranking age and event expiry retain their existing policies.

## Checks

```text
python scripts/check_daily_news_brief.py
python scripts/check_daily_news_brief.py --windows-socketpair
python scripts/check_daily_agent_delivery.py
python scripts/check_report_consistency.py
```

Regression checks cover both report formats, delivery, read-only cache access, multi-company coverage, earnings confidence, headline attribution, market-session labels, source gaps and bounded narration. The new check is included in deployment preflight and the Linux/Windows regression workflow.
