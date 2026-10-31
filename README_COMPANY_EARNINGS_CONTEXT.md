# Company results in the Daily Brief

Large price moves need business context as well as a quote check. The brief can now retain Intel's dated quarterly revenue and separately labeled next-quarter revenue forecast after the release leaves the fresh-news window. Alphabet's existing original-issuer and SEC earnings context remains supported.

## Admission and analysis

- Fresh company news still requires an original publication within 24 hours. Dated results context can be at most 72 hours old, with a source observation no more than six hours old. A refetch never changes the original publication date.
- Context requires a matching move of at least five percent that passed the existing repeat-quote and corporate-action checks. The company must be selected for this edition's dynamic focus. The quote check does not establish a business explanation or independent-provider confirmation.
- Intel evidence requires the exact original IR release URL, headline, visible release day, native zoned feed clock, issuer opening sentence and reporting period. The supported opening News Summary supplies current revenue and, when unambiguous, the next quarter's revenue range. Current figures, forecasts and periods remain distinct. Comparative tables, management quotations and GAAP/non-GAAP EPS do not supply these retained fields.
- Conflicting figures, ambiguous periods, stale observations and unavailable bodies withhold the context. `/editorstatus` shows whether usable Intel results were available for the rechecked move. Broader company results readers can be added individually; this does not claim universal earnings coverage.
- At most two issuer contexts can be considered per edition. A selected fresh earnings story already carries its facts, so it does not repeat as dated context. The 3,800-character brief budget can omit a complete optional context paragraph to preserve fresh stories.
- The analysis compares the forecast range with the quarter just reported, converting million/billion units before saying the entire range is above or below it. This is a sequential comparison, not an estimate of demand or a consensus beat/miss. Follow-up asks about delivery against the outlook, operating costs, profits and cash generation. It does not claim that the disclosure caused the share-price move, change research scores or recommend a trade.

## Source refresh and narration

Intel's existing normal feed refresh can read one supported results article within 72 hours. That uses its existing one-article enrichment budget; fresh material releases retain priority. The hourly desk keeps its existing model, search and source-read limits. Building a brief, viewing its log or exporting narration performs no new source fetch.

A contextualized company receives its own paragraph and voiceover scene before the remaining peer-price comparison. The scene includes the checked return, reported-period revenue and separately labeled forecast when present. Both ends of a spoken money range retain their units. `/storylog INTC` records the exact retained source passages, publication and observation clocks, periods and original URL.

Intel's new fresh-story facts use evidence schema 7; earlier story schemas retain their original interpretation. New issuer context uses schema 2 alongside Alphabet's existing schema 1 records. Stored editions remain tied to their frozen text and research proof.

`/voiceover` remains the official narration source. Its existing schema 2 episode JSON, scene source references, review requirement and narration hashes remain compatible with `Smart_Money_YouTube_Branded_Starter_v2`. Export a new reviewed edition before previewing it in the existing renderer. This update changes the bot's editorial content; rendering, Samara X configuration and private YouTube review remain in the video workflow.

## Checks

```bash
python scripts/check_company_earnings.py
python scripts/check_company_earnings.py --windows-socketpair
python scripts/check_earnings_context.py
python scripts/check_semiconductor_news.py
python scripts/check_daily_voiceover.py
python scripts/check_video_brief.py
```

The new suite checks issuer and clock binding, current/forecast period separation, next-year rollover, duplicate/conflicting figures, stale observations, source-read bounds, publication-age rules, pending quotes, peer grouping, fixed-edition review, native narration and JSON source linkage. Synthetic fixture figures are not investment research. Production source access and actual market coverage still depend on the next successful refresh.
