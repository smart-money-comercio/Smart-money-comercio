"""Offline checks for daily-agent delivery, cache refresh and macro freshness."""

from __future__ import annotations

import argparse
import asyncio
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
from src.commands import daily_agent_commands as commands
from src.intelligence import research_context
from src.reports import daily_report, morning_brief_intro


NOW = datetime(2026, 10, 20, 2, 16, tzinfo=timezone.utc)
REPORT = "Daily Brief\n" + "\n".join(daily.REQUIRED_DAILY_REPORT_TERMS) + "\n" + ("Report evidence. " * 400) + "REPORT_END"


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
        def build():
            self.actions.append("build_daily_report_step")
            return REPORT
        self.build = self.stack.enter_context(patch.object(daily, "build_daily_report_step", side_effect=build))

    def test_live_run_refreshes_macro_cache_before_building_report(self):
        result = daily.run_daily_agent(False)
        self.assertTrue(result["success"])
        self.assertEqual(self.actions[0], "refresh_morning_brief_step")
        self.assertLess(self.actions.index("refresh_morning_brief_step"), self.actions.index("build_daily_report_step"))
        self.assertLess(self.actions.index("refresh_calendar_step"), self.actions.index("build_daily_report_step"))

    def test_dry_run_skips_all_source_refreshes(self):
        result = daily.run_daily_agent(True)
        for name in ("refresh_morning_brief_step", "refresh_calendar_step", "refresh_news_intelligence", "refresh_alert_monitor", "refresh_stockanalysis_top_names"):
            self.mocks[name].assert_not_called()
        step = next(item for item in result["steps"] if item["name"] == "Morning Brief Refresh")
        self.assertEqual(step["status"], "skip")
        self.assertEqual(next(item for item in result["steps"] if item["name"] == "Calendar Review")["status"], "skip")

    def test_full_report_is_returned_once_and_not_saved_inside_workflow_steps(self):
        result = daily.run_daily_agent(False)
        self.assertEqual(result["report"], REPORT)
        stored = json.loads(daily.STATUS_PATH.read_text())
        self.assertNotIn("report", stored)
        self.assertNotIn("REPORT_END", json.dumps(stored))
        step = next(item for item in stored["steps"] if item["name"] == "Daily Report Build")
        self.assertEqual(step["detail"], f"Daily report built ({len(REPORT)} chars).")
        text = daily.format_daily_agent_result(result)
        self.assertIn("PASS: Quality Review", text)
        self.assertLess(len(text), commands.MAX_TELEGRAM_CHARS)

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
        self.assertNotIn("Daily Brief", status)
        messages = [call.kwargs["text"] for call in chat.send_message.await_args_list]
        self.assertEqual(sum("Daily Brief" in text for text in messages), 1)
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
