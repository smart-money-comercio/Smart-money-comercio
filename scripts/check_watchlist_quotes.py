"""Offline behavioral checks for dated watchlist quotes and daily return consumers."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.commands import watchlist_commands as watchlist
from src.reports import daily_report
from src.reports import morning_brief_intro
from src.intelligence import research_context
from src.utils import yahoo_quote
from src.utils.yahoo_quote import QuoteDataError, parse_regular_quote


UTC = timezone.utc
NOW = datetime(2026, 10, 20, 3, tzinfo=UTC)


def instant(day, hour, minute=0, second=0, month=10):
    return datetime(2026, month, day, hour, minute, second, tzinfo=UTC)


def result(symbol="TEST", price=101):
    return {"meta": {"symbol": symbol, "regularMarketPrice": price,
                     "regularMarketTime": instant(19, 20, second=1).timestamp(),
                     "chartPreviousClose": 120, "previousClose": 130,
                     "exchangeTimezoneName": "America/New_York", "currency": "USD",
                     "instrumentType": "EQUITY", "exchangeName": "NMS",
                     "currentTradingPeriod": {"regular": {"start": instant(19, 13, 30).timestamp(), "end": instant(19, 20).timestamp()}}},
            "timestamp": [instant(day, 13, 30).timestamp() for day in (13, 14, 15, 16, 19)],
            "indicators": {"quote": [{"close": [110, 108, 104, 100, price], "volume": [100, 200, 300, 400, 500]}]}}


def market_row(symbol, move, clock=NOW):
    """Synthetic dated cache evidence, independent of the production adapter."""
    from zoneinfo import ZoneInfo
    day = clock.astimezone(ZoneInfo("America/New_York")).date()
    start = datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC)
    end = start.replace(hour=20, minute=0)
    previous = day - timedelta(days=3 if day.weekday() == 0 else 1)
    previous_stamp = start.replace(year=previous.year, month=previous.month, day=previous.day)
    evidence = {"meta": {"symbol": symbol, "regularMarketPrice": 100 * (1 + move / 100),
                         "regularMarketTime": min(clock, end).timestamp(),
                         "exchangeTimezoneName": "America/New_York",
                         "currentTradingPeriod": {"regular": {"start": start.timestamp(), "end": end.timestamp()}}},
                "timestamp": [previous_stamp.timestamp(), start.timestamp()],
                "indicators": {"quote": [{"close": [100, None]}]}}
    return {"symbol": symbol, "move": move, "quote_evidence": evidence}


class QuoteChecks(unittest.TestCase):
    def test_daily_return_uses_dated_previous_close_even_when_range_metadata_disagrees(self):
        quote = parse_regular_quote("TEST", result(), NOW)
        self.assertAlmostEqual(quote["change_percent"], 1)
        self.assertEqual(quote["previous_close"], 100)
        self.assertEqual(quote["change"], 1)
        self.assertEqual(quote["session_date"], "2026-10-19")
        self.assertEqual(quote["previous_session_date"], "2026-10-16")

    def test_changing_chart_range_baseline_cannot_change_the_daily_return(self):
        for baseline in (1, 120, 999, None):
            value = result(); value["meta"]["chartPreviousClose"] = baseline; value["meta"]["previousClose"] = baseline
            with self.subTest(baseline=baseline):
                self.assertAlmostEqual(parse_regular_quote("TEST", value, NOW)["change_percent"], 1)

    def test_after_hours_keeps_completed_session_and_original_quote_time(self):
        quote = parse_regular_quote("TEST", result(), NOW)
        self.assertEqual(quote["quote_timing"], "completed_session")
        self.assertEqual(quote["asof"], "2026-10-19T20:00:01+00:00")
        self.assertEqual(quote["volume"], 500)

    def test_intraday_quote_uses_prior_completed_session_close(self):
        value = result(); value["meta"]["regularMarketTime"] = instant(19, 17, 59).timestamp()
        quote = parse_regular_quote("TEST", value, instant(19, 18))
        self.assertEqual(quote["quote_timing"], "regular_session")
        self.assertAlmostEqual(quote["change_percent"], 1)

    def test_stale_intraday_quote_is_unavailable(self):
        value = result(); value["meta"]["regularMarketTime"] = instant(19, 17, 30).timestamp()
        with self.assertRaisesRegex(QuoteDataError, "stale"):
            parse_regular_quote("TEST", value, instant(19, 18))

    def test_missing_regular_price_is_not_replaced_with_an_undated_close(self):
        value = result(); value["meta"].pop("regularMarketPrice")
        with self.assertRaisesRegex(QuoteDataError, "price or timestamp"):
            parse_regular_quote("TEST", value, NOW)

    def test_missing_regular_timestamp_is_not_replaced_with_fetch_time(self):
        value = result(); value["meta"].pop("regularMarketTime")
        with self.assertRaisesRegex(QuoteDataError, "price or timestamp"):
            parse_regular_quote("TEST", value, NOW)

    def test_nonfinite_boolean_and_nonpositive_prices_are_rejected(self):
        for price in (None, 0, -1, True, float("nan"), float("inf"), 10 ** 500):
            with self.subTest(price=str(price)[:30]), self.assertRaises(QuoteDataError):
                parse_regular_quote("TEST", result(price=price), NOW)

    def test_wrong_instrument_is_not_used_for_requested_ticker(self):
        with self.assertRaisesRegex(QuoteDataError, "instrument"):
            parse_regular_quote("TEST", result("OTHER"), NOW)

    def test_missing_or_invalid_latest_prior_close_does_not_fall_back_to_an_older_day(self):
        for price in (None, 0, -1, True, float("nan")):
            value = result(); value["indicators"]["quote"][0]["close"][-2] = price
            with self.subTest(price=price), self.assertRaisesRegex(QuoteDataError, "prior-session close"):
                parse_regular_quote("TEST", value, NOW)

    def test_missing_history_is_unavailable_even_when_metadata_has_previous_close(self):
        value = result(); value["timestamp"] = []
        with self.assertRaisesRegex(QuoteDataError, "prior-session close"):
            parse_regular_quote("TEST", value, NOW)

    def test_source_history_order_does_not_change_the_selected_session(self):
        value = result()
        for key in ("close", "volume"):
            value["indicators"]["quote"][0][key].reverse()
        value["timestamp"].reverse()
        self.assertAlmostEqual(parse_regular_quote("TEST", value, NOW)["change_percent"], 1)

    def test_future_timestamp_and_very_old_completed_quote_are_rejected(self):
        value = result(); value["meta"]["regularMarketTime"] = (NOW + timedelta(seconds=61)).timestamp()
        with self.assertRaisesRegex(QuoteDataError, "future"):
            parse_regular_quote("TEST", value, NOW)
        with self.assertRaisesRegex(QuoteDataError, "stale"):
            parse_regular_quote("TEST", result(), NOW + timedelta(days=4))

    def test_previous_day_quote_cannot_stand_in_for_current_regular_session(self):
        value = result(); value["meta"]["regularMarketTime"] = instant(16, 20).timestamp()
        with self.assertRaisesRegex(QuoteDataError, "Current regular-session"):
            parse_regular_quote("TEST", value, instant(19, 18))

    def test_weekend_and_holiday_upcoming_schedule_can_use_last_completed_session(self):
        value = result(price=100)
        value["meta"]["regularMarketTime"] = instant(16, 20).timestamp()
        value["timestamp"] = value["timestamp"][:-1]
        for key in ("close", "volume"):
            value["indicators"]["quote"][0][key] = value["indicators"]["quote"][0][key][:-1]
        quote = parse_regular_quote("TEST", value, instant(18, 18))
        self.assertEqual(quote["session_date"], "2026-10-16")
        self.assertEqual(quote["previous_session_date"], "2026-10-15")
        value["meta"]["currentTradingPeriod"]["regular"] = {"start": instant(20, 13, 30).timestamp(), "end": instant(20, 20).timestamp()}
        self.assertEqual(parse_regular_quote("TEST", value, instant(19, 18))["session_date"], "2026-10-16")

    def test_old_session_metadata_is_not_labelled_current_on_a_later_trading_day(self):
        value = result(); value["meta"]["regularMarketTime"] = instant(16, 20).timestamp()
        value["meta"]["currentTradingPeriod"]["regular"] = {"start": instant(16, 13, 30).timestamp(), "end": instant(16, 20).timestamp()}
        with self.assertRaisesRegex(QuoteDataError, "metadata is outdated"):
            parse_regular_quote("TEST", value, instant(19, 18))

    def test_early_close_and_one_second_closing_timestamp_are_supported(self):
        value = result(); value["meta"]["regularMarketTime"] = instant(19, 17, second=1).timestamp()
        value["meta"]["currentTradingPeriod"]["regular"]["end"] = instant(19, 17).timestamp()
        self.assertAlmostEqual(parse_regular_quote("TEST", value, instant(19, 18))["change_percent"], 1)

    def test_exchange_timezone_handles_dst_without_fixed_utc_open_hours(self):
        value = result()
        value["meta"]["regularMarketTime"] = instant(3, 21, second=1, month=11).timestamp()
        value["meta"]["currentTradingPeriod"]["regular"] = {"start": instant(3, 14, 30, month=11).timestamp(), "end": instant(3, 21, month=11).timestamp()}
        value["timestamp"] = [instant(day, 14, 30, month=11).timestamp() for day in (2, 3)]
        value["indicators"]["quote"][0] = {"close": [100, 101], "volume": [400, 500]}
        quote = parse_regular_quote("TEST", value, instant(4, 3, month=11))
        self.assertEqual(quote["previous_session_date"], "2026-11-02")
        self.assertAlmostEqual(quote["change_percent"], 1)

    def test_missing_or_invalid_exchange_timezone_is_unavailable(self):
        for zone in (None, "Invalid/Unknown"):
            value = result(); value["meta"]["exchangeTimezoneName"] = zone
            with self.subTest(zone=zone), self.assertRaisesRegex(QuoteDataError, "timezone"):
                parse_regular_quote("TEST", value, NOW)

    def test_missing_current_volume_does_not_use_previous_session_volume(self):
        value = result(); value["indicators"]["quote"][0]["volume"][-1] = None
        self.assertIsNone(parse_regular_quote("TEST", value, NOW)["volume"])

    def test_input_observation_is_not_modified(self):
        value = result(); before = deepcopy(value)
        parse_regular_quote("TEST", value, NOW)
        self.assertEqual(value, before)


class ConsumerChecks(unittest.TestCase):
    def test_http_adapter_uses_dated_parser_and_retains_clear_validation_errors(self):
        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        response = MagicMock(); response.__enter__.return_value = response
        payload = {"chart": {"result": [result()], "error": None}}
        with patch.object(yahoo_quote, "datetime", FixedDatetime), patch.object(watchlist.urllib.request, "urlopen", return_value=response):
            response.read.return_value = json.dumps(payload).encode()
            quote = watchlist.fetch_chart_quote("TEST")
            self.assertTrue(quote["ok"])
            self.assertAlmostEqual(quote["change_percent"], 1)
            payload["chart"]["result"][0]["meta"].pop("regularMarketTime")
            response.read.return_value = json.dumps(payload).encode()
            quote = watchlist.fetch_chart_quote("TEST")
            self.assertFalse(quote["ok"])
            self.assertIn("timestamp unavailable", quote["error"])

    def test_corrected_daily_returns_drive_breadth_and_tone_without_forcing_a_market_view(self):
        quotes = {symbol: parse_regular_quote(symbol, result(symbol, price), NOW) for symbol, price in (("AAA", 102), ("BBB", 101))}
        movers = daily_report.collect_watchlist_movers(list(quotes), quotes)
        self.assertEqual(daily_report.build_market_tone(movers), "Risk-on / bullish")
        for price in (98, 99):
            quotes = {"AAA": parse_regular_quote("AAA", result("AAA", price), NOW)}
            movers = daily_report.collect_watchlist_movers(list(quotes), quotes)
            self.assertEqual(daily_report.build_market_tone(movers), "Risk-off / bearish")

    def test_report_snapshot_exposes_quote_date_and_regular_session_basis(self):
        quote = parse_regular_quote("TEST", result(), NOW)
        movers = daily_report.collect_watchlist_movers(["TEST"], {"TEST": quote})
        text = daily_report.build_market_snapshot(["TEST"], movers)
        self.assertIn("Scope: watchlist regular-session returns", text)
        self.assertIn("Quote session: 2026-10-19", text)
        self.assertIn("Quote timestamps (UTC): 2026-10-19T20:00:01+00:00", text)
        self.assertIn("1 quoted", text)
        self.assertNotIn("1 live", text)

    def test_failed_and_nonfinite_quotes_are_not_counted_in_breadth(self):
        quotes = {"BAD": {"ok": False, "price": 100, "change_percent": 5},
                  "NAN": {"ok": True, "price": 100, "change_percent": float("nan")}}
        self.assertEqual(daily_report.collect_watchlist_movers(list(quotes), quotes), [])

    def test_older_session_is_not_mixed_into_a_newer_daily_snapshot(self):
        quote = parse_regular_quote("TEST", result(), NOW)
        old = {**quote, "symbol": "OLD", "session_date": "2026-10-16", "change_percent": -20}
        movers = daily_report.collect_watchlist_movers(["TEST", "OLD"], {"TEST": quote, "OLD": old})
        self.assertEqual([item["symbol"] for item in movers], ["TEST"])


class BackdropQuoteChecks(unittest.TestCase):
    def setUp(self):
        self.clock = NOW
        owner = self
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.clock.astimezone(tz) if tz else owner.clock.replace(tzinfo=None)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(morning_brief_intro, "datetime", Clock))
        self.stack.enter_context(patch.object(yahoo_quote, "datetime", Clock))
        self.stack.enter_context(patch.object(research_context, "utc_now", side_effect=lambda: self.clock))

    def fetch(self, value):
        with patch.object(morning_brief_intro, "request_text", return_value=json.dumps({"chart": {"result": [value], "error": None}})):
            return morning_brief_intro.get_asset_move(value["meta"]["symbol"])

    def payload(self, *rows):
        return {"cached_at": self.clock.timestamp(), "market_moves": list(rows)}

    def test_missing_today_bar_cannot_turn_yesterdays_gain_into_todays_return(self):
        value = result("MSFT", 99.7)
        value["indicators"]["quote"][0]["close"] = [110, 108, 99.167, 100, None]
        self.assertAlmostEqual(100 * (100 / 99.167 - 1), 0.84, places=2)
        row = self.fetch(value)
        self.assertEqual(row["move"], -0.3)
        self.assertEqual(row["session_date"], "2026-10-19")
        self.assertEqual(row["asof"], "2026-10-19T20:00:01+00:00")
        self.assertIn("MSFT -0.30%", research_context.market_check(self.payload(row), self.clock, "MSFT"))

    def test_watchlist_and_backdrop_use_the_same_return_when_the_daily_bar_disagrees(self):
        value = result("MSFT", 99.7)
        value["indicators"]["quote"][0]["close"][-1] = 105
        row = self.fetch(value)
        quote = parse_regular_quote("MSFT", value, self.clock)
        self.assertEqual(row["move"], round(quote["change_percent"], 2))
        self.assertEqual(research_context.market_observations(self.payload(row)), {"MSFT": -0.3})

    def test_missing_prior_close_does_not_collapse_to_an_older_bar(self):
        value = result(); value["indicators"]["quote"][0]["close"][-2] = None
        row = self.fetch(value)
        self.assertIsNone(row["move"])
        self.assertIn("QuoteDataError", row["error"])

    def test_missing_price_or_original_time_does_not_fall_back_to_history(self):
        for field in ("regularMarketPrice", "regularMarketTime"):
            value = result(); value["meta"].pop(field)
            with self.subTest(field=field): self.assertIsNone(self.fetch(value)["move"])

    def test_fresh_fetch_cannot_make_an_old_quote_current(self):
        value = result(); value["meta"]["regularMarketTime"] = (self.clock - timedelta(days=8)).timestamp()
        self.assertIsNone(self.fetch(value)["move"])

    def test_stale_intraday_quote_is_unavailable_on_fetch_and_cached_read(self):
        self.clock = instant(19, 18)
        value = result(); value["meta"]["regularMarketTime"] = instant(19, 17, 50).timestamp()
        row = self.fetch(value)
        self.assertEqual(row["move"], 1)
        self.clock = instant(19, 18, 15)
        self.assertIsNone(self.fetch(value)["move"])
        self.assertEqual(research_context.market_observations(self.payload(row)), {})

    def test_fresh_cache_timestamp_cannot_revalidate_stale_quote_evidence(self):
        row = self.fetch(result())
        self.clock += timedelta(days=8)
        text = research_context.market_check(self.payload(row), self.clock)
        self.assertIn("unavailable", text)

    def test_old_completed_session_is_withheld_after_the_next_open(self):
        row = self.fetch(result("^IXIC"))
        self.clock = instant(20, 13)
        self.assertIn("Nasdaq +1.00%", research_context.market_check(self.payload(row), self.clock))
        self.clock = instant(20, 14)
        self.assertIn("unavailable", research_context.market_check(self.payload(row), self.clock))

    def test_legacy_undated_cache_cannot_supply_a_stock_or_index_return(self):
        rows = [{"symbol": symbol, "move": 0.84} for symbol in ("MSFT", "^IXIC", "TLT")]
        payload = self.payload(*rows)
        self.assertEqual(research_context.market_observations(payload), {})
        self.assertIn("unavailable", research_context.market_check(payload, self.clock, "MSFT"))
        self.assertIsNone(morning_brief_intro.get_market_move(rows, "^IXIC"))
        self.assertIsNone(morning_brief_intro.get_move_from_cache(rows, "MSFT"))

    def test_tampered_return_is_withheld_in_every_cache_consumer(self):
        row = self.fetch(result("MSFT", 99.7)); row["move"] = 0.84
        self.assertEqual(research_context.market_observations(self.payload(row)), {})
        self.assertIsNone(morning_brief_intro.get_market_move([row], "MSFT"))
        self.assertIsNone(morning_brief_intro.get_move_from_cache([row], "MSFT"))

    def test_one_stale_asset_does_not_hide_independent_valid_quotes(self):
        good = self.fetch(result("MSFT", 99.7)); bad = self.fetch(result("TLT"))
        bad["quote_evidence"]["meta"]["regularMarketTime"] = (self.clock - timedelta(days=8)).timestamp()
        text = research_context.market_check(self.payload(good, bad), self.clock, "MSFT")
        self.assertIn("MSFT -0.30%", text)
        self.assertNotIn("TLT +", text)

    def test_backdrop_distinguishes_cache_time_from_the_quote_session_and_time(self):
        row = self.fetch(result("MSFT", 99.7))
        text = research_context.market_check(self.payload(row), self.clock, "MSFT")
        self.assertIn("10-20 03:00 UTC cache", text)
        self.assertIn("Regular-session returns: 2026-10-19", text)
        self.assertIn("earliest quote 10-19 20:00 UTC", text)

    def test_genuine_zero_is_valid_with_dated_source_evidence(self):
        row = self.fetch(result("TLT", 100))
        self.assertIn("TLT +0.00%", research_context.market_check(self.payload(row), self.clock))

    def test_json_cache_round_trip_preserves_original_evidence_without_network(self):
        row = self.fetch(result("MSFT", 99.7))
        payload = json.loads(json.dumps(self.payload(row)))
        before = deepcopy(payload)
        with patch.object(morning_brief_intro, "request_text", side_effect=AssertionError("No cache-side fetch")):
            self.assertEqual(research_context.market_observations(payload), {"MSFT": -0.3})
        self.assertEqual(payload, before)

    def test_wrong_instrument_and_malformed_evidence_are_withheld(self):
        row = self.fetch(result("MSFT"))
        for evidence in (None, [], {}, {"meta": None}, result("OTHER")):
            with self.subTest(evidence=evidence):
                self.assertEqual(research_context.market_observations(self.payload({**row, "quote_evidence": evidence})), {})

    def test_five_day_move_uses_chronological_dated_bars_and_current_regular_price(self):
        value = result("MSFT", 99.7)
        first = self.fetch(value)
        value["timestamp"].reverse()
        value["indicators"]["quote"][0]["close"].reverse()
        second = self.fetch(value)
        self.assertEqual(first["week_move"], second["week_move"])
        self.assertEqual(first["week_move"], round(100 * (99.7 / 110 - 1), 2))


class IndexClosingChecks(unittest.TestCase):
    setUp = BackdropQuoteChecks.setUp
    fetch = BackdropQuoteChecks.fetch
    payload = BackdropQuoteChecks.payload

    def index(self, symbol="^GSPC", minutes=45):
        value = result(symbol)
        value["meta"].update(instrumentType="INDEX", hasPrePostMarketData=False,
                             dataGranularity="1d", priceHint=2,
                             regularMarketTime=(instant(19, 20) + timedelta(minutes=minutes)).timestamp())
        value["indicators"]["quote"][0]["close"][-1] = 101.0003
        return value

    def test_delayed_cash_index_closing_updates_are_supported_for_all_four_indexes(self):
        for symbol, minutes in (("^GSPC", 45), ("^IXIC", 76), ("^RUT", 30), ("^DJI", 50)):
            with self.subTest(symbol=symbol):
                quote = parse_regular_quote(symbol, self.index(symbol, minutes), self.clock)
                self.assertAlmostEqual(quote["change_percent"], 1)
                self.assertTrue(quote["closing_quote_update"])
                self.assertEqual(quote["quote_timing"], "completed_session")

    def test_original_after_close_source_timestamp_is_retained(self):
        value = self.index("^IXIC", 76)
        quote = parse_regular_quote("^IXIC", value, self.clock)
        self.assertEqual(quote["asof"], "2026-10-19T21:16:00+00:00")
        self.assertEqual(quote["session_date"], "2026-10-19")
        self.assertEqual(quote["previous_session_date"], "2026-10-16")

    def test_missing_or_invalid_current_daily_close_cannot_corroborate_the_update(self):
        for close in (None, True, 0, -1, float("nan"), float("inf")):
            value = self.index(); value["indicators"]["quote"][0]["close"][-1] = close
            with self.subTest(close=close), self.assertRaises(QuoteDataError):
                parse_regular_quote("^GSPC", value, self.clock)

    def test_price_disagreement_is_rejected_at_the_sources_reported_precision(self):
        value = self.index(); value["indicators"]["quote"][0]["close"][-1] = 101.01
        with self.assertRaises(QuoteDataError):
            parse_regular_quote("^GSPC", value, self.clock)

    def test_prior_day_price_match_cannot_replace_the_missing_current_bar(self):
        value = self.index(); value["timestamp"].pop()
        value["indicators"]["quote"][0]["close"] = [110, 108, 104, 101]
        with self.assertRaises(QuoteDataError):
            parse_regular_quote("^GSPC", value, self.clock)

    def test_duplicate_current_session_bars_are_ambiguous(self):
        value = self.index(); value["timestamp"].append(instant(19, 13, 31).timestamp())
        value["indicators"]["quote"][0]["close"].append(101)
        with self.assertRaises(QuoteDataError):
            parse_regular_quote("^GSPC", value, self.clock)

    def test_missing_or_wrong_index_metadata_does_not_enable_later_timestamps(self):
        for field, invalid in (("instrumentType", "ETF"), ("hasPrePostMarketData", True),
                               ("hasPrePostMarketData", None), ("dataGranularity", "1m"),
                               ("priceHint", None), ("priceHint", True), ("priceHint", 9)):
            value = self.index(); value["meta"][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(QuoteDataError):
                parse_regular_quote("^GSPC", value, self.clock)

    def test_equities_etfs_and_other_indices_keep_the_existing_closing_time_rule(self):
        for symbol, kind in (("MSFT", "EQUITY"), ("TLT", "ETF"), ("OTHER", "INDEX")):
            value = self.index(symbol); value["meta"]["instrumentType"] = kind
            with self.subTest(symbol=symbol), self.assertRaises(QuoteDataError):
                parse_regular_quote(symbol, value, self.clock)

    def test_future_source_times_remain_unavailable_even_with_a_matching_close(self):
        value = self.index(); value["meta"]["regularMarketTime"] = (self.clock + timedelta(minutes=5)).timestamp()
        with self.assertRaisesRegex(QuoteDataError, "future"):
            parse_regular_quote("^GSPC", value, self.clock)

    def test_old_index_session_cannot_become_current_after_the_next_market_open(self):
        value = self.index(); self.clock = instant(20, 14)
        with self.assertRaisesRegex(QuoteDataError, "metadata is outdated"):
            parse_regular_quote("^GSPC", value, self.clock)

    def test_the_first_twenty_minutes_after_close_keep_the_existing_freshness_rule(self):
        value = self.index(minutes=10); self.clock = instant(19, 20, 15)
        with self.assertRaisesRegex(QuoteDataError, "Current regular-session"):
            parse_regular_quote("^GSPC", value, self.clock)

    def test_special_alert_monitor_still_rejects_late_index_updates(self):
        from src.config.special_alerts import settings
        from src.intelligence.special_alert_sources import chart_observation
        for minutes in (10, 45):
            value = self.index(minutes=minutes)
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                chart_observation("^GSPC", {"chart": {"result": [value]}},
                                  instant(19, 20, minutes + 1), settings())

    def test_morning_brief_and_cache_reader_preserve_the_required_source_metadata(self):
        row = self.fetch(self.index("^IXIC", 76))
        self.assertEqual(row["move"], 1)
        evidence = row["quote_evidence"]["meta"]
        self.assertIs(evidence["hasPrePostMarketData"], False)
        self.assertEqual(evidence["dataGranularity"], "1d")
        self.assertEqual(evidence["priceHint"], 2)
        payload = json.loads(json.dumps(self.payload(row)))
        self.assertEqual(research_context.market_observations(payload), {"^IXIC": 1})
        self.assertIn("Nasdaq +1.00%", research_context.market_check(payload, self.clock))

    def test_early_close_uses_the_provider_session_end_without_fixed_utc_hours(self):
        value = self.index(); value["meta"]["currentTradingPeriod"]["regular"]["end"] = instant(19, 17).timestamp()
        value["meta"]["regularMarketTime"] = instant(19, 17, 45).timestamp()
        self.assertTrue(parse_regular_quote("^GSPC", value, self.clock)["closing_quote_update"])

    def test_source_exchange_timezone_handles_a_winter_index_close(self):
        value = self.index(); self.clock = instant(4, 3, month=11)
        value["meta"]["currentTradingPeriod"]["regular"] = {
            "start": instant(3, 14, 30, month=11).timestamp(), "end": instant(3, 21, month=11).timestamp()}
        value["meta"]["regularMarketTime"] = instant(3, 21, 45, month=11).timestamp()
        value["timestamp"] = [instant(day, 14, 30, month=11).timestamp() for day in (2, 3)]
        value["indicators"]["quote"][0]["close"] = [100, 101.0003]
        self.assertEqual(parse_regular_quote("^GSPC", value, self.clock)["session_date"], "2026-11-03")

    def test_normal_intraday_index_quotes_remain_live_without_a_close_corroboration(self):
        value = self.index(); self.clock = instant(19, 18)
        value["meta"]["regularMarketTime"] = instant(19, 17, 59).timestamp()
        value["indicators"]["quote"][0]["close"][-1] = None
        quote = parse_regular_quote("^GSPC", value, self.clock)
        self.assertFalse(quote["closing_quote_update"])
        self.assertEqual(quote["quote_timing"], "regular_session")


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
    print(f"Watchlist Quote Check: {'PASS' if success else 'FAIL'} ({result.testsRun} tests)")
    if traffic["blocked"]:
        print(f"FAIL: {len(traffic['blocked'])} unexpected provider connections blocked")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
