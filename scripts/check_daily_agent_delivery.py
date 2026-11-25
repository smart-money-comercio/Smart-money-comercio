"""Offline checks for daily-agent delivery, cache refresh and macro freshness."""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_watchlist_quotes import market_row
from src.jobs import daily_agent_job as daily
from src.jobs import daily_report_scheduler as scheduler
from src.commands import daily_agent_commands as commands
from src.intelligence import research_context
from src.reports import daily_report, morning_brief_intro


NOW = datetime(2026, 10, 20, 2, 16, tzinfo=timezone.utc)
SHORT_REPORT = """Smart Money Daily News Brief
Date: October 19, 2026
Generated: 2026-10-19 22:16:00 America/New_York
Market data: unavailable

Good evening.
Here is the news brief.

Market Update
Market data are unavailable.

Companies in Focus
Research rankings require confirmation.

Global and Defense Watch
This offline example includes no verified defense announcement. The research watch covers drones, cybersecurity and autonomy; funded demand and delivery timing would be required to establish a commercial development.

What's Ahead
Calendar evidence is unavailable.

What We're Watching
Check price, volume and original announcements.

Research Notes
Research only. Not financial advice.
REPORT_END"""

REPORT = """Smart Money Daily News Brief
Date: October 19, 2026
Generated: 2026-10-19 22:16:00 America/New_York
Market data: completed regular session 2026-10-19

Good evening.
The indexes in this offline example finished the regular session higher.

Market Update
Our indicator-based read in this offline example is constructive. At the completed regular-session close, the S&P 500 rose 0.33 percent and the Nasdaq Composite rose 0.39 percent. Portfolio lens: Improving index support may help growth exposure. Check whether company participation and volume support the move, and keep the next session's evidence separate from this completed-session snapshot.

Companies in Focus
Microsoft, Nvidia and Taiwan Semiconductor are on this fixture's research list. No new source-confirmed company report is included in the example, so no corporate development is being inferred from the index returns.

Global and Defense Watch
This offline example includes no verified defense announcement. The research watch covers drones, cybersecurity and autonomy; funded demand and delivery timing would be required to establish a commercial development.

What's Ahead
No publisher-confirmed upcoming release is included in this offline fixture. An event date would need an original publisher schedule before it could be narrated as a confirmed calendar entry.

What We're Watching
Our view: The next useful comparison is whether the broad indexes and the companies we follow continue to move in the same direction. Watch participation and the original company disclosures as they become available, and keep later evidence separate from this completed-session snapshot.

Research Notes
Research only. Not financial advice.
REPORT_END"""


def fresh_payload():
    return {"cached_at": NOW.timestamp(), "market_moves": [
        market_row("^GSPC", 0.33, NOW), market_row("^IXIC", 0.39, NOW),
        market_row("^RUT", 0.33, NOW), market_row("^VIX", -2.53, NOW),
        market_row("USO", 0.31, NOW), market_row("TLT", -0.38, NOW),
        market_row("GLD", 2.5, NOW)],
        "theme_summary": {"ranked_themes": [{"theme": "Inflation / Fed", "count": 1}]},
        "headlines": ["Fed policy is in focus."]}


class WorkflowChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="daily-agent-delivery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(daily, "STATUS_PATH", self.root / "status.json"))
        self.stack.enter_context(patch.dict(os.environ, {"SPECIAL_ALERT_STATE_FILE": str(self.root / "events.sqlite3")}))
        self.actions = []
        self.mocks = {}
        for name in ("refresh_morning_brief_step", "refresh_calendar_step", "refresh_news_intelligence", "refresh_alert_monitor",
                     "refresh_stockanalysis_top_names", "build_tradeplans_step", "build_allocation_step"):
            def action(name=name):
                self.actions.append(name)
                return name + " completed"
            self.mocks[name] = self.stack.enter_context(patch.object(daily, name, side_effect=action))
        def refresh_disclosures():
            self.actions.append("refresh_disclosures")
            return {"status": "limited", "detail": "SEC check current | Senate provider unavailable"}
        self.disclosures = self.stack.enter_context(patch("src.jobs.disclosure_refresh.refresh_due", side_effect=refresh_disclosures))
        def build():
            self.actions.append("build_daily_report_step")
            return REPORT
        self.build = self.stack.enter_context(patch.object(daily, "build_daily_report_step", side_effect=build))
        self.editor = self.stack.enter_context(patch("src.intelligence.news_editor.review_daily_edition", return_value="Edition evidence reviewed"))

    def test_live_run_refreshes_macro_cache_before_building_report(self):
        result = daily.run_daily_agent(False)
        self.assertTrue(result["success"])
        self.assertEqual(self.actions[0], "refresh_morning_brief_step")
        self.assertLess(self.actions.index("refresh_morning_brief_step"), self.actions.index("build_daily_report_step"))
        self.assertLess(self.actions.index("refresh_calendar_step"), self.actions.index("build_daily_report_step"))
        self.assertLess(self.actions.index("refresh_disclosures"), self.actions.index("build_daily_report_step"))
        refresh = next(step for step in result["steps"] if step["name"] == "Disclosure Source Refresh")
        self.assertEqual(refresh["status"], "limited")
        self.assertIn("Senate provider unavailable", refresh["detail"])

    def test_dry_run_skips_all_source_refreshes(self):
        result = daily.run_daily_agent(True)
        for name in ("refresh_morning_brief_step", "refresh_calendar_step", "refresh_news_intelligence", "refresh_alert_monitor", "refresh_stockanalysis_top_names"):
            self.mocks[name].assert_not_called()
        step = next(item for item in result["steps"] if item["name"] == "Morning Brief Refresh")
        self.assertEqual(step["status"], "skip")
        self.assertEqual(next(item for item in result["steps"] if item["name"] == "Calendar Review")["status"], "skip")
        self.disclosures.assert_not_called()
        self.assertEqual(next(item for item in result["steps"] if item["name"] == "Disclosure Source Refresh")["status"], "skip")

    def test_full_report_is_returned_once_and_not_saved_inside_workflow_steps(self):
        result = daily.run_daily_agent(False)
        self.assertEqual(result["report"], REPORT)
        stored = json.loads(daily.STATUS_PATH.read_text())
        self.assertEqual(stored["report_format"], "news")
        self.assertNotIn("report", stored)
        self.assertNotIn("REPORT_END", json.dumps(stored))
        step = next(item for item in stored["steps"] if item["name"] == "Daily Report Build")
        self.assertEqual(step["detail"], f"Daily report built ({len(REPORT)} chars).")
        text = daily.format_daily_agent_result(result)
        self.assertIn("PASS: Quality Review", text)
        self.assertLess(len(text), commands.MAX_TELEGRAM_CHARS)

    def test_company_review_runs_after_the_rankings_are_refreshed(self):
        with patch("src.intelligence.company_catalyst_context.daily_company_catalyst_review", return_value="Cached companies reviewed") as review:
            result = daily.run_daily_agent(False)
        review.assert_called_once()
        names = [step["name"] for step in result["steps"]]
        self.assertLess(names.index("Daily Report Build"), names.index("Company Catalyst Review"))
        self.assertLess(names.index("Company Catalyst Review"), names.index("Quality Review"))

    def test_dry_run_skips_company_review(self):
        with patch("src.intelligence.company_catalyst_context.daily_company_catalyst_review") as review:
            result = daily.run_daily_agent(True)
        review.assert_not_called()
        self.assertEqual(next(step["status"] for step in result["steps"] if step["name"] == "Company Catalyst Review"), "skip")

    def test_live_editor_review_uses_the_exact_report_and_is_critical(self):
        result = daily.run_daily_agent(False)
        self.editor.assert_called_once_with(REPORT)
        self.assertTrue(next(step["critical"] for step in result["steps"] if step["name"] == "News Editor Review"))

    def test_missing_editor_record_blocks_success(self):
        self.editor.side_effect = RuntimeError("No matching editorial record")
        result = daily.run_daily_agent(False)
        self.assertFalse(result["success"])
        self.assertIn("FAIL: News Editor Review", daily.format_daily_agent_result(result))

    def test_saved_legacy_report_detail_is_summarized_when_read(self):
        result = daily.run_daily_agent(True)
        next(item for item in result["steps"] if item["name"] == "Daily Report Build")["detail"] = REPORT
        text = daily.format_daily_agent_result(result)
        self.assertNotIn("REPORT_END", text)
        self.assertIn("PASS: Quality Review", text)
        self.assertLess(len(text), commands.MAX_TELEGRAM_CHARS)

    def test_source_refresh_failure_is_visible_and_does_not_block_report_build(self):
        self.mocks["refresh_morning_brief_step"].side_effect = RuntimeError("Current macro cache unavailable")
        result = daily.run_daily_agent(False)
        self.assertTrue(result["success"])
        text = daily.format_daily_agent_result(result)
        self.assertIn("FAIL: Morning Brief Refresh", text)
        self.assertIn("Current macro cache unavailable", text)
        self.assertIn("PASS: Quality Review", text)

    def test_short_narration_blocks_a_successful_daily_run(self):
        self.build.side_effect = lambda: SHORT_REPORT
        result = daily.run_daily_agent(False)
        self.assertFalse(result["success"])
        step = next(item for item in result["steps"] if item["name"] == "Quality Review")
        self.assertEqual(step["status"], "fail")
        from src.reports.daily_news_brief import validate_news_brief
        validation = validate_news_brief(SHORT_REPORT)
        self.assertEqual(validation["missing_headers"], [])
        self.assertTrue(validation["narration_errors"])

    def test_critical_build_failure_has_no_report_and_quality_review_fails(self):
        self.build.side_effect = RuntimeError("Report build failed")
        result = daily.run_daily_agent(False)
        self.assertFalse(result["success"])
        self.assertEqual(result["report"], "")
        text = daily.format_daily_agent_result(result)
        self.assertIn("FAIL: Daily Report Build", text)
        self.assertIn("FAIL: Quality Review", text)

    def test_verbose_failure_does_not_hide_final_checks(self):
        result = daily.run_daily_agent(False)
        result["steps"][0].update(status="fail", detail="Source failure " * 600)
        text = daily.format_daily_agent_result(result)
        self.assertLess(len(text), commands.MAX_TELEGRAM_CHARS)
        self.assertIn("PASS: Quality Review", text)


class TelegramChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        env = patch.dict(os.environ,{"DAILY_AGENT_DELIVERY_STATE_FILE":str(Path(temporary.name)/"delivery.json")})
        env.start();self.addCleanup(env.stop)

    def update(self):
        loading = SimpleNamespace(edit_text=AsyncMock())
        chat = SimpleNamespace(send_message=AsyncMock())
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=loading)), effective_chat=chat)
        return update, loading, chat

    def result(self):
        return {"success": True, "last_run": NOW.isoformat(), "report_characters": len(REPORT),
                "report": REPORT, "steps": [
                    {"name": "Daily Report Build", "status": "pass", "detail": REPORT},
                    {"name": "Quality Review", "status": "pass", "detail": "Quality validation passed"}]}

    async def test_manual_run_delivers_complete_report_once_and_short_status_separately(self):
        update, loading, chat = self.update()
        with patch.object(commands, "run_daily_agent", return_value=self.result()):
            await commands.rundailyagent_command(update, SimpleNamespace())
        status = loading.edit_text.await_args.args[0]
        self.assertIn("PASS: Quality Review", status)
        self.assertNotIn("Market Update", status)
        messages = [call.kwargs["text"] for call in chat.send_message.await_args_list]
        self.assertEqual(sum("Smart Money Daily News Brief" in text for text in messages), 1)
        self.assertEqual(sum("REPORT_END" in text for text in messages), 1)
        self.assertTrue(all(len(text) <= commands.MAX_TELEGRAM_CHARS for text in messages))

    async def test_long_workflow_sends_remaining_status_instead_of_dropping_it(self):
        update, loading, chat = self.update()
        result = self.result()
        result["steps"] = [{"name": "Source " + str(i), "status": "fail", "detail": "A lengthy source diagnostic " * 20} for i in range(25)] + result["steps"]
        with patch.object(commands, "run_daily_agent", return_value=result):
            await commands.rundailyagent_command(update, SimpleNamespace())
        messages = [loading.edit_text.await_args.args[0]] + [call.kwargs["text"] for call in chat.send_message.await_args_list]
        self.assertTrue(all(len(text) <= commands.MAX_TELEGRAM_CHARS for text in messages))
        self.assertIn("PASS: Quality Review", "\n".join(messages))
        self.assertEqual(sum("REPORT_END" in text for text in messages), 1)

    async def test_failed_run_does_not_deliver_a_success_report(self):
        update, loading, chat = self.update()
        result = self.result(); result["success"] = False
        with patch.object(commands, "run_daily_agent", return_value=result):
            await commands.rundailyagent_command(update, SimpleNamespace())
        self.assertIn("Status: FAIL", loading.edit_text.await_args.args[0])
        chat.send_message.assert_not_awaited()


class ReaderRefreshChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.now = datetime(2026, 10, 19, 17, tzinfo=timezone.utc)
        self.payload = {"cached_at": self.now.timestamp(), "market_moves": [
            market_row(symbol, -0.5, self.now) for symbol in ("^GSPC", "^IXIC", "^RUT")
        ]}
        self.clock = Mock(wraps=datetime); self.clock.now.return_value = self.now
        self.stack.enter_context(patch.object(morning_brief_intro, "datetime", self.clock))
        self.stack.enter_context(patch.object(morning_brief_intro.time, "time", return_value=self.now.timestamp()))
        self.monotonic = self.stack.enter_context(patch.object(morning_brief_intro.time, "monotonic", return_value=1000.0))
        self.stack.enter_context(patch.object(morning_brief_intro, "last_report_refresh", None))
        self.stack.enter_context(patch.object(morning_brief_intro, "load_morning_brief_cache", return_value=self.payload))
        self.refresh = self.stack.enter_context(patch.object(morning_brief_intro, "refresh_morning_brief_cache", return_value={"refreshed": True}))

    def test_recent_file_with_aging_live_quotes_refreshes_before_the_quotes_expire(self):
        self.payload["cached_at"] -= 7200
        self.payload["market_moves"] = [market_row(symbol, -0.5, self.now - timedelta(minutes=11))
                                       for symbol in ("^GSPC", "^IXIC", "^RUT")]
        self.assertEqual(len(research_context.market_quotes(self.payload, self.now)), 3)
        result = morning_brief_intro.ensure_morning_brief_cache_is_fresh(max_age_minutes=360)
        self.refresh.assert_called_once_with()
        self.assertEqual(result, {"refreshed": True})

    def test_expired_live_quotes_refresh_even_when_the_cache_file_is_recent(self):
        self.payload["market_moves"] = [market_row(symbol, -0.5, self.now - timedelta(minutes=25))
                                       for symbol in ("^GSPC", "^IXIC", "^RUT")]
        self.assertEqual(research_context.market_quotes(self.payload, self.now), {})
        morning_brief_intro.ensure_morning_brief_cache_is_fresh()
        self.refresh.assert_called_once_with()

    def test_current_core_quotes_reuse_the_cache_without_provider_requests(self):
        self.payload["cached_at"] -= 3600
        self.assertIs(morning_brief_intro.ensure_morning_brief_cache_is_fresh(), self.payload)
        self.refresh.assert_not_called()

    def test_missing_benchmark_retries_share_a_two_minute_interval(self):
        self.payload["market_moves"].pop()
        self.refresh.return_value = self.payload
        self.monotonic.side_effect = [1000.0, 1001.0, 1121.0]
        for _ in range(3):
            self.assertIs(morning_brief_intro.ensure_morning_brief_cache_is_fresh(), self.payload)
        self.assertEqual(self.refresh.call_count, 2)

    def test_forced_agent_refresh_bypasses_the_automatic_retry_interval(self):
        for _ in range(2):
            morning_brief_intro.ensure_morning_brief_cache_is_fresh(force_refresh=True)
        self.assertEqual(self.refresh.call_count, 2)

    def test_simultaneous_report_requests_share_one_incomplete_refresh(self):
        self.payload["market_moves"].pop()
        self.refresh.return_value = self.payload
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: morning_brief_intro.ensure_morning_brief_cache_is_fresh(), range(4)))
        self.refresh.assert_called_once_with()
        self.assertTrue(all(result is self.payload for result in results))

    def test_refresh_failure_preserves_the_original_clock_and_withholds_expired_prices(self):
        self.payload["cached_at"] -= 3600
        self.payload["market_moves"] = [market_row(symbol, -0.5, self.now - timedelta(minutes=25))
                                       for symbol in ("^GSPC", "^IXIC", "^RUT")]
        before = deepcopy(self.payload)
        self.refresh.side_effect = RuntimeError("source unavailable")
        result = morning_brief_intro.ensure_morning_brief_cache_is_fresh()
        self.assertEqual(self.payload, before)
        self.assertEqual(result["cached_at"], before["cached_at"])
        self.assertEqual(result["refresh_error"], "source unavailable")
        self.assertEqual(research_context.market_quotes(result, self.now), {})

    def test_valid_completed_session_quotes_do_not_need_an_intraday_refresh(self):
        self.payload.clear(); self.payload.update(fresh_payload())
        self.clock.now.return_value = NOW
        with patch.object(morning_brief_intro.time, "time", return_value=NOW.timestamp()):
            self.assertIs(morning_brief_intro.ensure_morning_brief_cache_is_fresh(), self.payload)
        self.refresh.assert_not_called()


