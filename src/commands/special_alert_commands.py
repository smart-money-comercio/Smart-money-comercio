"""Status, read-only preview and owner controls for special alerts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.commands.admin_commands import is_admin
from src.config.special_alerts import settings
from src.intelligence import special_alert_store as store
from src.intelligence.special_alert_universe import company_universe
from src.jobs.special_alert_scheduler import collect_snapshot, destinations
from src.utils.telegram_messages import reply_long_message


def tesla_source_lines(source_status: dict) -> list[str]:
    if "TSLA news" not in source_status and "Tesla IR" not in source_status:
        return []
    return ["TSLA headlines: " + source_status.get("TSLA news", "not checked"),
            "Tesla confirmation source: " + source_status.get("Tesla IR", "not checked")]


def company_source_lines(source_status: dict, symbols: list[str]) -> list[str]:
    lines = tesla_source_lines(source_status)
    for symbol in symbols:
        if symbol == "TSLA":
            continue
        headline = source_status.get(symbol + " news", "not checked")
        official = source_status.get(symbol + " official", "not configured; headline coverage only")
        lines.append(f"{symbol}: headlines — {headline}; official — {official}")
    return lines


def status_report() -> str:
    config, state = settings(), store.get_settings()
    coverage = company_universe(config)
    active = config["enabled"] and state.get("enabled", True)
    from src.intelligence.ipo_monitor import issuers
    try:
        ipo_scope = ", ".join(row["name"] for row in issuers().values())
    except ValueError:
        ipo_scope = "configuration invalid"
    lines = ["🚨 Special Alerts", "Monitoring: " + ("ON" if active else "OFF"),
             f"Scan interval: {config['interval'] // 60} minutes · company news also after hours/weekends",
             "Market checks: regular session plus 20 minutes for delayed closing quotes",
             f"Destinations: {len(destinations())} configured", "",
             "AI IPO monitoring: " + ("ON" if config.get("ipo_enabled") else "OFF") + " · " + ipo_scope,
             f"IPO milestone window: {config.get('ipo_hours', 24):g} hours · original issuer/SEC evidence required",
             "AI IPO sources: " + state.get("last_source_status", {}).get("AI IPOs", "not scanned yet"),
             f"Selloff: S&P 500 -{config['sp_drop']:g}% / Nasdaq -{config['nasdaq_drop']:g}%",
             f"Severe: S&P 500 -{config['sp_severe']:g}% / Nasdaq -{config['nasdaq_severe']:g}%",
             f"Two negative sessions: S&P 500 -{config['sp_two_day']:g}% / Nasdaq -{config['nasdaq_two_day']:g}% compounded",
             "Core companies: " + (", ".join(coverage["core"]) or "none configured"),
             "Top opportunities: " + (", ".join(coverage["ranked"]) or "none added"),
             "Ranking coverage: " + coverage["ranking_status"],
             "Companies: " + (", ".join(coverage["symbols"]) or "none configured"),
             f"Maximum quote age: {config['max_quote_age'] / 60:g} minutes; news age: {config['news_hours']:g} hours",
             "Repeats: one level per market session; worsening severity and company confirmation can alert again.",
             "", "Last scan: " + state.get("last_scan", "not run yet"),
             f"Last scan deliveries: {state.get('last_sent', 0)} sent / {state.get('last_failed', 0)} failed",
             "Source status: " + ("; ".join(state.get("last_issues", [])) or "No recorded source errors"),
             *company_source_lines(state.get("last_source_status", {}), coverage["symbols"]),
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
        coverage = snapshot.get("coverage", {})
        if coverage:
            messages.append("Companies: " + ", ".join(coverage["symbols"]) + "\n" + coverage["ranking_status"])
        messages.extend(alert["text"] for alert in snapshot["alerts"])
        if not snapshot["alerts"]:
            messages.append("No qualifying alerts in the available current data.")
        if snapshot["issues"]:
            messages.append("Unavailable inputs: " + "; ".join(snapshot["issues"]))
        details = company_source_lines(snapshot.get("source_status", {}), coverage.get("symbols", settings()["symbols"]))
        if details:
            messages.append("\n".join(details))
        await loading.edit_text("Preview ready.", parse_mode=None)
        await reply_long_message(update, "\n\n".join(messages), title="Special Alerts Preview", parse_mode=None)
    except Exception as exc:
        await loading.edit_text("Special alerts preview unavailable: " + type(exc).__name__, parse_mode=None)
