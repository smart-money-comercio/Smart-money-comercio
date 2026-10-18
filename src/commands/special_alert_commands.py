"""Status, read-only preview and owner controls for special alerts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.commands.admin_commands import is_admin
from src.config.special_alerts import settings
from src.intelligence import special_alert_store as store
from src.jobs.special_alert_scheduler import collect_snapshot, destinations
from src.utils.telegram_messages import reply_long_message


def status_report() -> str:
    config, state = settings(), store.get_settings()
    active = config["enabled"] and state.get("enabled", True)
    lines = ["🚨 Special Alerts", "Monitoring: " + ("ON" if active else "OFF"),
             f"Scan interval: {config['interval'] // 60} minutes · company news also after hours/weekends",
             "Market checks: regular session plus 20 minutes for delayed closing quotes",
             f"Destinations: {len(destinations())} configured", "",
             f"Selloff: S&P 500 -{config['sp_drop']:g}% / Nasdaq -{config['nasdaq_drop']:g}%",
             f"Severe: S&P 500 -{config['sp_severe']:g}% / Nasdaq -{config['nasdaq_severe']:g}%",
             f"Two negative sessions: S&P 500 -{config['sp_two_day']:g}% / Nasdaq -{config['nasdaq_two_day']:g}% compounded",
             "Companies: " + (", ".join(config["symbols"]) or "none configured"),
             f"Maximum quote age: {config['max_quote_age'] / 60:g} minutes; news age: {config['news_hours']:g} hours",
             "Repeats: one level per market session; worsening severity and company confirmation can alert again.",
             "", "Last scan: " + state.get("last_scan", "not run yet"),
             f"Last scan deliveries: {state.get('last_sent', 0)} sent / {state.get('last_failed', 0)} failed",
             "Source status: " + ("; ".join(state.get("last_issues", [])) or "No recorded source errors"),
             "", "/specialalerts preview — current candidates; does not send to the channel",
             "/specialalerts history — dated events and agent reviews from the past day",
             "/specialalerts on · /specialalerts off — admin only"]
    if not config["enabled"]:
        lines.append("SPECIAL_ALERTS_ENABLED is disabled in the server environment.")
    if not destinations():
        lines.append("No alert destination configured; automatic messages cannot be delivered.")
    return "\n".join(lines)


async def specialalerts_command(update, context) -> None:
    if not update.message:
        return
    action = str(context.args[0]).lower() if context.args else "status"
    if action in {"on", "off"}:
        if not is_admin(update) or getattr(update.effective_chat, "type", "") != "private":
            await update.message.reply_text("Unauthorized: admin only", parse_mode=None)
            return
        store.save_settings(enabled=action == "on")
        await reply_long_message(update, status_report(), parse_mode=None)
        return
    if action not in {"status", "preview", "history"}:
        await update.message.reply_text("Use /specialalerts [status|preview|history|on|off]", parse_mode=None)
        return
    if action == "status":
        await reply_long_message(update, status_report(), parse_mode=None)
        return
    if action == "history":
        from src.intelligence.special_alert_context import event_fact
        events = store.recent_events(datetime.now(timezone.utc).timestamp(), active_only=False)
        text = "Special Alerts · Past 24 Hours\n\n" + ("\n\n".join(
            ("Active context: " if event["currently_active"] else "Historical context: ")
            + event_fact(event) + "\n" + event.get("agent_review", "Agent review unavailable")
            for event in events) or "No recorded events yet.")
        await reply_long_message(update, text, title="Special Alerts History", parse_mode=None)
        return
    loading = await update.message.reply_text("Checking special alert candidates…", parse_mode=None)
    try:
        snapshot = await asyncio.to_thread(collect_snapshot)
        messages = ["Special Alerts Preview · " + snapshot["asof"],
                    "Preview only. Delivery receipts are unchanged."]
        messages.extend(alert["text"] for alert in snapshot["alerts"])
        if not snapshot["alerts"]:
            messages.append("No qualifying alerts in the available current data.")
        if snapshot["issues"]:
            messages.append("Unavailable inputs: " + "; ".join(snapshot["issues"]))
        await loading.edit_text("Preview ready.", parse_mode=None)
        await reply_long_message(update, "\n\n".join(messages), title="Special Alerts Preview", parse_mode=None)
    except Exception as exc:
        await loading.edit_text("Special alerts preview unavailable: " + type(exc).__name__, parse_mode=None)