class ScheduleChecks(unittest.TestCase):
    def registrations(self, **settings):
        app = SimpleNamespace(job_queue=Mock())
        with patch.dict(os.environ, {"TELEGRAM_DAILY_REPORT_CHAT_ID": "-123", **settings}, clear=True):
            scheduler.schedule_daily_report(app)
        return [call.kwargs for call in app.job_queue.run_daily.call_args_list]

    def test_both_times_run_every_day_in_the_market_zone(self):
        morning, evening = self.registrations()
        self.assertEqual([row["time"].strftime("%H:%M") for row in (morning, evening)], ["08:30", "17:30"])
        for row in (morning, evening):
            self.assertIs(row["callback"], scheduler.daily_report_job)
            self.assertEqual(row.get("days", tuple(range(7))), tuple(range(7)))
            self.assertEqual(str(row["time"].tzinfo), "America/New_York")
            self.assertEqual(row["job_kwargs"]["id"], row["name"])
            self.assertTrue(row["job_kwargs"]["replace_existing"])
        self.assertNotEqual(morning["name"], evening["name"])

    def test_real_cron_triggers_follow_new_york_through_both_clock_changes(self):
        from telegram.ext import Application
        from zoneinfo import ZoneInfo
        app = Application.builder().token("12345:offline").build()
        zone = ZoneInfo("America/New_York")
        with patch.dict(os.environ, {"TELEGRAM_DAILY_REPORT_CHAT_ID": "-123"}, clear=True):
            scheduler.schedule_daily_report(app)
        jobs = sorted(app.job_queue.jobs(), key=lambda job: job.name)
        self.assertEqual(len(jobs), 2)
        for job, hour in zip(jobs, (8, 17)):
            trigger = job.job.trigger
            for day in (datetime(2026,3,7,0,tzinfo=zone), datetime(2026,10,31,0,tzinfo=zone)):
                prior = None
                for offset in range(3):
                    at = trigger.get_next_fire_time(prior, day if prior is None else prior + timedelta(seconds=1))
                    self.assertEqual(at.astimezone(zone).date(), (day + timedelta(days=offset)).date())
                    self.assertEqual(at.astimezone(zone).strftime("%H:%M"), f"{hour:02d}:30")
                    prior = at

    def test_custom_slots_duplicate_time_disabled_and_missing_recipients(self):
        settings = {"TELEGRAM_DAILY_REPORT_TIME": "07:45", "TELEGRAM_DAILY_REPORT_EVENING_TIME": "18:15",
                    "TELEGRAM_DAILY_REPORT_TIMEZONE": "America/Chicago"}
        slots = self.registrations(**settings)
        self.assertEqual([str(row["time"])[:5] for row in slots], ["07:45", "18:15"])
        self.assertEqual(str(slots[1]["time"].tzinfo), "America/Chicago")
        settings["TELEGRAM_DAILY_REPORT_EVENING_TIME"] = "07:45"
        self.assertEqual(len(self.registrations(**settings)), 1)
        self.assertEqual(self.registrations(TELEGRAM_DAILY_REPORT_ENABLED="no"), [])
        self.assertEqual(self.registrations(TELEGRAM_DAILY_REPORT_CHAT_ID=""), [])

    def test_each_slot_runs_the_full_agent_and_sends_one_copy_per_recipient(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        morning, evening = self.registrations()
        values = [{"success": True, "report": "Morning edition"}, {"success": True, "report": "Evening edition"}]
        with patch.dict(os.environ, {"TELEGRAM_DAILY_REPORT_CHAT_ID": "4,4,5"}), \
                patch.object(scheduler, "utc_now", return_value=NOW), \
                patch.object(scheduler, "run_daily_agent", side_effect=values) as agent, \
                patch.object(scheduler, "confirm_watchlist_delivery") as confirm:
            for slot in (morning, evening):
                asyncio.run(slot["callback"](SimpleNamespace(bot=bot, job=SimpleNamespace(name=slot["name"]))))
        self.assertEqual(agent.call_count, 2)
        self.assertTrue(all(call.args == (False,) for call in agent.call_args_list))
        self.assertEqual([(c.kwargs["chat_id"], c.kwargs["text"]) for c in bot.send_message.await_args_list],
                         [(4,"Morning edition"), (5,"Morning edition"), (4,"Evening edition"), (5,"Evening edition")])
        self.assertEqual(confirm.call_count, 4)

    def test_failed_quality_check_withholds_brief_for_all_destinations(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(scheduler, "utc_now", return_value=NOW), \
                patch.object(scheduler, "get_daily_report_chat_ids", return_value=[1, 2]), \
                patch.object(scheduler, "run_daily_agent", return_value={"success": False, "report": "unchecked"}) as agent, \
                patch.object(scheduler, "confirm_watchlist_delivery") as confirm, self.assertLogs(scheduler.LOG, "ERROR"):
            asyncio.run(scheduler.daily_report_job(SimpleNamespace(bot=bot)))
        agent.assert_called_once_with(False)
        self.assertEqual([c.kwargs for c in bot.send_message.await_args_list],
                         [{"chat_id": chat, "text": "The Daily Brief is unavailable for this scheduled run."} for chat in (1, 2)])
        confirm.assert_not_called()

    def test_evening_weekends_refresh_the_day_specific_edition(self):
        evening = self.registrations()[1]
        for at in (datetime(2026,11,21,22,30,tzinfo=timezone.utc), datetime(2026,11,22,22,30,tzinfo=timezone.utc)):
            bot = SimpleNamespace(send_message=AsyncMock())
            with patch.object(scheduler, "utc_now", return_value=at), \
                    patch.object(scheduler, "get_daily_report_chat_ids", return_value=[1]), \
                    patch.object(scheduler, "build_weekend_delivery_report", return_value="Weekend edition") as build, \
                    patch.object(scheduler, "run_daily_agent") as weekday:
                asyncio.run(evening["callback"](SimpleNamespace(bot=bot, job=SimpleNamespace(name=evening["name"]))))
            build.assert_called_once_with(at, refresh=True)
            weekday.assert_not_called()
            self.assertEqual(bot.send_message.await_args.kwargs["text"], "Weekend edition")


class MacroFreshnessChecks(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(research_context, "utc_now", return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)

    def context(self, payload):
        with patch.object(daily_report, "load_morning_brief_payload", return_value=payload), patch.object(daily_report.time, "time", return_value=NOW.timestamp()):
            return daily_report.load_global_context()

    def test_ten_day_old_prices_and_headlines_do_not_become_current_macro_signals(self):
        payload = fresh_payload(); payload["cached_at"] -= 10 * 86400
        context = self.context(payload)
        self.assertEqual(context["headline_themes"], [])
        self.assertEqual(context["headline_examples"], [])
        self.assertEqual(context["gold"], 0)
        self.assertIs(context["_market_payload"], payload)
        self.assertEqual(daily_report.get_macro_pressure(context), "macro observations stale/unavailable")
        line = daily_report.build_market_moves_line(context, [])
        self.assertIn("S&P unavailable", line)
        self.assertNotIn("+0.33%", line)
        self.assertNotIn("safety/inflation", daily_report.get_macro_pressure(context))

    def test_future_cache_is_not_displayed_as_current_or_fresh(self):
        payload = fresh_payload(); payload["cached_at"] += 3600
        context = self.context(payload)
        self.assertNotIn("Fresh Morning Brief", context["regime"])
        self.assertEqual(context["headline_themes"], [])
        self.assertIn("S&P unavailable", daily_report.build_market_moves_line(context, []))

    def test_missing_or_invalid_cache_timestamp_withholds_numeric_moves(self):
        for stamp in (None, float("nan"), float("inf"), "today"):
            payload = fresh_payload(); payload["cached_at"] = stamp
            with self.subTest(stamp=stamp):
                context = self.context(payload)
                self.assertEqual(context["headline_themes"], [])
                self.assertNotIn("+0.33%", daily_report.build_market_moves_line(context, []))

    def test_fresh_moves_and_genuine_zero_remain_visible_with_missing_assets_unavailable(self):
        payload = fresh_payload()
        payload["market_moves"] = [market_row("^IXIC", 0.0, NOW), market_row("TLT", -0.38, NOW)]
        context = self.context(payload)
        line = daily_report.build_market_moves_line(context, [])
        self.assertIn("Nasdaq +0.00%", line)
        self.assertIn("TLT -0.38%", line)
        self.assertIn("VIX unavailable", line)
        self.assertIn("incomplete", daily_report.get_macro_pressure(context))

    def test_nonfinite_boolean_and_errored_rows_cannot_generate_pressure(self):
        for row in ({"symbol": "GLD", "move": float("nan")}, {"symbol": "GLD", "move": float("inf")},
                    {"symbol": "GLD", "move": True}, {"symbol": "GLD", "move": 9.0, "error": "unavailable"}):
            payload = fresh_payload()
            payload["market_moves"] = [item for item in payload["market_moves"] if item["symbol"] != "GLD"] + [row]
            with self.subTest(row=row):
                context = self.context(payload)
                self.assertEqual(context["gold"], 0)
                self.assertNotIn("safety/inflation", daily_report.get_macro_pressure(context))

    def test_fresh_valid_context_preserves_existing_macro_pressure_rules(self):
        context = self.context(fresh_payload())
        self.assertIn("safety/inflation hedge demand", daily_report.get_macro_pressure(context))
        self.assertIn("S&P +0.33%", daily_report.build_market_moves_line(context, []))

    def test_stale_macro_data_does_not_hide_independent_watchlist_movers(self):
        payload = fresh_payload(); payload["cached_at"] -= 10 * 86400
        movers = [{"symbol": "MSFT", "change_percent": -1.4}, {"symbol": "NVDA", "change_percent": 2.0}]
        line = daily_report.build_market_moves_line(self.context(payload), movers)
        self.assertIn("S&P unavailable", line)
        self.assertIn("NVDA strongest at +2.00%", line)
        self.assertIn("MSFT weakest at -1.40%", line)

    def test_refresh_step_forces_refresh_and_accepts_usable_fresh_cache(self):
        with patch.object(morning_brief_intro, "ensure_morning_brief_cache_is_fresh", return_value=fresh_payload()) as refresh:
            text = daily.refresh_morning_brief_step()
        refresh.assert_called_once_with(force_refresh=True)
        self.assertIn("cache refreshed", text)

    def test_failed_refresh_cannot_relabel_old_cache_or_empty_quotes_as_current(self):
        old = fresh_payload(); old["cached_at"] -= 10 * 86400; old["refresh_error"] = "source unavailable"
        cases = [old, {}, {"cached_at": NOW.timestamp(), "market_moves": [{"symbol": "^GSPC", "move": None}]}]
        for payload in cases:
            before = deepcopy(payload)
            with self.subTest(payload=payload), patch.object(morning_brief_intro, "ensure_morning_brief_cache_is_fresh", return_value=payload):
                with self.assertRaisesRegex(RuntimeError, "no usable current macro cache"):
                    daily.refresh_morning_brief_step()
            self.assertEqual(payload, before)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-socketpair", action="store_true")
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", portable_tcp_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    success = result.wasSuccessful() and not traffic["blocked"]
    if traffic["blocked"]:
        print(f"FAIL: {len(traffic['blocked'])} unexpected provider connections blocked")
    print(f"Daily Agent Delivery Check: {'PASS' if success else 'FAIL'} ({result.testsRun} tests)")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
