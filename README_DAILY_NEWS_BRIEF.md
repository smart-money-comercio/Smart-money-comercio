# Smart Money Daily News Brief

`/report`, `/brief` and `/newsbrief` return a concise news edition suitable for reading aloud and later adapting for YouTube or a podcast. The existing scheduled daily delivery and `/rundailyagent` use that same edition. This update creates text only; it does not generate audio, publish a video or create another scheduled send.

The edition is capped at 3,800 characters and uses short paragraphs under Market Update, Companies in Focus, What's Ahead, What We're Watching and Research Notes. It keeps the report's generation time and the quoted regular-session date separate. Weekend and after-hours prices are described as a completed session. Returns without a dated quote session are withheld. Watchlist breadth is explicitly watchlist breadth rather than a claim about the whole market. TLT remains a bond-price proxy, not verified Treasury-yield data.

Every delivered news edition must contain at least 180 spoken words, estimating a minimum of 60 seconds at the reference pace of 180 words per minute. The count excludes the title, dates, generation metadata, section headings, command links and Research Notes footer. `/reportcheck` shows the spoken word count, estimated seconds and the minimum-duration check. Actual audio duration depends on the voice and delivery pace; a later audio export can measure the finished recording.

When more context is needed, the builder first includes additional publisher-verified calendar entries, then derives index-return comparisons or watchlist participation percentages from the same dated observations. It does not add unconfirmed stories or repeated filler. Whole-story selection and optional paragraph trimming must satisfy both the narration floor and the character cap. If the available evidence cannot support both, the build fails with a narration-quality reason and no passing edition is recorded.

Deployment checks use explicit `--offline-fixture` inputs for the report, daily-agent and intelligence quality scripts. These exercise the actual renderer and duration validator against isolated synthetic data; they do not publish a report, overwrite live agent status or relax the production narration requirement. The default quality commands continue to validate current runtime inputs.

The writing follows a market-review pattern inspired by the supplied Empower commentary: start with the main observation, give the dated numbers, and close with a measured outlook. The opening and the "Our view" paragraph respond to the available session evidence. Outlook sentences pose follow-up questions about energy costs, a Nasdaq recovery or watchlist participation; they do not attribute price moves to an unverified cause. Empower's historical figures, private account information and investment opinions are not inserted into current news.

Company paragraphs keep original-source attribution, publication date/time and complete wording together. The spoken news edition requires dated company or agency reports with material investor relevance. Unconfirmed secondary headlines are held in `/storylog`; opinion, price predictions, stock-pick lists and retrospective profiles are skipped. Empty news slots remain empty. Numerical rankings and the conditional "Our view" outlook remain identified research context, separate from sourced news.

Unconfirmed Nasdaq earnings-date estimates remain in `/calendar`, `/catalysts` and `/fullreport`. They are excluded from spoken news. What's Ahead uses publisher-verified or still-valid previously verified calendar schedules. Missing coverage is identified rather than replaced with estimated timing.

Company names are expanded for the core coverage and common research leaders, including Apple, Alphabet, Amazon, Northrop Grumman and Lockheed Martin. Complete source headlines are retained in narration; the editor holds incomplete wording and removes whole stories to meet the length limit. Retrospectives and personal-wealth profiles are excluded from the daily company-news slots unless the headline establishes a relevant corporate event such as compensation or a share sale. These editorial rules do not change company scores or independently confirm headline claims.

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
