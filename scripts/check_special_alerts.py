"""Offline behavioral checks for special events, selloffs and Telegram delivery."""

from __future__ import annotations

import asyncio
import argparse
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config.special_alerts import settings
from src.intelligence import special_alert_engine as engine
from src.intelligence import special_alert_sources as sources
from src.intelligence import special_alert_store as store
from src.jobs import special_alert_scheduler as job


NOW = datetime(2026, 10, 16, 18, tzinfo=timezone.utc)
_SOCKETPAIR_PERMISSION = threading.local()


@contextmanager
def offline_network_guard():
    """Block providers while allowing only socketpair's private loopback setup.

    Windows uses a local TCP connection inside socket.socketpair() to initialize
    asyncio's self-pipe. The permission is limited to that call and its thread;
    ordinary loopback requests, DNS lookups and external connects stay blocked.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    original_socketpair = socket.socketpair
    permission = _SOCKETPAIR_PERMISSION
    traffic = {"blocked": []}

    def allowed(address):
        if not getattr(permission, "socketpair", False):
            return False
        try:
            return isinstance(address, tuple) and ipaddress.ip_address(address[0]).is_loopback
        except (ValueError, TypeError, IndexError):
            return False

    def deny(operation):
        traffic["blocked"].append(operation)
        raise AssertionError("Offline tests must not access network providers")

    def connect(sock, address):
        if allowed(address):
            return original_connect(sock, address)
        deny("connect")

    def connect_ex(sock, address):
        if allowed(address):
            return original_connect_ex(sock, address)
        deny("connect_ex")

    def getaddrinfo(host, port, *args, **kwargs):
        if allowed((host, port)):
            return original_getaddrinfo(host, port, *args, **kwargs)
        deny("DNS")

    def socketpair(*args, **kwargs):
        previous = getattr(permission, "socketpair", False)
        permission.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            permission.socketpair = previous

    with patch.object(socket.socket, "connect", connect), patch.object(socket.socket, "connect_ex", connect_ex), patch.object(socket, "getaddrinfo", getaddrinfo), patch.object(socket, "socketpair", socketpair):
        yield traffic


def config():
    return {"enabled": True, "symbols": ["TSLA", "NVDA"], "interval": 300,
            "max_quote_age": 1200, "news_hours": 6, "sp_drop": 1.5, "nasdaq_drop": 2,
            "sp_severe": 3, "nasdaq_severe": 4, "sp_two_day": 3, "nasdaq_two_day": 4}


def chart(symbol="^GSPC", price=96):
    epochs = [int(datetime(2026, 10, day, 13, 30, tzinfo=timezone.utc).timestamp()) for day in (13, 14, 15, 16)]
    return {"chart": {"result": [{"meta": {
        "symbol": symbol, "regularMarketPrice": price, "regularMarketTime": (NOW - timedelta(minutes=1)).timestamp(),
        "chartPreviousClose": 80,  # range-start close must NEVER set the daily change
        "currentTradingPeriod": {"regular": {"start": epochs[-1], "end": datetime(2026, 10, 16, 20, tzinfo=timezone.utc).timestamp()}}
    }, "timestamp": epochs, "indicators": {"quote": [{"close": [100, 100, 98, 96]}]}}], "error": None}}


def observation(symbol="^GSPC", change=-2, two_day=-3.5, prior=-1.5):
    return {"symbol": symbol, "name": sources.INDEX_NAMES[symbol], "change": change,
            "two_day": two_day, "prior_change": prior, "price": 96, "asof": NOW.isoformat(),
            "session_date": "2026-10-16", "url": "https://finance.yahoo.com/quote/%5EGSPC/"}


def news(title="Tesla unveils new Roadster prototype", **overrides):
    return {"symbol": "TSLA", "title": title, "published": (NOW - timedelta(minutes=5)).isoformat(),
            "official": False, "url": "https://finance.yahoo.com/news/roadster", "source": "finance.yahoo.com", **overrides}


def alert():
    return engine.company_alert(news(), NOW, config())


class SourceChecks(unittest.TestCase):
    def test_daily_return_uses_prior_session_not_range_start(self):
        row = sources.chart_observation("^GSPC", chart(), NOW, config())
        self.assertAlmostEqual(row["change"], (96 / 98 - 1) * 100)
        self.assertAlmostEqual(row["two_day"], -4)
        self.assertAlmostEqual(row["prior_change"], -2)

    def test_quote_timestamp_is_required(self):
        value = chart(); value["chart"]["result"][0]["meta"].pop("regularMarketTime")
        with self.assertRaises(ValueError): sources.chart_observation("^GSPC", value, NOW, config())

    def test_stale_and_future_quotes_rejected(self):
        for delta in (-1201, 61):
            value = chart(); value["chart"]["result"][0]["meta"]["regularMarketTime"] = NOW.timestamp() + delta
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                sources.chart_observation("^GSPC", value, NOW, config())

    def test_nonfinite_and_zero_prices_rejected(self):
        for value in (None, 0, -1, "nan", float("inf"), True):
            with self.subTest(price=value), self.assertRaises(ValueError):
                sources.chart_observation("^GSPC", chart(price=value), NOW, config())

    def test_wrong_index_rejected(self):
        with self.assertRaises(ValueError): sources.chart_observation("^IXIC", chart(), NOW, config())

    def test_old_day_rejected_even_if_timestamp_recent(self):
        value = chart(); meta = value["chart"]["result"][0]["meta"]
        meta["currentTradingPeriod"]["regular"] = {"start": NOW.timestamp()-86400, "end": NOW.timestamp()+3600}
        # The regular window must itself start on the quote's session date.
        with self.assertRaises(ValueError): sources.chart_observation("^GSPC", value, NOW, config())

    def test_weekend_or_holiday_has_no_live_market_alert(self):
        with self.assertRaises(ValueError): sources.chart_observation("^GSPC", chart(), NOW + timedelta(days=1), config())

    def test_missing_previous_close_does_not_fabricate_daily_return(self):
        value = chart(); value["chart"]["result"][0]["indicators"]["quote"][0]["close"][2] = None
        with self.assertRaises(ValueError): sources.chart_observation("^GSPC", value, NOW, config())

    def test_missing_two_session_base_still_allows_daily_alert(self):
        value = chart(); value["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = None
        row = sources.chart_observation("^GSPC", value, NOW, config())
        self.assertIsNone(row["two_day"])
        self.assertLess(row["change"], -2)

    def test_closing_check_accepts_early_close_and_then_stops(self):
        value = chart(); meta = value["chart"]["result"][0]["meta"]
        close = NOW - timedelta(minutes=10)
        meta["currentTradingPeriod"]["regular"]["end"] = close.timestamp()
        meta["regularMarketTime"] = close.timestamp()
        self.assertIsNotNone(sources.chart_observation("^GSPC", value, NOW, config()))
        with self.assertRaises(ValueError): sources.chart_observation("^GSPC", value, NOW + timedelta(minutes=11), config())

    def test_news_parser_preserves_publication_and_validates_official_domain(self):
        feed = b'<rss><channel><item><title>Tesla unveils new Roadster</title><link>https://www.tesla.com/blog/roadster</link><pubDate>Fri, 16 Oct 2026 17:55:00 GMT</pubDate></item></channel></rss>'
        items = sources.parse_feed(feed, ["TSLA", "NVDA"], "feed")
        self.assertEqual(len(items), 1); self.assertTrue(items[0]["official"])
        self.assertEqual(items[0]["published"], "2026-10-16T17:55:00+00:00")
        fake = feed.replace(b"www.tesla.com", b"tesla.com.example.com")
        self.assertFalse(sources.parse_feed(fake, ["TSLA"], "feed")[0]["official"])

    def test_news_without_publication_or_with_unsafe_link_is_skipped(self):
        feed = b'<rss><item><title>Tesla unveils new Roadster</title><link>javascript:alert(1)</link><pubDate>Fri, 16 Oct 2026 17:55:00 GMT</pubDate></item></rss>'
        self.assertEqual(sources.parse_feed(feed, ["TSLA"], "feed"), [])
        self.assertEqual(sources.parse_feed(feed.replace(b"javascript:alert(1)", b"https://tesla.com/news").replace(b"Fri, 16 Oct 2026 17:55:00 GMT", b""), ["TSLA"], "feed"), [])

    def test_atom_feed_supported(self):
        feed = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Tesla unveils Roadster concept</title><link href="https://tesla.com/news"/><published>2026-10-16T17:55:00Z</published></entry></feed>'
        self.assertEqual(len(sources.parse_feed(feed, ["TSLA"], "feed")), 1)

    def test_source_failure_is_visible_and_does_not_invent_data(self):
        with patch.object(sources, "request_bytes", side_effect=OSError("offline")):
            quotes, articles, issues = sources.collect_inputs(NOW, config())
        self.assertEqual(quotes, {}); self.assertEqual(articles, []); self.assertTrue(issues)

    def test_empty_and_provider_error_charts_rejected(self):
        for value in ({}, {"chart": {"error": {"code": "Not Found"}, "result": None}}):
            with self.assertRaises(ValueError): sources.chart_observation("^GSPC", value, NOW, config())


class OfflineGuardChecks(unittest.TestCase):
    def test_windows_fallback_socketpair_can_exchange_bytes(self):
        with patch.object(socket, "socketpair", socket._fallback_socketpair), offline_network_guard() as traffic:
            left, right = socket.socketpair()
            try:
                left.settimeout(2); right.settimeout(2)
                left.sendall(b"self-pipe")
                self.assertEqual(right.recv(16), b"self-pipe")
            finally:
                left.close(); right.close()
        self.assertEqual(traffic["blocked"], [])

    def test_asyncio_starts_and_closes_with_windows_socketpair(self):
        async def local_task():
            await asyncio.sleep(0)
            return await asyncio.to_thread(lambda: "ready")
        with patch.object(socket, "socketpair", socket._fallback_socketpair), offline_network_guard() as traffic:
            self.assertEqual(asyncio.run(local_task()), "ready")
        self.assertEqual(traffic["blocked"], [])

    def test_external_connects_remain_blocked(self):
        with offline_network_guard() as traffic:
            with socket.socket() as sock:
                with self.assertRaises(AssertionError): sock.connect(("203.0.113.1", 443))
        self.assertEqual(traffic["blocked"], ["connect"])

    def test_connect_ex_cannot_bypass_the_guard(self):
        with offline_network_guard() as traffic:
            with socket.socket() as sock:
                with self.assertRaises(AssertionError): sock.connect_ex(("203.0.113.1", 443))
        self.assertEqual(traffic["blocked"], ["connect_ex"])

    def test_dns_cannot_contact_a_provider(self):
        with offline_network_guard() as traffic:
            with self.assertRaises(AssertionError): socket.getaddrinfo("offline-check.invalid", 443)
        self.assertEqual(traffic["blocked"], ["DNS"])

    def test_loopback_permission_is_limited_to_socketpair(self):
        with offline_network_guard() as traffic:
            with socket.socket() as sock:
                with self.assertRaises(AssertionError): sock.connect(("127.0.0.1", 9))
        self.assertEqual(traffic["blocked"], ["connect"])

    def test_socketpair_context_does_not_allow_external_addresses(self):
        def invalid_pair():
            with socket.socket() as sock:
                sock.connect(("203.0.113.1", 443))
        with patch.object(socket, "socketpair", invalid_pair), offline_network_guard() as traffic:
            with self.assertRaises(AssertionError): socket.socketpair()
        self.assertEqual(traffic["blocked"], ["connect"])

    def test_socketpair_permission_does_not_leak_to_worker_threads(self):
        errors = []
        def worker():
            try:
                with socket.socket() as sock: sock.connect(("127.0.0.1", 9))
            except AssertionError:
                errors.append("blocked")
        def simulated_pair():
            thread = threading.Thread(target=worker)
            thread.start(); thread.join(timeout=2)
            if thread.is_alive(): raise RuntimeError("worker did not finish")
            return "internal setup"
        with patch.object(socket, "socketpair", simulated_pair), offline_network_guard() as traffic:
            self.assertEqual(socket.socketpair(), "internal setup")
        self.assertEqual(errors, ["blocked"])
        self.assertEqual(traffic["blocked"], ["connect"])


class RuleChecks(unittest.TestCase):
    def test_releasing_new_concepts_is_a_qualifying_event(self):
        self.assertIsNotNone(engine.company_alert(news("Tesla releases new concepts and prototypes"), NOW, config()))
    def test_company_must_be_actor_not_incidental_stock_mention(self):
        self.assertIsNone(engine.company_alert(news("Nvidia unveils new chip while Tesla shares fall"), NOW, config()))
        self.assertIsNone(engine.company_alert(news("Tesla shares fall as Nvidia unveils new chip"), NOW, config()))
    def test_concept_is_not_claimed_as_production(self):
        result = alert()
        self.assertIn("Concept / product reveal", result["text"])
        self.assertIn("headline only", result["text"])
        self.assertNotIn("Production / deliveries reported", result["text"])

    def test_official_announcement_is_distinguished_from_news(self):
        result = engine.company_alert(news(official=True), NOW, config())
        self.assertEqual(result["level"], 2); self.assertIn("Company announcement", result["text"])

    def test_rumor_speculation_and_fan_renders_ignored(self):
        for title in ("Tesla may unveil new Roadster", "Tesla reportedly reveals Roadster", "Tesla new Roadster revealed?", "Tesla fans unveil Roadster rendering", "Tesla could launch robotaxi"):
            with self.subTest(title=title): self.assertIsNone(engine.company_alert(news(title), NOW, config()))

    def test_competitor_reveal_is_not_assigned_to_tesla(self):
        self.assertIsNone(engine.company_alert(news("Tesla rival unveils new car concept"), NOW, config()))

    def test_generic_market_and_nonproduct_news_ignored(self):
        for title in ("Tesla stock falls 5%", "Tesla announces earnings date", "Tesla reveals its quarterly profit", "Tesla Roadster prototype looks nice"):
            with self.subTest(title=title): self.assertIsNone(engine.company_alert(news(title), NOW, config()))

    def test_old_future_or_undated_news_is_ignored(self):
        for published in (None, (NOW + timedelta(minutes=1)).isoformat(), (NOW - timedelta(hours=7)).isoformat()):
            self.assertIsNone(engine.company_alert(news(published=published), NOW, config()))

    def test_article_age_uses_original_publication_not_import_time(self):
        item = news(published=(NOW - timedelta(days=20)).isoformat(), fetched_at=NOW.isoformat())
        self.assertIsNone(engine.company_alert(item, NOW, config()))

    def test_repeated_headlines_group_same_product(self):
        a = alert(); b = engine.company_alert(news("Tesla reveals redesigned Roadster car"), NOW, config())
        self.assertEqual(a["key"], b["key"])

    def test_robotaxi_and_cybercab_headlines_group_together(self):
        a = engine.company_alert(news("Tesla unveils new robotaxi Cybercab"), NOW, config())
        b = engine.company_alert(news("Tesla reveals Cybercab robot"), NOW, config())
        self.assertEqual(a["key"], b["key"])

    def test_planned_event_and_real_production_are_labeled(self):
        self.assertIn("Event announced", engine.company_alert(news("Tesla will unveil Roadster car"), NOW, config())["text"])
        self.assertIn("Production / deliveries reported", engine.company_alert(news("Tesla begins production of Roadster"), NOW, config())["text"])

    def test_other_configured_company_product_alerts(self):
        self.assertIsNotNone(engine.company_alert(news("Nvidia unveils Rubin chip", symbol="NVDA"), NOW, config()))
        self.assertIsNone(engine.company_alert(news("Microsoft unveils new cloud platform", symbol="MSFT"), NOW, config()))

    def test_daily_thresholds_and_severe_escalation(self):
        for symbol, threshold in (("^GSPC", 1.5), ("^IXIC", 2)):
            with self.subTest(symbol=symbol):
                self.assertIsNone(engine.market_alert({symbol: observation(symbol, -threshold + .01, 0)}, NOW, config()))
                self.assertEqual(engine.market_alert({symbol: observation(symbol, -threshold, 0)}, NOW, config())["level"], 1)
        result = engine.market_alert({"^GSPC": observation(change=-3)}, NOW, config())
        self.assertEqual(result["level"], 2)

    def test_two_consecutive_small_losses_can_trigger(self):
        result = engine.market_alert({"^GSPC": observation(change=-1.4, two_day=-3.1, prior=-1.72)}, NOW, config())
        self.assertIn("two consecutive trading sessions", result["text"])

    def test_two_day_net_drop_with_positive_session_is_not_persistent_selloff(self):
        self.assertIsNone(engine.market_alert({"^GSPC": observation(change=.2, two_day=-4, prior=-4.2)}, NOW, config()))
        self.assertIsNone(engine.market_alert({"^GSPC": observation(change=-1.3, two_day=-4, prior=.2)}, NOW, config()))

    def test_missing_data_not_reported_as_zero_or_cause(self):
        self.assertIsNone(engine.market_alert({}, NOW, config()))
        result = engine.market_alert({"^GSPC": observation()}, NOW, config())
        self.assertIn("^IXIC: unavailable", result["text"])
        self.assertIn("Cause: Not established", result["text"])
        self.assertNotIn("+0.00%", result["text"])

    def test_mixed_market_sessions_are_rejected(self):
        row = observation("^IXIC"); row["session_date"] = "2026-10-15"
        self.assertIsNone(engine.market_alert({"^GSPC": observation(), "^IXIC": row}, NOW, config()))

    def test_fresh_news_can_alert_on_weekends_after_hours(self):
        sunday = NOW + timedelta(days=2)
        self.assertIsNotNone(engine.company_alert(news(published=sunday.isoformat()), sunday, config()))

    def test_duplicate_news_collapses_and_official_evidence_wins(self):
        result = engine.evaluate({}, [news(), news(official=True)], NOW, config())
        self.assertEqual(len(result), 1); self.assertEqual(result[0]["level"], 2)

    def test_market_alert_prioritized_over_company_news(self):
        result = engine.evaluate({"^GSPC": observation()}, [news()], NOW, config())
        self.assertEqual(result[0]["kind"], "market")
        self.assertLess(len(result[0]["text"]), 3200)

    def test_malformed_environment_has_bounded_safe_defaults(self):
        with patch.dict(os.environ, {"SPECIAL_ALERT_INTERVAL_SECONDS": "nan", "SPECIAL_ALERT_SP500_DROP": "-5", "SPECIAL_ALERT_SYMBOLS": "tsla,../secret,TSLA,NVDA", "SPECIAL_ALERT_MAX_QUOTE_AGE_SECONDS": "inf"}):
            value = settings()
            self.assertEqual(value["interval"], 300); self.assertEqual(value["sp_drop"], 1.5)
            self.assertEqual(value["symbols"], ["TSLA", "NVDA"]); self.assertEqual(value["max_quote_age"], 1200)


class DeliveryChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="special-alert-check-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "state.sqlite3"
        self.env = patch.dict(os.environ, {"SPECIAL_ALERT_STATE_FILE": str(self.path), "SPECIAL_ALERTS_ENABLED": "true"})
        self.env.start(); self.addCleanup(self.env.stop)
        clock = patch.object(job, "datetime").start()
        clock.now.return_value = NOW
        self.addCleanup(patch.stopall)
        self.snapshot = {"asof": NOW.isoformat(), "alerts": [alert()], "issues": [], "observations": {}}

    def test_success_survives_module_reload_and_is_per_destination(self):
        a = alert(); self.assertTrue(store.claim(1, a, NOW.timestamp()))
        store.finish(1, a, NOW.timestamp(), True)
        importlib.reload(store)
        self.assertFalse(store.claim(1, a, NOW.timestamp()+60))
        self.assertTrue(store.claim(2, a, NOW.timestamp()+60))

    def test_failure_can_retry_and_lease_stops_concurrent_sends(self):
        a = alert(); self.assertTrue(store.claim(1, a, NOW.timestamp()))
        self.assertFalse(store.claim(1, a, NOW.timestamp()+1))
        store.finish(1, a, NOW.timestamp(), False)
        self.assertTrue(store.claim(1, a, NOW.timestamp()+2))

    def test_abandoned_claim_expires(self):
        a = alert(); self.assertTrue(store.claim(1, a, NOW.timestamp()))
        self.assertTrue(store.claim(1, a, NOW.timestamp()+121))

    def test_severity_and_official_confirmation_bypass_repeat_suppression(self):
        a = alert(); store.finish(1, a, NOW.timestamp(), True)
        b = {**a, "level": 2}
        self.assertTrue(store.claim(1, b, NOW.timestamp()+1))
        store.finish(1, b, NOW.timestamp()+1, True)
        self.assertFalse(store.claim(1, a, NOW.timestamp()+2))

    async def run_job(self, bot):
        with patch.object(job, "destinations", return_value=[1, 2]), patch.object(job, "collect_snapshot", return_value=self.snapshot):
            await job.special_alert_job(SimpleNamespace(bot=bot))

    async def test_successful_destination_not_resent_when_other_destination_fails(self):
        async def send(**kwargs):
            if kwargs["chat_id"] == 2: raise RuntimeError("simulated Telegram failure")
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
        await self.run_job(bot)
        await self.run_job(bot)
        self.assertEqual([c.kwargs["chat_id"] for c in bot.send_message.await_args_list], [1, 2, 2])
        self.assertEqual(store.get_settings()["last_failed"], 1)

    async def test_paused_monitor_does_no_networking_or_delivery(self):
        store.save_settings(enabled=False)
        with patch.object(job, "collect_snapshot") as collect:
            await self.run_job(SimpleNamespace(send_message=AsyncMock()))
            collect.assert_not_called()

    async def test_no_destination_does_no_networking(self):
        with patch.object(job, "destinations", return_value=[]), patch.object(job, "collect_snapshot") as collect:
            await job.special_alert_job(SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock())))
            collect.assert_not_called()

    async def test_alert_expiring_during_scan_is_not_delivered(self):
        self.snapshot["alerts"][0]["expires"] = NOW.timestamp() - 1
        bot = SimpleNamespace(send_message=AsyncMock())
        await self.run_job(bot)
        bot.send_message.assert_not_awaited()

    async def test_company_burst_is_bounded_without_starving_unsent_events(self):
        self.snapshot["alerts"] = [engine.company_alert(news("Tesla unveils new " + product + " prototype"), NOW, config())
                                   for product in ("Roadster", "Optimus", "Cybercab", "Semi", "Cybertruck")]
        bot = SimpleNamespace(send_message=AsyncMock())
        await self.run_job(bot)
        self.assertEqual(bot.send_message.await_count, 6)  # three per configured destination
        await self.run_job(bot)
        self.assertEqual(bot.send_message.await_count, 10)

    async def test_environment_master_switch_is_obeyed(self):
        with patch.dict(os.environ, {"SPECIAL_ALERTS_ENABLED": "false"}), patch.object(job, "collect_snapshot") as collect:
            await self.run_job(SimpleNamespace(send_message=AsyncMock()))
            collect.assert_not_called()

    async def test_preview_does_not_send_to_channel_or_consume_receipts(self):
        from src.commands import special_alert_commands as commands
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock()))))
        with patch.object(commands, "collect_snapshot", return_value=self.snapshot):
            await commands.specialalerts_command(update, SimpleNamespace(args=["preview"]))
        self.assertTrue(store.claim(1, alert(), NOW.timestamp()))
        self.assertIn("Preview only", update.message.reply_text.await_args_list[-1].kwargs["text"])

    async def test_only_admin_in_private_chat_can_pause(self):
        from src.commands import special_alert_commands as commands
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=5, type="private"), message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "is_admin", return_value=False):
            await commands.specialalerts_command(update, SimpleNamespace(args=["off"]))
        self.assertNotIn("enabled", store.get_settings())
        with patch.object(commands, "is_admin", return_value=True):
            update.effective_chat.type = "group"
            await commands.specialalerts_command(update, SimpleNamespace(args=["off"]))
            self.assertNotIn("enabled", store.get_settings())
            update.effective_chat.type = "private"
            await commands.specialalerts_command(update, SimpleNamespace(args=["off"]))
            self.assertFalse(store.get_settings()["enabled"])

    def test_scheduler_uses_frequent_nonoverlapping_job(self):
        app = SimpleNamespace(job_queue=Mock())
        job.schedule_special_alerts(app)
        call = app.job_queue.run_repeating.call_args
        self.assertEqual(call.kwargs["interval"], 300)
        self.assertEqual(call.kwargs["job_kwargs"]["max_instances"], 1)
        self.assertTrue(call.kwargs["job_kwargs"]["coalesce"])

    def test_destination_override_and_fallback(self):
        with patch.dict(os.environ, {"TELEGRAM_SPECIAL_ALERT_CHAT_ID": "1,1,@alerts"}):
            self.assertEqual(job.destinations(), [1, "@alerts"])
        with patch.dict(os.environ, {"TELEGRAM_SPECIAL_ALERT_CHAT_ID": ""}), patch.object(job, "get_watchlist_alert_chat_ids", return_value=[4]):
            self.assertEqual(job.destinations(), [4])

    def test_registered_telegram_command_uses_real_callback(self):
        with patch("openai.OpenAI"):
            from src.commands.register_commands import register_commands
        from src.commands.special_alert_commands import specialalerts_command
        from src.config.command_catalog import get_all_commands
        app = Mock(); register_commands(app)
        handlers = [c.args[0] for c in app.add_handler.call_args_list if "specialalerts" in c.args[0].commands]
        self.assertEqual(len(handlers), 1); self.assertIs(handlers[0].callback, specialalerts_command)
        self.assertTrue(any(cmd.startswith("/specialalerts") for cmd, _ in get_all_commands()))

    def test_entrypoint_schedules_monitor(self):
        import ast
        tree = ast.parse((ROOT / "src/bot.py").read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertTrue(any(node.func.id == "schedule_special_alerts" for node in calls))


class AgentIntegrationChecks(unittest.TestCase):
    setUp = DeliveryChecks.setUp

    def enrich(self):
        from src.agents import analyst_agent
        from src.scoring import scoring_engine
        stocks = [{"ticker": "TSLA", "final_score": 65, "category": "Growth / AI", "risk_label": "Elevated"}]
        before = deepcopy(stocks)
        with patch.object(job, "datetime") as clock, patch.object(job, "settings", return_value=config()), patch.object(job, "collect_inputs", return_value=({}, [news()], [])), patch.object(scoring_engine, "get_stock_scores", return_value=stocks), patch.object(analyst_agent, "run_analyst_agent", wraps=analyst_agent.run_analyst_agent) as agent:
            clock.now.return_value = NOW
            result = job.collect_snapshot()
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(agent.call_args.kwargs["event_context"]["evidence"]["title"], news()["title"])
        self.assertEqual(stocks, before)
        return result

    def test_alert_monitor_invokes_existing_analyst_agent_without_changing_scores(self):
        result = self.enrich()
        self.assertIn("Agent review", result["alerts"][0]["text"])
        self.assertIn("Score Risk: Elevated", result["alerts"][0]["text"])
        self.assertIn("Setup Risk:", result["alerts"][0]["text"])

    def test_agent_unavailable_still_allows_factual_alert(self):
        from src.agents import analyst_agent
        from src.scoring import scoring_engine
        with patch.object(job, "datetime") as clock, patch.object(job, "settings", return_value=config()), patch.object(job, "collect_inputs", return_value=({}, [news()], [])), patch.object(scoring_engine, "get_stock_scores", return_value=[]), patch.object(analyst_agent, "run_analyst_agent", side_effect=RuntimeError("unavailable")):
            clock.now.return_value = NOW
            result = job.collect_snapshot()
        self.assertEqual(len(result["alerts"]), 1)
        self.assertIn("Agent review unavailable", result["alerts"][0]["text"])
        self.assertTrue(result["issues"])

    def test_agent_distinguishes_source_confirmation_and_missing_score_coverage(self):
        from src.agents.analyst_agent import review_special_event
        result = review_special_event(alert(), [])
        self.assertIn("confirmation pending", result["interpretation"])
        self.assertIn("coverage unavailable", result["model_context"][0])
        self.assertFalse(result["score_changes"])

    def test_partial_stock_coverage_does_not_create_a_setup_risk(self):
        from src.agents.analyst_agent import review_special_event
        result = review_special_event(alert(), [{"ticker": "TSLA"}])
        self.assertIn("Score Risk: Unavailable; Setup Risk: Unavailable", result["model_context"][0])

    def test_market_agent_flags_exposure_without_predicting_cause(self):
        from src.agents.analyst_agent import review_special_event
        event = engine.market_alert({"^GSPC": observation()}, NOW, config())
        result = review_special_event(event, [{"ticker": "MSFT", "category": "Growth / AI", "final_score": 87, "risk_label": "Controlled"}])
        self.assertIn("MSFT", result["symbols"])
        self.assertIn("does not establish the cause", result["interpretation"])

    def test_events_and_assessments_persist_independently_of_delivery(self):
        event = self.enrich()["alerts"][0]
        store.record_snapshot([event], {}, NOW.timestamp())
        saved = store.recent_events(NOW.timestamp())[0]
        self.assertEqual(saved["agent_review"], event["agent_review"])
        self.assertEqual(saved["evidence"], event["evidence"])
        self.assertTrue(store.claim(1, event, NOW.timestamp()))

    def test_repeated_scans_do_not_increase_evidence_count(self):
        event = self.enrich()["alerts"][0]
        for index in range(5): store.record_snapshot([event], {}, NOW.timestamp() + index)
        self.assertEqual(len(store.recent_events(NOW.timestamp() + 5)), 1)

    def test_recovered_market_clears_live_risk_and_preserves_dated_history(self):
        event = engine.market_alert({"^GSPC": observation()}, NOW, config())
        store.record_snapshot([event], {}, NOW.timestamp())
        healthy = {s: observation(s, .2, .4, .2) for s in ("^GSPC", "^IXIC")}
        store.record_snapshot([], healthy, NOW.timestamp() + 60)
        self.assertEqual(store.recent_events(NOW.timestamp()+60), [])
        saved = store.recent_events(NOW.timestamp()+60, active_only=False)
        self.assertEqual(len(saved), 1); self.assertFalse(saved[0]["currently_active"])

    def test_source_failure_does_not_mislabel_market_as_recovered(self):
        event = engine.market_alert({"^GSPC": observation()}, NOW, config())
        store.record_snapshot([event], {}, NOW.timestamp())
        store.record_snapshot([], {}, NOW.timestamp()+60)
        self.assertTrue(store.recent_events(NOW.timestamp()+60))
        self.assertFalse(store.recent_events(NOW.timestamp()+1201))

    def test_stale_event_never_becomes_fresh_by_rescanning(self):
        event = alert(); store.record_snapshot([event], {}, NOW.timestamp())
        store.record_snapshot([event], {}, NOW.timestamp()+7*3600)
        self.assertFalse(store.recent_events(NOW.timestamp()+7*3600))

    def test_provider_exposes_current_event_to_integrated_ai_context(self):
        from src.intelligence import special_alert_context as context
        from src.intelligence import intelligence_context_providers as providers
        from src.intelligence.intelligence_context_registry import get_registered_context_providers
        event = self.enrich()["alerts"][0]; store.record_snapshot([event], {}, NOW.timestamp())
        with patch.object(context, "datetime") as clock:
            clock.now.return_value = NOW
            block = context.special_alert_context_provider()
        self.assertTrue(block.metadata["agent_integrated"])
        self.assertIn("Roadster", block.signal)
        self.assertEqual(block.themes, [])
        self.assertIn(context.special_alert_context_provider, get_registered_context_providers())

    def test_expired_events_have_no_live_context_votes(self):
        from src.intelligence import special_alert_context as context
        store.record_snapshot([alert()], {}, NOW.timestamp())
        with patch.object(context, "datetime") as clock:
            clock.now.return_value = NOW + timedelta(days=1)
            self.assertIsNone(context.special_alert_context_provider())

    def test_daily_agent_reads_events_without_fetching_or_sending(self):
        from src.intelligence import special_alert_context as context
        event = self.enrich()["alerts"][0]; store.record_snapshot([event], {}, NOW.timestamp())
        with patch.object(context, "datetime") as clock, patch.object(sources, "request_bytes", side_effect=AssertionError("must use cache")):
            clock.now.return_value = NOW
            self.assertIn("1 active sourced events", context.daily_agent_event_review())
        self.assertIn('"Special Alerts Agent", daily_agent_event_review', (ROOT / "src/jobs/daily_agent_job.py").read_text())

    def test_daily_report_keeps_agent_evidence_after_final_formatting(self):
        from src.intelligence.special_alert_context import attach_daily_special_alerts
        from src.reports.report_quality import validate_daily_report_quality, REQUIRED_HEADERS, split_report_sections
        event = self.enrich()["alerts"][0]; store.record_snapshot([event], {}, NOW.timestamp())
        bodies = {header: "Available." for header in REQUIRED_HEADERS}
        bodies.update({"Smart Money Summary": "Signal: Mixed.\nImplication: Review.\nValidation: Confirm.", "What Changed Today": "• Leadership changed."})
        text = "Generated: 2026-10-16 14:00:00 America/New_York\nGood afternoon.\n\n" + "\n\n".join(header + "\n" + body for header, body in bodies.items())
        output = attach_daily_special_alerts(text, 7600, NOW)
        self.assertIn("Agent event:", output); self.assertIn("Roadster", output)
        self.assertIn("Special Alerts Agent: active.", output)
        self.assertLessEqual(len(output), 7600)
        risk = next(lines for header, lines in split_report_sections(output) if header == "Risk Notes")
        self.assertLessEqual(len([line for line in risk if line.strip()]), 4)
        self.assertTrue(validate_daily_report_quality(output)["passes"])

    def test_report_budget_cannot_produce_false_active_label(self):
        from src.intelligence.special_alert_context import attach_daily_special_alerts
        store.record_snapshot([alert()], {}, NOW.timestamp())
        text = "Intelligence Used Today\nA\n\nRisk Notes\nB\n\nSmart Money Summary\nC"
        self.assertEqual(attach_daily_special_alerts(text, len(text), NOW), text)

    def test_report_and_manual_command_entrypoints_consume_shared_agent_context(self):
        for relative in ("src/reports/scorecard.py", "src/reports/tradeplan_report.py", "src/commands/analyst_commands.py"):
            text = (ROOT / relative).read_text(encoding="utf-8-sig")
            self.assertIn("build_event_review", text)
        self.assertIn("attach_daily_special_alerts(final_report.strip()", (ROOT / "src/reports/daily_report.py").read_text())

    def test_delivered_scorecard_and_tradeplan_include_the_same_event_review(self):
        from src.intelligence import special_alert_context as context
        from src.reports import tradeplan_report
        from src.reports import scorecard as card_module
        with patch("openai.OpenAI"):
            from src.commands import market_commands
        event = self.enrich()["alerts"][0]; store.record_snapshot([event], {}, NOW.timestamp())
        stock = {"ticker": "TSLA", "final_score": 65, "category": "Growth / AI", "risk_label": "Elevated"}
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(context, "datetime") as clock, patch.object(market_commands, "get_stock_scores", return_value=[stock]), patch.object(market_commands, "fetch_quotes_for_symbols", return_value={}), patch.object(tradeplan_report, "find_stock", return_value=stock), patch.object(card_module, "build_headline_impact_summary", return_value="Offline headline fixture"):
            clock.now.return_value = NOW
            asyncio.run(market_commands.scorecard(update, SimpleNamespace(args=["TSLA"])))
            card = update.message.reply_text.await_args.args[0]
            plan = tradeplan_report.build_tradeplan_report("TSLA")
        for text in (card, plan):
            self.assertIn("Special Alerts Agent", text)
            self.assertIn("Roadster", text)
            self.assertIn("confirmation pending", text)
            self.assertIn("Score Risk: Elevated", text)

    def test_active_analyst_command_includes_saved_agent_event(self):
        from src.intelligence import special_alert_context as context
        with patch("openai.OpenAI"):
            from src.commands import analyst_commands as commands
        event = self.enrich()["alerts"][0]; store.record_snapshot([event], {}, NOW.timestamp())
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock()))))
        with patch.object(context, "datetime") as clock, patch.object(commands, "build_analyst_intelligence_report", return_value="Consensus fixture"), patch.object(commands, "build_stockanalysis_analyst_overlay", return_value="Analyst overlay fixture"), patch.object(commands, "edit_or_reply_long_message", new_callable=AsyncMock) as deliver:
            clock.now.return_value = NOW
            asyncio.run(commands.analyst_command(update, SimpleNamespace(args=["TSLA"])))
        self.assertIn("Roadster", deliver.await_args.kwargs["text"])
        self.assertIn("Agent interpretation:", deliver.await_args.kwargs["text"])

    def test_daily_agent_workflow_runs_the_event_review_step(self):
        from src.intelligence import special_alert_context as context
        from src.jobs import daily_agent_job as daily
        event = self.enrich()["alerts"][0]; store.record_snapshot([event], {}, NOW.timestamp())
        with patch.object(context, "datetime") as clock, patch.object(daily, "STATUS_PATH", self.path.parent / "daily.json"), patch.object(daily, "build_tradeplans_step", return_value="Fixture plans"), patch.object(daily, "build_allocation_step", return_value="Fixture allocation"), patch.object(daily, "build_daily_report_step", return_value="Fixture report"), patch.object(daily, "validate_daily_report", return_value="Quality fixture"):
            clock.now.return_value = NOW
            result = daily.run_daily_agent(dry_run=True)
        step = next(step for step in result["steps"] if step["name"] == "Special Alerts Agent")
        self.assertEqual(step["status"], "pass"); self.assertIn("Roadster", step["detail"])

    def test_history_distinguishes_expired_context(self):
        from src.commands import special_alert_commands as commands
        event = alert(); store.record_snapshot([event], {}, NOW.timestamp())
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(commands, "datetime") as clock:
            clock.now.return_value = NOW + timedelta(hours=7)
            asyncio.run(commands.specialalerts_command(update, SimpleNamespace(args=["history"])))
        text = update.message.reply_text.await_args.kwargs["text"]
        self.assertIn("Historical context:", text)
        self.assertIn("Roadster", text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-socketpair", action="store_true",
                        help="Exercise every test with the TCP socketpair path used on Windows.")
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket, "socketpair", socket._fallback_socketpair))
        traffic = stack.enter_context(offline_network_guard())
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    success = result.wasSuccessful() and not traffic["blocked"]
    if traffic["blocked"]:
        print(f"FAIL: {len(traffic['blocked'])} unexpected network-provider attempts were blocked.")
    mode = "; Windows socketpair path" if args.windows_socketpair else ""
    print(f"Special Alerts Check: {'PASS' if success else 'FAIL'} ({result.testsRun} tests{mode})")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
