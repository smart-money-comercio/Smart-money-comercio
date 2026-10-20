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
