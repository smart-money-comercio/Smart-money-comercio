"""Inspect, pause and manually start the hourly two-agent research desk."""

import asyncio
from src.commands.admin_commands import is_admin
from src.intelligence import hourly_research as desk
from src.utils.telegram_messages import reply_long_message


async def researchdesk_command(update, context):
    if not update.message: return
    action = str(context.args[0]).lower() if context.args else "status"
    if action in {"run", "on", "off"}:
        if not is_admin(update) or getattr(update.effective_chat, "type", "") != "private":
            await update.message.reply_text("Unauthorized: admin private chat only", parse_mode=None)
            return
        if action in {"on", "off"}:
            await asyncio.to_thread(desk.set_enabled, action == "on")
        else:
            message = await update.message.reply_text("Discovery and relevance review are running…", parse_mode=None)
            value = await asyncio.to_thread(desk.run)
            await message.edit_text("Research run: " + value["status"], parse_mode=None)
    elif action not in {"status", "history"}:
        await update.message.reply_text("Use /researchdesk [status|history|run|on|off]", parse_mode=None)
        return
    config, value = desk.settings(), desk.status()
    lines = ["Smart Money Hourly Research Desk", "Monitoring: " + ("ON" if config["enabled"] else "OFF"),
             "Cadence: every hour, including after hours and weekends", "Status: " + value["status"],
             "Last started (UTC): " + value.get("started", "not run"),
             "Discovery Agent: " + config["discovery_model"] + " · web search",
             "Relevance Reviewer: " + config["review_model"] + " · independent structured review",
             "Limits: 2 model requests / UTC hour; 2 search-tool calls; 8 leads; 6 original-source reads.",
             "Model and web-search usage are billed to the configured OpenAI API account.",
             "Original-source checks and existing alert rules determine publication and delivery."]
    details = value.get("details", {})
    lines += [f"Latest: {details.get('candidates', 0)} leads / {details.get('approved', 0)} approved"]
    if "search_leads" in details:
        lines.append(f"Search returned: {details['search_leads']} leads · held leads revisited: {details.get('retried', 0)}")
    if "publisher_candidates" in details:
        lines.append(f"Dated publisher candidates: {details['publisher_candidates']} · cached evidence used: {details.get('publisher_cache_used', 0)}")
        coverage = details.get("publisher_coverage", {})
        lines.append(f"Publisher cache coverage: {coverage.get('available', 0)} available / {coverage.get('limited', 0)} limited")
    if "source_verified" in details:
        lines += [f"Checks: {details['source_verified']} original sources verified / {details.get('held', 0)} held / {details.get('skipped', 0)} skipped; {details.get('original_reads', 0)} source reads"]
    if details.get("resolved_releases"):
        lines.append(f"Discovery links resolved to specific original releases: {details['resolved_releases']}")
    if details.get("expired"):
        lines.append(f"Expired reports retired from active follow-up: {details['expired']}")
    if value["status"] == "complete" and not details.get("approved"):
        lines.append("Review outcome: no findings cleared all relevance and original-source checks.")
    if details.get("error"): lines.append("Run limited: " + details["error"] + "; review API access and server logs.")
    if action == "history":
        try:
            records = desk.read_history(16)
        except Exception:
            records = []; lines.append("Decision history is temporarily unavailable.")
        lines += ["", "Decision history — entries can be older than the latest scan."]
        scan_at = desk.timestamp(value.get("started"))
        checked_at = [desk.timestamp(record.get("last_attempt_at", record.get("discovered_at"))) for record in records]
        if records and scan_at is not None and all(at is not None and at < scan_at for at in checked_at):
            lines.append("The latest scan recorded no story decisions; the entries below are from earlier runs.")
        for record in records:
            outcome = record.get("source_outcome", {})
            label = "EXPIRED" if outcome.get("status") == "expired" else record["review"]["final"].upper()
            lines += ["", label + " — " + (record.get("verified") or record["lead"])["title"],
                      "First discovered (UTC): " + record["discovered_at"],
                      "Last checked (UTC): " + record.get("last_attempt_at", record["discovered_at"]),
                      "Follow-up retries: " + str(record.get("retry_count", 0)) + "/" + str(desk.MAX_HELD_RETRIES),
                      "Published: " + ((record.get("verified") or {}).get("published") or outcome.get("published") or "unverified"),
                      "Original source: " + record["verification"], "Decision reason: " + record["review"].get("reason", "Review unavailable"),
                      "Evidence: " + (record["review"].get("evidence_quote") or "unavailable"), (record.get("verified") or record["lead"])["url"]]
            if record.get("verified") and record["verified"]["url"] != record["lead"]["url"]:
                lines.append("Discovered link: " + record["lead"]["url"])
    lines += ["", "/researchdesk history · /researchdesk run · /researchdesk off · /researchdesk on"]
    await reply_long_message(update, "\n".join(lines), title="Hourly Research Desk", parse_mode=None)
