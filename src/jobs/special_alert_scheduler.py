"""Five-minute monitoring, separate from the existing daily/watchlist alerts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os

from src.config.special_alerts import settings
from src.intelligence import special_alert_store as store
from src.intelligence.special_alert_engine import evaluate
from src.intelligence.special_alert_sources import collect_inputs
from src.intelligence.special_alert_universe import company_universe
from src.jobs.watchlist_alert_scheduler import get_watchlist_alert_chat_ids, parse_chat_destinations


LOG = logging.getLogger(__name__)


def destinations() -> list:
    raw = os.getenv("TELEGRAM_SPECIAL_ALERT_CHAT_ID", "").strip()
    return list(dict.fromkeys(parse_chat_destinations(raw) if raw else get_watchlist_alert_chat_ids()))


def collect_snapshot() -> dict:
    now, config = datetime.now(timezone.utc), settings()
    coverage = company_universe(config, now)
    config = {**config, "symbols": coverage["symbols"]}
    source_status = {}
    observations, news, issues = collect_inputs(now, config, source_status=source_status)
    alerts = evaluate(observations, news, now, config)
    if alerts:
        try:
            from src.agents.analyst_agent import run_analyst_agent
            from src.scoring.scoring_engine import get_stock_scores
            scores = get_stock_scores()
            for alert in alerts:
                review = run_analyst_agent(scores, event_context=alert)
                alert["agent_review"] = review
                alert["text"] += "\n\n" + review
        except Exception as exc:
            issues.append("Agent review unavailable: " + type(exc).__name__)
            for alert in alerts:
                alert.setdefault("agent_review", "Agent review unavailable; review the sourced facts and validation commands.")
                if "Agent review\n" not in alert["text"]:
                    alert["text"] += "\n\n" + alert["agent_review"]
    return {"asof": now.isoformat(), "alerts": alerts, "issues": issues,
            "observations": observations, "news_items": len(news), "source_status": source_status,
            "coverage": coverage}


async def special_alert_job(context) -> None:
    config = settings()
    try:
        state = store.get_settings()
        chats = destinations()
        if not config["enabled"] or not state.get("enabled", True) or not chats:
            return
        snapshot = await asyncio.to_thread(collect_snapshot)
        # Check again after networking in case an admin paused during the scan.
        if not settings()["enabled"] or not store.get_settings().get("enabled", True):
            return
        store.record_snapshot(snapshot["alerts"], snapshot["observations"], datetime.now(timezone.utc).timestamp())
        sent, failed = 0, 0
        company_sent = dict.fromkeys(chats, 0)
        for alert in snapshot["alerts"]:
            for chat_id in chats:
                if alert["kind"] == "company" and company_sent[chat_id] >= 3:
                    continue
                now = datetime.now(timezone.utc).timestamp()
                if alert["expires"] < now:
                    continue
                if not settings()["enabled"] or not store.get_settings().get("enabled", True):
                    return
                if not store.claim(chat_id, alert, now):
                    continue
                try:
                    await context.bot.send_message(chat_id=chat_id, text=alert["text"],
                                                   parse_mode=None, disable_web_page_preview=True)
                except Exception as exc:
                    store.finish(chat_id, alert, now, False)
                    failed += 1
                    LOG.warning("Special alert delivery failed (%s)", type(exc).__name__)
                else:
                    store.finish(chat_id, alert, now, True)
                    sent += 1
                    if alert["kind"] == "company":
                        company_sent[chat_id] += 1
        store.save_settings(last_scan=snapshot["asof"], last_issues=snapshot["issues"],
                            last_candidates=len(snapshot["alerts"]), last_sent=sent, last_failed=failed,
                            last_source_status=snapshot.get("source_status", {}),
                            last_company_symbols=snapshot.get("coverage", {}).get("symbols", []),
                            last_quote_times={k: v["asof"] for k, v in snapshot["observations"].items()})
    except Exception as exc:
        LOG.exception("Special alert scan failed (%s)", type(exc).__name__)
        try:
            store.save_settings(last_issues=["Scan unavailable: " + type(exc).__name__])
        except Exception:
            LOG.error("Special alert state is unavailable")


def schedule_special_alerts(app) -> None:
    # Still schedule when paused so an admin can resume without restarting the bot.
    if not app.job_queue:
        LOG.warning("Special alerts not scheduled: JobQueue unavailable")
        return
    app.job_queue.run_repeating(special_alert_job, interval=settings()["interval"], first=30,
                               name="special-alert-monitor",
                               job_kwargs={"max_instances": 1, "coalesce": True, "misfire_grace_time": 60})
