# Daily Agent reply recovery — editorial rules 30

The manual `/rundailyagent` command previously caught research and Telegram reply exceptions in the same block. A failed status edit or brief send could replace a completed workflow's PASS with a generic FAIL. This correction preserves the workflow result and records reply confirmation separately. It does not change editorial rules, source admission, scoring or the Weekend Outlook.

The command runs the research once. An unconfirmed loading notice does not prevent that requested run. Status edits retry at most once after a network exception, using identical text and the same message. A server response that the text was already applied is accepted only after that uncertain edit. A rejected edit is not retried as a network failure.

New `send_message` requests are not automatically repeated after a read error or timeout: Telegram may have accepted the request before the connection failed. The receipt records the affected status/brief part and the number of API-confirmed parts. A notice uses the existing loading message when available. A true research failure still shows FAIL and does not send a success report.

`/agentstatus` displays the saved research result and the matching manual reply receipt. Receipt status CONFIRMED means the Telegram API acknowledged the requests; it is not evidence that a person read them. An interrupted request with no workflow result is labeled separately from any earlier saved run. Reading status does not rerun research or refresh source clocks.

The latest receipt is stored separately in `DAILY_AGENT_DELIVERY_STATE_FILE`, defaulting to `data/daily_agent_delivery.json`. It contains run identity, stage, part counts and exception class names, with no bot token, destination/chat ID, provider URL or report text. Writes are bounded and atomic. An older overlapping command cannot replace a newer request's receipt. Diagnostics do not modify the research result or the editorial history; a receipt-write failure does not fail a completed run.

For an existing generic error, first use `/agentstatus` and `/quality` to inspect the saved run. The old message alone does not identify the failed request. The updated command logs stages such as `research_workflow`, `status_edit`, `status_part` and `brief_part`, and persists the same stage in the receipt. The underlying connection failure may still recur; the correction adds a bounded edit recovery and an accurate account of what completed.

Checks: `python scripts/check_daily_agent_recovery.py` and the same command with `--windows-socketpair`. The original Daily Agent delivery, Weekend Outlook, SQLite cleanup, editorial and media-export checks remain in the cumulative installer and preflight. Preflight isolates the reply receipt from service state. The scheduled CLI/channel sender and its permissions are unchanged.
