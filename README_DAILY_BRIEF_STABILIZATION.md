# Daily Brief stabilization wording — editorial rules 20

New editions lead with weakness already observed in the dated market evidence. When all three tracked indexes are lower, the opening says so before discussing an individual outlier. If all quoted watchlist names are lower, the wording explicitly refers to that tracked group. It does not infer the direction of every stock from the watchlist or attribute a price move to an earnings release.

The follow-up section explains what to observe next and why it matters. A completed-session edition looks to the next session. A live edition checks whether participation improves before the close. All-gain editions ask whether gains hold, rather than asking more names to participate when every tracked name is already higher. Missing session evidence cannot supply an index or participation claim.

For admitted Intel results context, the opening can explain that the entire next-quarter revenue forecast lies above or below the revenue just reported. The comparison reuses the validated original-results parser and normalized currency units. Overlapping ranges do not supply a directional comparison. The next business check compares reported sales against management's outlook and considers costs and cash generation. A forecast remains an outlook, and the dated disclosure does not establish a market cause.

These changes use internal reader version 2 and editorial rules 20. Reader version 1 is retained for frozen historical editions. An offline rules 19 fixture verifies the original brief and voiceover hashes after this upgrade. New script text and scene references continue through the existing schema 2 native episode export, with review required. Opening-card bullets include the market takeaway and the company receiving attention. The V2 renderer interface is unchanged.

The existing source checks, 24-hour fresh-news window, 72-hour dated-results window, source-observation limits, character budget, scoring and model-request budgets remain in force. This update adds no dependencies, changes no credentials, performs no provider calls during checks, and does not alter delivery receipts.

Run `python scripts/check_reader_brief.py` and its `--windows-socketpair` variant for the reader regressions. The existing company-results, video-brief, daily-voiceover, daily-brief and news-editor suites also cover this change and run through the cumulative installer and deployment preflight.
