# Smart Money news editor

The daily brief now selects up to three current sourced stories, alongside the dated market snapshot and upcoming calendar. It uses six inspectable stages within the existing daily agent: Scan, Source Check, Relevance, Selection, Editorial Review and Decision Log. These are bounded role-specific checks; no additional model subscription is required.

Company candidates come from active special-alert evidence and the existing cached news RSS feeds. Coverage uses configured core companies plus dated top opportunities. Source dates remain original publication times, never the time a page was fetched. The reader accepts at most six-hour-old feed fetches and 24-hour-old articles, checks HTTPS source links, and rejects HTML page-title fallbacks. Publisher feeds retain publisher authority only when article links match the publisher. Yahoo headlines stay headline-only accounts; they do not establish company confirmation.

Selection favors sourced announcements and research relevance, then newer publication times. Duplicate article URLs and normalized titles are skipped. Tracking parameters do not make a repeated article new. Each represented company receives at most one story; Alphabet share classes count as one issuer. When company candidates are available, macro stories occupy at most one slot. Fewer than three stories is a valid result when evidence is limited.

Editorial rules version 2 separates announcements, reported developments, commentary and roundups using the headline's format. Broad index previews and stock-pick lists are skipped with a visible reason; a mention of Tesla or Microsoft does not make such a roundup a company announcement. Explicit commentary receives lower priority than a specific report and keeps a commentary label in narration. These format checks do not verify the article's substance or imply that its full text was read. Official evidence retains its original authority. Original decisions from older editions remain readable.

The spoken text retains source attribution, original publication time and confirmation status within each story paragraph. Repeated research-focus prompts remain in the evidence log. The brief's "Our view" outlook is conditional and uses the dated snapshot; it does not assert the cause of market moves. Length budgeting removes whole paragraphs; a story removed to fit 3,800 characters is logged as skipped. Final review checks selected story paragraphs against the source-derived statements before returning the report. Quality validation also rejects an unqualified headline paragraph even when another paragraph retains its qualification.

`/editorstatus` shows the latest built edition and all six stages. `/storylog` shows selected, skipped and held candidates from the latest three editions. `/storylog NVDA` filters the decision history to a company. Each candidate retains its headline, original date, source check, original URL, confidence label and selection reason. Market evidence and the underlying research/report hashes link the brief to its inputs. These records describe built editions; Telegram delivery remains in the existing delivery records.

Records live in `data/news_editor.sqlite3`, overridable with `NEWS_EDITOR_STATE_FILE`, and retain up to 200 editions from 30 days. Reads use SQLite read-only mode and do not create a missing database. A failed audit write prevents the report build from succeeding. The daily agent additionally checks that the returned report matches a recorded passing editorial review. Deployment preflight uses an isolated temporary editor database.

This update supplies news research and decision inspection. Position sizing, broker order execution and return attribution are separate future workflows. Company scores, alert receipts and source caches retain their existing behavior.

```text
python scripts/check_news_editor.py
python scripts/check_news_editor.py --windows-socketpair
python scripts/check_daily_news_brief.py
python scripts/check_daily_agent_delivery.py
```
