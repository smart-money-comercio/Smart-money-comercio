# Original-source intelligence — rules 21

This release adds bounded article reading and source-linked business facts to the rules 20 Daily Brief. It builds on repository revision `879a497` and adds no dependency. The Weekend Outlook is a later feature; this release supplies more useful evidence for it.

## What changes

- Original RSS readers can read up to two distinct fresh articles per feed. The new RSS reads share 12 attempts and a 30-second window for starting requests per refresh. A request already started retains the existing network timeout. Intel earnings context and Fed statements retain their one-page limits; existing index and PDF readers retain their separate limits.
- Calendar notices do not consume these article reads. Cached results are reused without changing their publication or observation clocks. Failed and deferred reads appear in coverage diagnostics.
- The Nvidia blog reader isolates the article text from its heading and sharing controls. EIA's Today in Energy body and visible publication field are recognized explicitly. Publisher identity, the exact article title and the original publication clock or matching release date still have to agree.
- A fresh, verified original body can establish materiality missing from a headline. An issuer's actual contract award or dated EIA refinery observations can qualify. Feed summaries, promotional language, another company's award, forecast amounts and unverified links cannot supply this promotion.
- Deployment facts retain named technology, use, location and implementation stage. Rollout targets remain targets. Contract facts separate stated award value, duration, customer, work and obligated funding. Refinery facts retain units, direction and reporting periods; these historical figures do not establish a current oil-price cause.
- The brief and narration use concise summaries when these facts are available. Nvidia's uppercase brand is normalized in newly built rules 21 narration. Full original titles and the supporting sentences remain in `/storylog`.
- The new evidence profile is schema 8. Older fact profiles and saved narration retain their original behavior. The YouTube export remains schema 2 with `draft_review_required` and source-linked segments.

## Boundaries

The reader examines a bounded excerpt, not every paragraph or every publisher. Missing commitments, funding and margin figures are reported as unspecified in the reviewed text. A press release's stated award value is not a claim of funded backlog or earned revenue. Business interpretation remains separate from disclosed facts.

The release does not clear publisher HTTP 403/429 errors, infer publication timezones, bypass cooldowns or invent a SEC contact. A publisher can remain available while an article read is limited. Coverage now reports those article outcomes separately.

Alphabet's SEC earnings backup still needs a real administrative contact in `SEC_USER_AGENT` in the service's existing runtime configuration. Updating code does not supply that contact. `/editorstatus` reports whether the backup is usable. Keep an unavailable source marked limited until a successful source check verifies it.

## Verify after deployment

Run `/rundailyagent`, `/editorstatus`, `/brief`, and `/voiceover`. Expect `Editorial rules: 21`, passing brief and voiceover checks, original article review counts, and source-specific coverage notes. Fact counts and selected stories depend on the current available evidence. Use `/storylog NVDA` or `/storylog CACI` to inspect facts and their supporting sentences; a story may have aged out of the 24-hour news window by the time you deploy.

`python scripts/check_disclosure_intelligence.py` runs synthetic offline checks for reading budgets, dates, materiality, qualified facts, narration, source references and historical rules 20 hashes. It is included in the installer and Ubuntu preflight.
