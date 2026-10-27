# AI IPO alerts

The five-minute special-alert monitor now follows configured AI issuers independently of stock tickers and opportunity rankings. Default coverage is Anthropic (SEC submissions and original company news index) and OpenAI (original company RSS). This is explicit issuer coverage, not a claim to scan every global IPO. More issuers can be configured with an exact company domain and an SEC CIK or original feed/index.

Milestones distinguish confirmed company plans, confidential draft submissions, public S-1/F-1 filings, amendments, indicative price ranges, final prospectuses, pricing, planned trading starts, actual trading reports and withdrawals. SEC forms alone do not establish an IPO: the bounded prospectus face must explicitly identify an initial public offering. Resale registrations, private funding rounds, rumors and price predictions do not trigger these alerts. A public filing is not a statement that shares are already trading.

SEC records use the original acceptance timestamp and an issuer/CIK/accession-bound archive link. Company reports require original zoned publication metadata or an original publisher RSS clock. Date-only midnight placeholders and modification times are not promoted to publication times. The monitor retains a bounded original excerpt, its hash, stage, source URL and clocks. Proposed symbols remain qualified; price, valuation and dates are not filled from speculation.

Current IPO milestones use a separate 24-hour publication window, with observations no older than six hours. Existing company-news and quote windows are unchanged. Successes are checked every five minutes; a failing source has a 15-minute backoff that does not delay healthy sources. HTTP denials and unavailable clocks remain explicit source gaps. Reads are bounded to two SEC prospectus prefixes and two company-index details per issuer per scan.

Each issuer's current milestone is delivered through the existing destination, pause controls, delivery leases and receipts. A successful delivery suppresses the same stage for 30 days; a new stage can notify again. Company and IPO alerts share the existing three-message-per-destination scan cap. Failed sends remain retryable. The source cache and evidence history are not delivery receipts.

The analyst reviews offering stage, valuation, revenue quality, losses, cash needs, dilution, governance and AI concentration. It assigns no inferred stock score to an unlisted issuer and does not infer direct holdings, funded orders, guaranteed returns or a cause for index moves. The daily news editor can admit these same verified IPO records without requiring a ticker. Rendering and history read cached evidence only.

## Settings

- `AI_IPO_ALERTS_ENABLED=true` enables this coverage under the existing special-alert monitoring switch.
- `AI_IPO_NEWS_MAX_HOURS=24` bounds the milestone window (1 to 24 hours).
- `AI_IPO_CACHE_FILE` optionally changes `data/ai_ipo_cache.json`.
- `SEC_USER_AGENT` can identify the deployment and a real operator contact according to SEC access guidance.
- `AI_IPO_ISSUERS_JSON` adds or overrides up to ten issuer definitions. Each needs a lowercase ID, `name`, exact `domain`, and at least one of `cik`, `feed` or `index`. All configured endpoints must belong to that issuer; CIKs must be verified against the original SEC record.

Example additional issuer (synthetic identity):

```json
{"exampleai":{"name":"Example AI","domain":"example.ai","cik":"12345"}}
```

## Verification

Run `python scripts/check_ipo_alerts.py` and its `--windows-socketpair` variant. Deployment preflight uses an isolated IPO cache. The guarded installer includes these checks and preserves production caches and delivery receipts.

In Telegram use `/specialalerts`, `/specialalerts preview`, `/specialalerts history`, `/storylog ANTHROPIC` and `/reportcheck`. Preview refreshes source observations but does not send channel alerts or change delivery receipts. Source freshness and original evidence determine whether a particular old announcement still qualifies.
