# Publisher readers and narration — rules 22

This release builds on deployed rules 21 revision `38cfb40`. It repairs AMD's original-release date matching, restores bounded release discovery from Northrop Grumman's public newsroom, and improves newly built narration. No dependency is added.

AMD's original release can show a date such as `November 03` or `Nov. 03`. The reader now accepts the zero-padded day and checks the release's own visible date field when present. A different day, month, year, title or explicit publication timestamp still fails verification. The original zoned RSS publication time remains authoritative. AMD's older excerpt cache is reviewed once after upgrading without renewing its feed observation clock.

Northrop's current News Stream page loads its article list dynamically. If that page returns successfully without recognizable release links, the reader can inspect the configured official newsroom homepage once. It reads only identified release-card headlines and verifies at most three distinct article pages. An HTTP error from the primary index retains its cooldown. A blocked homepage also retains its HTTP retry time; foreign redirects and unrecognized alternative endpoints are rejected.

Northrop's new article layout supplies an explicit zoned `og:publishDate` field. It is accepted only with a matching title, a single matching heading and the same canonical article URL. The publisher's duplicated leading slash in that canonical field is normalized for comparison only. Modification dates and date-only values do not establish an original publication clock. The article reader isolates the body from media contacts and navigation.

Source coverage distinguishes a quiet, dated publisher from an unavailable source. A successful Northrop read may show zero fresh stories when the latest verified release is outside the 24-hour news window. HTTP 403/429 responses, missing dates and unresolved identity checks remain coverage limits.

New rules 22 narration introduces refinery observations as energy news, expands EIA to the U.S. Energy Information Administration, and places a contract's value after the award description so the spoken dollar amount is grammatical. The text brief retains its original fact wording. Previously saved editions retain their original brief, narration and export hashes. The YouTube handoff remains schema 2 with source references and `draft_review_required`.

Run `python scripts/check_publisher_readers.py` for the synthetic offline publisher and narration checks. The suite covers dates, titles, canonical references, request limits, redirects, HTTP cooldowns, cache upgrades, energy labels, spoken contract values and preserved rules 21 history. It runs in the installer and Ubuntu deployment preflight.
