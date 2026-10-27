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
    if "source_verified" in details:
        lines += [f"Checks: {details['source_verified']} original sources verified / {details.get('held', 0)} held / {details.get('skipped', 0)} skipped; {details.get('original_reads', 0)} source reads"]
    if value["status"] == "complete" and not details.get("approved"):
        lines.append("Review outcome: no findings cleared all relevance and original-source checks.")
    if details.get("error"): lines.append("Run limited: " + details["error"] + "; review API access and server logs.")
    if action == "history":
        try:
            records = desk.read_history(16)
        except Exception:
            records = []; lines.append("Decision history is temporarily unavailable.")
        for record in records:
            lines += ["", record["review"]["final"].upper() + " — " + (record.get("verified") or record["lead"])["title"],
                      "Discovered (UTC): " + record["discovered_at"],
                      "Published: " + (record.get("verified") or {}).get("published", "unverified"),
                      "Original source: " + record["verification"], "Reviewer: " + record["review"].get("reason", "Review unavailable"),
                      "Evidence: " + (record["review"].get("evidence_quote") or "unavailable"), record["lead"]["url"]]
    lines += ["", "/researchdesk history · /researchdesk run · /researchdesk off · /researchdesk on"]
    await reply_long_message(update, "\n".join(lines), title="Hourly Research Desk", parse_mode=None)
