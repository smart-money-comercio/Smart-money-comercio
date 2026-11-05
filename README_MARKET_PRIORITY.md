# Market priority and dated refinery facts — editorial rules 25

New editions use reader version 4. A dated Nasdaq decline of at least 2%, or S&P 500 decline of at least 1.5%, puts observed index moves and participation ahead of secondary source developments. Missing indexes remain missing. A cautious read based on the available indexes explicitly qualifies incomplete index coverage. The market lens prioritizes concentrated growth exposure, participation and upcoming results during that pressure; an energy topic cannot replace the observed selloff. Text and spoken editions put market and checked company price watches first.

Market-event focus distinguishes repeated quotes from unresolved readings. Rechecked events retain priority over pending events; within that tier, absolute move size precedes recent exposure. Original earnings, guidance and regulatory developments retain their higher priority. Source quality, publication windows, ranking scores, monitored symbols and quote-request limits are unchanged. Two quotes from one provider remain a repeat check, not independent corroboration or proof of a market cause.

The EIA refinery product-mix reader requires an admitted original body, matching EIA identity and an original zoned publication clock. It records measurement coverage, dated gasoline yield averages and, when explicitly supported, the first jet-fuel threshold crossing, its later yield floor and EIA's stated margin incentive. Each field includes its source sentence. The report and voiceover retain measurement periods and comparison qualifiers; publication day does not become the observation month. Product yields are refinery shares, not bond yields or current fuel prices.

Missing periods, conflicting statistics, regional or speculative claims and future measurement months cannot supply national facts. Recognized product-mix headlines without a body are held; bodies without a dated material average are skipped. Other EIA throughput and solar-storage profiles keep their existing behavior.

Live participation uses singular verbs for one advancing or declining name. Completed-session wording stays in the past tense. Saved reader versions 1–3 and evidence profiles 1–10 keep their previous interpretation. The synthetic rules-24 fixture preserves its report, narration and company-focus decisions exactly, including the old selection that rules 25 fixes for new editions.

## Verification

```bash
.venv/bin/python scripts/check_market_priority.py
.venv/bin/python scripts/check_market_priority.py --windows-socketpair
bash deployment/preflight_check.sh
```

The offline suite checks dated fact extraction, withholding, index coverage, focus priority, narration source references and saved-edition hashes. Video export remains schema 2 with `draft_review_required`; no messages, orders, TTS calls or uploads are sent by these checks.
