"""Offline behavioral checks for publisher times, date confidence and agent context."""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_special_alerts import offline_network_guard
from src.intelligence import calendar_context as context, calendar_sources as sources, calendar_source_cache as source_cache
from src.reports import live_market_calendar as calendar

NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)
DAYS = [date(2026, 10, 22), date(2026, 10, 23)]
DOL = "Publication Schedule: The UI Weekly Claims News Release is published each week on Thursday morning at 8:30am EST. Wednesday, November 25, 2026 8:30 AM EST."
MICHIGAN = "<p>Next data release: Friday, October 23, 2026 for Final October data at 10am ET</p>"


def fed_row(**overrides):
    return {"type": "FOMC", "title": "FOMC Meeting", "month": "2026-10", "days": "28",
            "time": "2:00 p.m.", "description": "Two-day meeting, October 27 - 28", **overrides}


def fed(*rows):
    return json.dumps({"events": list(rows)})


def event(start="DTSTART;TZID=US-Eastern:20261014T083000", name="Consumer Price Index", uid="release", sequence=0, extra=""):
    return f"BEGIN:VEVENT\nUID:{uid}\nSEQUENCE:{sequence}\n{start}\nSUMMARY:{name}\n{extra}\nEND:VEVENT\n"


def ics(*events):
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + "".join(events) + "END:VCALENDAR\n"


def macro(name="Initial Jobless Claims", **overrides):
    return {"eventName": name, "gmt": "08:30", "country": "United States", "actual": "194K",
            "consensus": "200K", "previous": "199K", **overrides}


def earnings(symbol="MSFT", **overrides):
    return {"symbol": symbol, "name": "Example Company", "time": "time-after-hours",
            "epsForecast": "2.00", "marketCap": "$1T", **overrides}


class IsolatedChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="calendar-evidence-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "calendar.json"
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"CALENDAR_STATE_FILE": str(self.path),
            "CALENDAR_SOURCE_CACHE_FILE": str(self.root / "publisher-cache.json"),
            "SPECIAL_ALERT_STATE_FILE": str(self.root / "alerts.sqlite3"), "REPORT_TIMEZONE": "America/New_York"}))
        self.stack.enter_context(patch.object(context, "utc_now", return_value=NOW))
        self.stack.enter_context(patch.object(source_cache, "utc_now", return_value=NOW))
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        self.stack.enter_context(patch.object(calendar, "datetime", Clock))

    def snapshot(self, raw=None, dates=None, now=None, schedules=None):
        dates = DAYS if dates is None else dates
        if raw is None:
            raw = {(DAYS[0], "economic"): [macro()], (DAYS[1], "economic"): [macro("S&P Global Manufacturing PMI", gmt="09:45", actual="")],
                   (DAYS[0], "earnings"): [earnings()], (DAYS[1], "earnings"): []}
        schedules = sources.parse_claims_schedule(DOL, dates) if schedules is None else schedules
        return context.normalize_snapshot(dates, raw, schedules, {"DOL": "available"}, now or NOW)

    def save(self, snapshot=None):
        snapshot = self.snapshot() if snapshot is None else snapshot
        context.save_snapshot(snapshot)
        return snapshot

    def render(self, snapshot=None, compact=True):
        snapshot = self.snapshot() if snapshot is None else snapshot
        dates = [date.fromisoformat(day["date"]) for day in snapshot["days"]]
        with patch.object(calendar, "_business_days", return_value=dates), patch.object(context, "get_snapshot", return_value=snapshot):
            return calendar.build_compact_market_calendar(["MSFT"]) if compact else calendar.build_full_market_calendar()


class PublisherChecks(IsolatedChecks):
    def test_bls_eastern_schedule_uses_daylight_saving_time(self):
        rows = sources.parse_ics(ics(event()), "BLS")
        self.assertEqual(rows[0]["at"], "2026-10-14T12:30:00+00:00")
        self.assertEqual(rows[0]["publisher"], "BLS")

    def test_bls_winter_release_uses_standard_time(self):
        rows = sources.parse_ics(ics(event("DTSTART;TZID=US-Eastern:20261113T083000", "Producer Price Index")), "BLS")
        self.assertEqual(rows[0]["at"], "2026-11-13T13:30:00+00:00")

    def test_bea_utc_dates_and_folded_summaries_are_supported(self):
        rows = sources.parse_ics(ics(event("DTSTART;VALUE=DATE-TIME:20261029T123000Z", "Personal Income and Outlays\\, Septem\n ber 2026")), "BEA")
        self.assertEqual(rows[0]["category"], "pce")
        self.assertIn("September 2026", rows[0]["name"])

    def test_floating_all_day_and_unknown_timezones_do_not_establish_a_time(self):
        for start in ("DTSTART:20261014T083000", "DTSTART;VALUE=DATE:20261014", "DTSTART;TZID=Unknown/Zone:20261014T083000"):
            with self.subTest(start=start): self.assertEqual(sources.parse_ics(ics(event(start)), "BLS"), [])

    def test_modified_timestamp_does_not_replace_missing_release_time(self):
        self.assertEqual(sources.parse_ics(ics(event("DTSTAMP:20261022T150000Z")), "BLS"), [])

    def test_html_or_truncated_calendar_is_unavailable(self):
        for text in ("<html>Access denied</html>", "BEGIN:VCALENDAR\n"):
            with self.subTest(text=text), self.assertRaises(ValueError): sources.parse_ics(text, "BLS")

    def test_rescheduled_uid_uses_the_latest_revision(self):
        raw = ics(event(), event("DTSTART;TZID=US-Eastern:20261015T083000", sequence=1))
        rows = sources.parse_ics(raw, "BLS")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["at"], "2026-10-15T12:30:00+00:00")

    def test_cancelled_latest_revision_does_not_leave_the_old_release_active(self):
        self.assertEqual(sources.parse_ics(ics(event(), event(sequence=1, extra="STATUS:CANCELLED")), "BLS"), [])

    def test_conflicting_equal_revisions_are_withheld(self):
        raw = ics(event(), event("DTSTART;TZID=US-Eastern:20261015T083000"))
        self.assertEqual(sources.parse_ics(raw, "BLS"), [])

    def test_claims_schedule_confirms_current_thursday_in_eastern_time(self):
        schedule = sources.parse_claims_schedule(DOL, DAYS)
        result = sources.verify_time("Initial Jobless Claims", DAYS[0], schedule)
        self.assertEqual(result["time_status"], "verified")
        self.assertEqual(result["event_at"], "2026-10-22T12:30:00+00:00")

    def test_thanksgiving_exception_moves_claims_to_wednesday(self):
        day = date(2026, 11, 25)
        schedule = sources.parse_claims_schedule(DOL, [day, day + timedelta(days=1)])
        self.assertEqual(sources.verify_time("Initial Jobless Claims", day, schedule)["time_status"], "verified")
        self.assertEqual(sources.verify_time("Initial Jobless Claims", day + timedelta(days=1), schedule)["time_status"], "conflict")

    def test_claims_winter_time_is_not_a_fixed_daylight_offset(self):
        schedule = sources.parse_claims_schedule(DOL, [date(2026, 11, 5)])
        self.assertEqual(sources.verify_time("Initial Jobless Claims", date(2026, 11, 5), schedule)["event_at"], "2026-11-05T13:30:00+00:00")

    def test_unrecognized_claims_schedule_is_not_assumed_to_mean_thursday(self):
        with self.assertRaises(ValueError): sources.parse_claims_schedule("Schedule unavailable", DAYS)

    def test_a_cpi_schedule_does_not_confirm_a_pmi_or_earnings_time(self):
        schedule = sources.parse_ics(ics(event()), "BLS")
        self.assertEqual(sources.verify_time("S&P Global Manufacturing PMI", date(2026, 10, 14), schedule)["time_status"], "unverified")

    def test_one_publisher_failure_does_not_disable_the_others(self):
        payloads = {sources.BLS_URL: "<html>Unavailable</html>", sources.BEA_URL: ics(event("DTSTART:20261029T123000Z", "Personal Income and Outlays")), sources.DOL_URL: DOL}
        with patch.object(sources, "request_schedule", side_effect=lambda url: payloads[url]):
            rows, status = sources.collect_schedules(DAYS)
        self.assertIn("unavailable", status["BLS"])
        self.assertEqual(status["BEA"], "available")
        self.assertEqual(status["DOL"], "available")
        self.assertTrue(rows)


class SnapshotChecks(IsolatedChecks):
    def test_publisher_time_is_used_without_assuming_the_gmt_column_is_utc(self):
        raw = {(DAYS[0], "economic"): [macro(gmt="13:30")]}
        row = self.snapshot(raw)["economic"][0]
        self.assertEqual(row["gmt"], "13:30")
        self.assertEqual(row["event_at"], "2026-10-22T12:30:00+00:00")

    def test_zero_actual_and_eps_are_real_values(self):
        raw = {(DAYS[0], "economic"): [macro(actual=0, previous=0)], (DAYS[0], "earnings"): [earnings(epsForecast=0)]}
        snapshot = self.snapshot(raw)
        self.assertEqual(snapshot["economic"][0]["actual"], "0")
        self.assertEqual(snapshot["earnings"][0]["epsForecast"], "0")

    def test_unknown_timezone_is_not_inferred_from_the_gmt_field_name(self):
        row = self.snapshot()["economic"][1]
        self.assertEqual(row["time_status"], "unverified")
        self.assertEqual(row["event_at"], "")

    def test_conflicting_release_date_withholds_values(self):
        raw = {(DAYS[1], "economic"): [macro()]}
        row = next(item for item in self.snapshot(raw)["economic"] if item["source_date"] == DAYS[1].isoformat())
        self.assertEqual(row["time_status"], "conflict")
        self.assertEqual((row["actual"], row["previous"], row["consensus"]), ("", "", ""))

    def test_actual_is_withheld_before_a_verified_release_even_on_the_same_day(self):
        snapshot = self.snapshot(now=NOW.replace(hour=10))
        self.assertEqual(snapshot["economic"][0]["actual"], "")

    def test_future_source_actuals_are_removed_before_caching(self):
        raw = {(DAYS[1], "economic"): [macro("S&P Global Manufacturing PMI", actual="999")]}
        self.assertEqual(self.snapshot(raw)["economic"][0]["actual"], "")

    def test_ambiguous_publisher_times_are_not_verified(self):
        schedule = sources.parse_claims_schedule(DOL, DAYS)
        original = next(row for row in schedule if row["at"].startswith("2026-10-22"))
        schedule.append({**original, "at": "2026-10-22T13:00:00+00:00"})
        self.assertEqual(self.snapshot(schedules=schedule)["economic"][0]["time_status"], "conflict")

    def test_unknown_country_is_not_assumed_to_be_a_us_release(self):
        raw = {(DAYS[0], "economic"): [macro(country=""), macro(country="Canada")]}
        self.assertEqual(self.snapshot(raw, schedules=[])["economic"], [])

    def test_unavailable_feed_is_distinct_from_a_valid_empty_feed(self):
        raw = {(DAYS[0], "economic"): [], (DAYS[0], "earnings"): None}
        snapshot = self.snapshot(raw)
        self.assertTrue(snapshot["days"][0]["economic_available"])
        self.assertFalse(snapshot["days"][0]["earnings_available"])

    def test_publisher_release_is_still_available_when_the_nasdaq_feed_fails(self):
        snapshot = self.snapshot({})
        self.assertTrue(snapshot["days"][0]["economic_available"])
        self.assertEqual(snapshot["economic"][0]["data_source"], "DOL")
        self.assertEqual(snapshot["economic"][0]["actual"], "")
        self.assertTrue(snapshot["issues"])

    def test_an_empty_feed_cannot_hide_a_publisher_confirmed_cpi_release(self):
        schedule = sources.parse_ics(ics(event("DTSTART;TZID=US-Eastern:20261022T083000")), "BLS")
        snapshot = self.snapshot({(DAYS[0], "economic"): []}, schedules=schedule)
        self.assertEqual(snapshot["economic"][0]["eventName"], "Consumer Price Index")
        self.assertEqual(snapshot["economic"][0]["publisher"], "BLS")

    def test_original_snapshot_is_not_changed_by_rendering(self):
        snapshot = self.snapshot(); before = deepcopy(snapshot)
        self.render(snapshot)
        self.assertEqual(snapshot, before)

    def test_public_snapshot_excludes_unrecognized_feed_fields(self):
        raw = {(DAYS[0], "economic"): [macro(description="UNRECOGNIZED_FIELD")]}
        self.assertNotIn("UNRECOGNIZED_FIELD", json.dumps(self.snapshot(raw)))

    def test_malformed_snapshot_is_unavailable(self):
        for text in ("{", "[]", "null", "true"):
            self.path.write_text(text)
            with self.subTest(text=text): self.assertIsNone(context.read_snapshot())

    def test_stale_future_or_naive_checked_time_cannot_be_relabelled_as_current(self):
        for stamp in ((NOW - timedelta(hours=7)).isoformat(), (NOW + timedelta(hours=1)).isoformat(), "2026-10-22T15:00:00"):
            snapshot = self.snapshot(); snapshot["checked_at"] = stamp; self.save(snapshot)
            with self.subTest(stamp=stamp): self.assertIsNone(context.read_snapshot())

    def test_fresh_snapshot_is_reused_without_network(self):
        self.save()
        with patch.object(calendar, "_fetch_calendar_days", side_effect=AssertionError("No fetch")), patch.object(sources, "collect_schedules", side_effect=AssertionError("No publisher fetch")):
            self.assertEqual(context.get_snapshot(DAYS)["checked_at"], NOW.isoformat())

    def test_force_refresh_fetches_new_evidence_and_preserves_source_independence(self):
        self.save()
        with patch.object(calendar, "_fetch_calendar_days", return_value={(DAYS[0], "economic"): [macro(actual="195K")]}) as fetch, patch.object(sources, "collect_schedules", return_value=(sources.parse_claims_schedule(DOL, DAYS), {"DOL": "available"})) as official:
            snapshot = context.get_snapshot(DAYS, force_refresh=True)
        fetch.assert_called_once_with(DAYS); official.assert_called_once_with(DAYS)
        self.assertEqual(snapshot["economic"][0]["actual"], "195K")

    def test_timezone_change_requires_a_new_snapshot(self):
        self.save()
        with patch.dict(os.environ, {"REPORT_TIMEZONE": "America/Lima"}): self.assertIsNone(context.read_snapshot())

    def test_calendar_views_refresh_a_thirty_minute_old_snapshot_while_reviews_can_read_it(self):
        snapshot = self.snapshot(now=NOW - timedelta(minutes=31)); self.save(snapshot)
        self.assertIsNotNone(context.read_snapshot())
        with patch.object(calendar, "_fetch_calendar_days", return_value={(DAYS[0], "economic"): [macro()]}) as fetch, patch.object(sources, "collect_schedules", return_value=(sources.parse_claims_schedule(DOL, DAYS), {"DOL": "available"})):
            context.get_snapshot(DAYS)
        fetch.assert_called_once_with(DAYS)

    def test_interrupted_save_preserves_previous_snapshot(self):
        self.save(); before = self.path.read_bytes()
        with patch.object(context.os, "replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError): context.save_snapshot(self.snapshot())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".calendar-*.tmp")))

    def test_bad_cached_row_is_withheld_without_a_network_fallback(self):
        snapshot = self.snapshot(); snapshot["economic"] = [None]; self.save(snapshot)
        with patch.object(calendar, "_fetch_calendar_days", side_effect=AssertionError("No fetch")):
            self.assertIsNone(context.calendar_context_provider())


class AdditionalPublisherChecks(IsolatedChecks):
    def test_bea_abbreviated_gdp_is_verified_without_confusing_regional_releases(self):
        raw = ics(event("DTSTART:20261029T123000Z", "GDP (Advance Estimate)\\, 3rd Quarter 2026"))
        schedule = sources.parse_ics(raw, "BEA")
        for name in ("GDP", "GDP Price Index", "Core PCE Prices"):
            self.assertEqual(sources.verify_time(name, date(2026, 10, 29), schedule)["time_status"], "verified")
        for name in ("GDP by County and Personal Income by County", "Gross Domestic Product for Puerto Rico", "Gross Domestic Product by State and Personal Income by State"):
            self.assertEqual(sources.parse_ics(ics(event(name=name)), "BEA"), [])

    def test_gdp_does_not_confirm_monthly_pce_or_a_census_goods_trade_release(self):
        schedule = sources.parse_ics(ics(event("DTSTART:20261029T123000Z", "GDP (Advance Estimate)")), "BEA")
        self.assertEqual(sources.verify_time("Core PCE Price Index", date(2026, 10, 29), schedule)["time_status"], "unverified")
        trade = sources.parse_ics(ics(event("DTSTART:20261006T123000Z", "U.S. International Trade in Goods and Services")), "BEA")
        self.assertEqual(sources.verify_time("Goods Trade Balance", date(2026, 10, 6), trade)["time_status"], "unverified")

    def test_gdp_and_monthly_pce_count_as_distinct_releases_at_the_same_clock(self):
        day = date(2026, 10, 29)
        schedule = sources.parse_ics(ics(event("DTSTART:20261029T123000Z", "GDP (Advance Estimate)", uid="gdp"),
            event("DTSTART:20261029T123000Z", "Personal Income and Outlays", uid="pce")), "BEA")
        raw = {(day, "economic"): [macro("GDP", actual=""), macro("GDP Price Index", actual=""), macro("Core PCE Price Index", actual="")]}
        self.assertIn("2 publisher-verified releases", context.review_snapshot(self.snapshot(raw, dates=[day], schedules=schedule)))

    def test_fed_uses_announcement_day_instead_of_meeting_start_or_asof(self):
        rows = sources.parse_fed_calendar(fed(fed_row()))
        self.assertEqual(rows[0]["at"], "2026-10-28T18:00:00+00:00")
        self.assertEqual(rows[0]["url"], sources.FED_URL)
        self.assertEqual(sources.verify_time("Fed Interest Rate Decision", date(2026, 10, 28), rows)["time_status"], "verified")
        self.assertEqual(sources.verify_time("FOMC Statement", date(2026, 10, 27), rows)["time_status"], "conflict")

    def test_fed_press_conference_and_minutes_keep_independent_times(self):
        rows = sources.parse_fed_calendar(fed(fed_row(), fed_row(title="FOMC Press Conference", time="2:30 p.m."), fed_row(title="FOMC Minutes", days="7")))
        self.assertEqual(sources.verify_time("FOMC Press Conference", date(2026, 10, 28), rows)["event_at"], "2026-10-28T18:30:00+00:00")
        self.assertEqual(sources.verify_time("FOMC Minutes", date(2026, 10, 7), rows)["event_at"], "2026-10-07T18:00:00+00:00")

    def test_fed_time_changes_and_winter_offsets_are_read_from_the_calendar(self):
        rows = sources.parse_fed_calendar(fed(fed_row(month="2026-12", days="9", time="1:15 p.m.")))
        self.assertEqual(rows[0]["at"], "2026-12-09T18:15:00+00:00")

    def test_fed_never_invents_a_clock_or_expands_a_meeting_date_range(self):
        for values in ({"time": ""}, {"time": "14:00"}, {"time": "2:99 p.m."}, {"days": "27-28"}, {"days": "28,29"}, {"days": "32"}, {"type": "Speeches"}, {"title": "FOMC Special Discussion"}):
            self.assertEqual(sources.parse_fed_calendar(fed(fed_row(**values))), [])

    def test_fed_calendar_handles_its_full_event_list_without_truncating_at_1500(self):
        rows = [{"type": "Other"}] * 2000 + [fed_row()]
        self.assertEqual(len(sources.parse_fed_calendar(fed(*rows))), 1)
        for raw in ("<html>Unavailable</html>", "null", '{"events":null}', '{"events":{}}', fed(*([{}] * 4001))):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError): sources.parse_fed_calendar(raw)

    def test_michigan_requires_its_explicit_next_release_date_and_eastern_clock(self):
        row = sources.parse_michigan_schedule(MICHIGAN)[0]
        self.assertEqual(row["at"], "2026-10-23T14:00:00+00:00")
        self.assertEqual(row["name"], "Michigan Consumer Sentiment (Final)")
        self.assertEqual(sources.verify_time("Michigan Consumer Sentiment", DAYS[1], [row])["time_status"], "verified")

    def test_michigan_winter_release_and_preliminary_stage_are_preserved(self):
        raw = "Next data release: Friday, December 4, 2026 for Preliminary December data at 10:00am ET"
        row = sources.parse_michigan_schedule(raw)[0]
        self.assertEqual(row["at"], "2026-12-04T15:00:00+00:00")
        self.assertIn("Preliminary", row["name"])

    def test_michigan_ambiguous_missing_or_inconsistent_notices_are_not_verified(self):
        for raw in ("<p>Current result 46.3</p>", MICHIGAN * 2, MICHIGAN.replace("Friday", "Monday"), MICHIGAN.replace(" ET", " UTC"), MICHIGAN.replace("10am", "99am"), MICHIGAN.replace(", 2026", "")):
            with self.subTest(raw=raw), self.assertRaises(ValueError): sources.parse_michigan_schedule(raw)

    def test_michigan_fallback_keeps_friday_visible_when_nasdaq_returns_no_events(self):
        schedule = sources.parse_michigan_schedule(MICHIGAN)
        snapshot = self.snapshot({(DAYS[1], "economic"): [], (DAYS[1], "earnings"): []}, dates=[DAYS[1]], schedules=schedule)
        report = self.render(snapshot)
        self.assertIn("10:00 EDT [Michigan] - Michigan Consumer Sentiment (Final)", report)
        self.assertNotIn("No matching releases", report)
        self.assertIn("incomplete Nasdaq coverage", report)
        self.assertEqual(snapshot["economic"][0]["actual"], "")

    def test_fed_statement_and_decision_count_once_and_do_not_add_a_duplicate_fallback(self):
        day = date(2026, 10, 28)
        schedule = sources.parse_fed_calendar(fed(fed_row(), fed_row(title="FOMC Press Conference", time="2:30 p.m.")))
        raw = {(day, "economic"): [macro("FOMC Statement", gmt="14:00", actual=""), macro("Fed Interest Rate Decision", gmt="14:00", actual=""), macro("FOMC Press Conference", gmt="14:30", actual="")]}
        snapshot = self.snapshot(raw, dates=[day], schedules=schedule)
        self.assertEqual(len(snapshot["economic"]), 3)
        self.assertIn("2 publisher-verified releases", context.review_snapshot(snapshot))
        report = self.render(snapshot)
        self.assertIn("14:00 EDT [Fed]", report)
        self.assertIn("14:30 EDT [Fed]", report)
        self.save(snapshot)
        self.assertIn("FOMC Press Conference", context.calendar_context_provider().signal)

    def test_fed_fallback_supplies_the_decision_and_press_conference_without_forecasts(self):
        day = date(2026, 10, 28)
        schedule = sources.parse_fed_calendar(fed(fed_row(), fed_row(title="FOMC Press Conference", time="2:30 p.m.")))
        snapshot = self.snapshot({}, dates=[day], schedules=schedule)
        report = self.render(snapshot)
        self.assertIn("FOMC Statement / Rate Decision", report)
        self.assertIn("FOMC Press Conference", report)
        self.assertNotIn("4.00%", report)
        self.save(snapshot)
        with patch.object(sources, "collect_schedules", side_effect=AssertionError("No network")):
            block = context.calendar_context_provider()
        self.assertIn("FOMC", block.signal)
        self.assertFalse(block.metadata["score_changes"])

    def test_publisher_outages_remain_visible_without_disabling_other_sources(self):
        payloads = {sources.BLS_URL: ics(event()), sources.BEA_URL: ics(event("DTSTART:20261029T123000Z", "GDP (Advance Estimate)")), sources.DOL_URL: DOL,
                    sources.FED_URL: fed(fed_row()), sources.MICHIGAN_URL: "<html>Unavailable</html>"}
        with patch.object(sources, "request_schedule", side_effect=lambda url: payloads[url]):
            schedule, status = sources.collect_schedules(DAYS)
        self.assertEqual(status["Fed"], "available")
        self.assertIn("unavailable", status["Michigan"])
        snapshot = context.normalize_snapshot(DAYS, {}, schedule, status, NOW)
        self.assertIn("Michigan schedule unavailable", self.render(snapshot))

    def test_past_michigan_next_release_notice_is_flagged_for_a_later_window(self):
        payloads = {sources.BLS_URL: ics(event()), sources.BEA_URL: ics(event("DTSTART:20261029T123000Z", "GDP (Advance Estimate)")), sources.DOL_URL: DOL,
                    sources.FED_URL: fed(fed_row()), sources.MICHIGAN_URL: MICHIGAN}
        with patch.object(sources, "request_schedule", side_effect=lambda url: payloads[url]):
            _, status = sources.collect_schedules([date(2026, 10, 26)])
        self.assertIn("unavailable", status["Michigan"])

    def test_empty_partial_sources_do_not_claim_the_day_has_no_macro_events(self):
        snapshot = self.snapshot({(DAYS[1], "economic"): [], (DAYS[1], "earnings"): []}, dates=[DAYS[1]], schedules=[])
        report = self.render(snapshot)
        self.assertIn("coverage may be incomplete", report)
        self.assertNotIn("No matching major US macro events", report)


class SourceResilienceChecks(IsolatedChecks):
    def collect(self, when=NOW, failures=None, bls=None, michigan=MICHIGAN):
        payloads = {sources.BLS_URL: bls if bls is not None else ics(event("DTSTART;TZID=US-Eastern:20261023T083000")),
            sources.BEA_URL: ics(event("DTSTART:20261029T123000Z", "GDP (Advance Estimate)")), sources.DOL_URL: DOL,
            sources.FED_URL: fed(fed_row()), sources.MICHIGAN_URL: michigan}
        failures = failures or {}
        def request(url):
            if url in failures:
                raise failures[url]
            return payloads[url]
        with patch.object(source_cache, "utc_now", return_value=when), patch.object(sources, "request_schedule", side_effect=request) as fetch:
            rows, status = sources.collect_schedules(DAYS)
        return rows, status, [call.args[0] for call in fetch.call_args_list]

    def forbidden(self):
        return HTTPError(sources.BLS_URL, 403, "Forbidden", None, None)

    def test_first_403_without_history_never_invents_bls_verification(self):
        rows, status, _ = self.collect(failures={sources.BLS_URL: self.forbidden()})
        self.assertFalse(any(row["publisher"] == "BLS" for row in rows))
        self.assertIn("unavailable (HTTP 403; retry after 10-22 21:00 UTC)", status["BLS"])
        self.assertEqual(status["Fed"], "available")
        self.assertEqual(status["BEA"], "available")

    def test_403_pauses_bls_for_six_hours_without_disabling_other_publishers(self):
        self.collect(failures={sources.BLS_URL: self.forbidden()})
        _, status, calls = self.collect(NOW + timedelta(hours=5))
        self.assertNotIn(sources.BLS_URL, calls)
        self.assertIn(sources.BEA_URL, calls)
        self.assertIn("HTTP 403", status["BLS"])
        self.assertEqual(status["BEA"], "available")
        _, status, calls = self.collect(NOW + timedelta(hours=6, seconds=1))
        self.assertIn(sources.BLS_URL, calls)
        self.assertEqual(status["BLS"], "available")

    def test_recent_successful_bls_schedule_survives_a_403_with_its_original_check(self):
        self.collect()
        rows, status, _ = self.collect(NOW + timedelta(hours=1), {sources.BLS_URL: self.forbidden()})
        row = next(row for row in rows if row["publisher"] == "BLS")
        self.assertEqual(row["fetched_at"], NOW.isoformat())
        self.assertTrue(row["cached"])
        self.assertIn("cached (HTTP 403", status["BLS"])
        timing = sources.verify_time("CPI", DAYS[1], rows)
        self.assertEqual(timing["time_status"], "cached")
        self.assertEqual(timing["timing_checked_at"], NOW.isoformat())

    def test_cached_schedule_expiry_cannot_be_extended_by_more_failed_scans(self):
        self.collect()
        self.collect(NOW + timedelta(hours=23), {sources.BLS_URL: self.forbidden()})
        rows, status, calls = self.collect(NOW + timedelta(hours=25))
        self.assertNotIn(sources.BLS_URL, calls)
        self.assertFalse(any(row["publisher"] == "BLS" for row in rows))
        self.assertIn("unavailable", status["BLS"])
        self.assertFalse(source_cache.load()["BLS"]["events"])

    def test_recovery_replaces_the_old_schedule_instead_of_merging_rescheduled_bls_dates(self):
        self.collect()
        self.collect(NOW + timedelta(hours=1), {sources.BLS_URL: self.forbidden()})
        revised = ics(event("DTSTART;TZID=US-Eastern:20261026T083000", sequence=1))
        rows, status, _ = self.collect(NOW + timedelta(hours=8), bls=revised)
        bls = [row for row in rows if row["publisher"] == "BLS"]
        self.assertEqual([row["at"] for row in bls], ["2026-10-26T12:30:00+00:00"])
        self.assertFalse(bls[0]["cached"])
        self.assertEqual(status["BLS"], "available")

    def test_cancellation_cannot_revive_the_old_schedule_from_cache(self):
        self.collect()
        cancelled = ics(event("DTSTART;TZID=US-Eastern:20261023T083000", extra="STATUS:CANCELLED"))
        rows, _, _ = self.collect(NOW + timedelta(hours=1), bls=cancelled)
        self.assertFalse(any(row["publisher"] == "BLS" for row in rows))
        self.assertFalse(source_cache.load()["BLS"]["events"])

    def test_html_returned_instead_of_a_calendar_keeps_only_recent_labelled_history(self):
        self.collect()
        rows, status, _ = self.collect(NOW + timedelta(hours=1), bls="<html>Access denied</html>")
        self.assertTrue(next(row for row in rows if row["publisher"] == "BLS")["cached"])
        self.assertIn("cached (ValueError", status["BLS"])

    def test_other_http_failures_have_a_shorter_backoff_and_show_the_http_code(self):
        error = HTTPError(sources.BEA_URL, 503, "Unavailable", None, None)
        self.collect(failures={sources.BEA_URL: error})
        _, status, calls = self.collect(NOW + timedelta(minutes=14))
        self.assertNotIn(sources.BEA_URL, calls)
        self.assertIn("HTTP 503", status["BEA"])
        _, status, calls = self.collect(NOW + timedelta(minutes=16))
        self.assertIn(sources.BEA_URL, calls)
        self.assertEqual(status["BEA"], "available")

    def test_corrupt_unknown_origin_future_and_naive_cached_rows_cannot_supply_times(self):
        self.collect()
        original = deepcopy(source_cache.load()["BLS"]["events"][0])
        for override in ({"url": "https://example.invalid/schedule"}, {"publisher": "BEA"},
                         {"fetched_at": (NOW + timedelta(hours=1)).isoformat()}, {"fetched_at": "2026-10-22T15:00:00"},
                         {"fetched_at": (NOW - timedelta(hours=25)).isoformat()}, {"at": "2026-10-23"}, {"category": []}):
            state = {"BLS": source_cache.failure([{**original, **override}], "HTTP 403", NOW, True)}
            source_cache.save(state)
            rows, _, _ = self.collect()
            self.assertFalse(any(row["publisher"] == "BLS" for row in rows), override)

    def test_a_forged_long_or_future_backoff_does_not_stop_a_valid_new_request(self):
        for attempted, retry in ((NOW, NOW + timedelta(days=100)), (NOW + timedelta(hours=1), NOW + timedelta(hours=6))):
            source_cache.save({"BLS": {"events": [], "error": "HTTP 403", "attempted_at": attempted.isoformat(), "retry_after": retry.isoformat()}})
            _, status, calls = self.collect()
            self.assertIn(sources.BLS_URL, calls)
            self.assertEqual(status["BLS"], "available")

    def test_malformed_source_cache_does_not_disable_current_sources(self):
        for text in ("{", "null", "[]", '{"schema":true,"sources":{}}'):
            source_cache.state_path().write_text(text)
            _, status, calls = self.collect()
            self.assertIn(sources.BLS_URL, calls)
            self.assertEqual(status["BLS"], "available")

    def test_interrupted_cache_write_keeps_previous_bytes_and_live_results(self):
        self.collect(); before = source_cache.state_path().read_bytes()
        with patch.object(source_cache.os, "replace", side_effect=PermissionError("simulated write failure")):
            rows, status, _ = self.collect(NOW + timedelta(hours=1))
        self.assertTrue(any(row["publisher"] == "BLS" and not row["cached"] for row in rows))
        self.assertIn("save unavailable", status["Schedule cache"])
        self.assertEqual(source_cache.state_path().read_bytes(), before)
        self.assertFalse(list(self.root.glob(".calendar-source-*.tmp")))

    def test_report_and_agent_show_cached_age_without_promoting_it_to_live_verification(self):
        self.collect()
        when = NOW + timedelta(hours=1)
        rows, status, _ = self.collect(when, {sources.BLS_URL: self.forbidden()})
        raw = {(DAYS[1], "economic"): [macro("CPI", actual="999")], (DAYS[1], "earnings"): []}
        snapshot = context.normalize_snapshot([DAYS[1]], raw, rows, status, when)
        report = self.render(snapshot)
        self.assertIn("08:30 EDT [BLS; cached 10-22 15:00 UTC]", report)
        self.assertNotIn("999", report)
        self.assertIn("HTTP 403", report)
        self.assertIn("1 cached publisher release;", context.review_snapshot(snapshot))
        self.save(snapshot)
        with patch.object(context, "utc_now", return_value=when), patch.object(sources, "request_schedule", side_effect=AssertionError("No network")):
            block = context.calendar_context_provider()
        self.assertIn("cached as of 10-22 15:00 UTC", block.signal)
        self.assertFalse(block.metadata["score_changes"])
        from scripts.check_report_consistency import BuilderConsistencyChecks
        from src.reports import daily_report
        from src.reports.report_quality import validate_daily_report_quality, MAX_DAILY_REPORT_CHARS
        daily = BuilderConsistencyChecks.build_daily_fixture(SimpleNamespace(daily=daily_report), when, report)
        self.assertTrue(validate_daily_report_quality(daily)["passes"])
        self.assertLessEqual(len(daily), MAX_DAILY_REPORT_CHARS)
        self.assertIn("BLS; cached 10-22 15:00 UTC", daily)

    def test_a_new_report_timestamp_cannot_launder_expired_publisher_evidence(self):
        self.collect()
        rows, status, _ = self.collect(NOW + timedelta(hours=1), {sources.BLS_URL: self.forbidden()})
        snapshot = context.normalize_snapshot([DAYS[1]], {(DAYS[1], "economic"): [macro("CPI")]}, rows, status, NOW + timedelta(hours=1))
        self.save(snapshot)
        self.assertIsNotNone(context.read_snapshot(now=NOW + timedelta(hours=1)))
        snapshot["checked_at"] = (NOW + timedelta(hours=25)).isoformat(); self.save(snapshot)
        self.assertIsNone(context.read_snapshot(now=NOW + timedelta(hours=25)))

    def test_a_cached_release_date_disagreement_stays_explicit_and_withholds_values(self):
        self.collect()
        rows, status, _ = self.collect(NOW + timedelta(hours=1), {sources.BLS_URL: self.forbidden()})
        snapshot = context.normalize_snapshot([DAYS[0]], {(DAYS[0], "economic"): [macro("CPI", actual="999")]}, rows, status, NOW + timedelta(hours=1))
        report = self.render(snapshot)
        self.assertIn("date conflicts with cached publisher schedule", report)
        self.assertNotIn("999", report)

    def test_michigan_rollover_keeps_the_recent_past_notice_with_its_original_age(self):
        before = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        self.collect(before)
        new_notice = "Next data release: Friday, November 6, 2026 for Preliminary November data at 10am ET"
        rows, status, _ = self.collect(before + timedelta(hours=4), michigan=new_notice)
        old = next(row for row in rows if row["publisher"] == "Michigan" and row["at"].startswith("2026-10-23"))
        self.assertTrue(old["cached"])
        self.assertEqual(old["fetched_at"], before.isoformat())
        upcoming = next(row for row in rows if row["publisher"] == "Michigan" and row["at"].startswith("2026-11-06"))
        self.assertFalse(upcoming["cached"])
        self.assertEqual(status["Michigan"], "available")

    def test_cached_actual_values_remain_source_reported_instead_of_publisher_confirmed(self):
        self.collect()
        when = NOW + timedelta(hours=23)
        rows, status, _ = self.collect(when, {sources.BLS_URL: self.forbidden()})
        snapshot = context.normalize_snapshot([DAYS[1]], {(DAYS[1], "economic"): [macro("CPI", actual="3.0%")]}, rows, status, when)
        self.assertIn("source-reported actual 3.0%", self.render(snapshot))


class OutputChecks(IsolatedChecks):
    def test_compact_calendar_shows_verified_zone_and_estimated_earnings_dates(self):
        report = self.render()
        self.assertIn("08:30 EDT [DOL]", report)
        self.assertIn("Time unverified (source 09:45)", report)
        self.assertIn("Nasdaq estimates; company confirmation pending", report)
        self.assertIn("Checked: 2026-10-22 11:00 EDT", report)
        self.assertNotIn("Economic release times: timezone unverified", report)

    def test_full_calendar_includes_publisher_source_links(self):
        report = self.render(compact=False)
        for url in sources.SOURCE_URLS.values(): self.assertIn(url, report)

    def test_conflicting_dates_cannot_show_source_actuals_as_verified_results(self):
        report = self.render(self.snapshot({(DAYS[1], "economic"): [macro(actual="999")] }))
        self.assertIn("date conflicts with publisher schedule", report)
        self.assertNotIn("999", report)

    def test_source_outage_is_not_rendered_as_no_events(self):
        report = self.render(self.snapshot({}, schedules=[]))
        self.assertIn("Live economic calendar unavailable", report)
        self.assertNotIn("No matching major US macro events", report)

    def test_verified_times_convert_to_lima_without_assuming_a_fixed_offset(self):
        with patch.dict(os.environ, {"REPORT_TIMEZONE": "America/Lima"}):
            report = self.render(self.snapshot())
        self.assertIn("07:30 -05 [DOL]", report)

    def test_converted_time_shows_its_date_when_it_crosses_midnight(self):
        with patch.dict(os.environ, {"REPORT_TIMEZONE": "Pacific/Kiritimati"}):
            report = self.render(self.snapshot())
        self.assertIn("10-23 02:30 +14 [DOL]", report)
        self.assertIn("US calendar dates", report)

    def test_business_day_selection_uses_the_us_calendar_even_in_another_report_zone(self):
        with patch.dict(os.environ, {"REPORT_TIMEZONE": "Asia/Tokyo"}):
            self.assertEqual(calendar._business_days(2), DAYS)

    def test_economic_query_offset_remains_explicit_and_asof_does_not_set_event_dates(self):
        payload = {"data": {"asOf": "Thu, Jan 01, 1970", "rows": [macro()]}}
        with patch.dict(os.environ, {"CALENDAR_ECONOMIC_DATE_OFFSET": "1"}), patch.object(calendar, "_calendar_request_payload", return_value=payload) as fetch:
            result = calendar._request_json(calendar.NASDAQ_ECONOMIC_URL, DAYS[0])
        fetch.assert_called_once_with(calendar.NASDAQ_ECONOMIC_URL, DAYS[0] + timedelta(days=1))
        snapshot = self.snapshot({(DAYS[0], "economic"): calendar._extract_rows(result)})
        self.assertEqual(snapshot["economic"][0]["source_date"], "2026-10-22")


class AgentChecks(IsolatedChecks):
    def test_calendar_review_warms_the_same_cache_used_by_the_report(self):
        with patch.object(calendar, "_business_days", return_value=DAYS), patch.object(calendar, "_fetch_calendar_days", return_value={(DAYS[0], "economic"): [macro()]}), patch.object(sources, "collect_schedules", return_value=(sources.parse_claims_schedule(DOL, DAYS), {"DOL": "available"})):
            detail = context.refresh_calendar_review()
        self.assertIn("1 publisher-verified releases", detail)
        self.assertIsNotNone(context.read_snapshot())

    def test_cache_only_context_has_no_risk_votes_or_score_changes(self):
        self.save()
        with patch.object(calendar, "_fetch_calendar_days", side_effect=AssertionError("No fetch")):
            block = context.calendar_context_provider()
        self.assertEqual(block.feature, "Calendar Evidence")
        self.assertEqual((block.risks, block.themes), ([], []))
        self.assertFalse(block.metadata["score_changes"])
        self.assertIn("estimates", block.implication)

    def test_three_claims_rows_count_as_one_publisher_release(self):
        raw = {(DAYS[0], "economic"): [macro(), macro("Continuing Jobless Claims"), macro("Jobless Claims 4-Week Avg.")]}
        self.assertIn("1 publisher-verified releases", context.review_snapshot(self.snapshot(raw)))

    def test_company_calendar_review_preserves_estimate_status_and_symbol_scope(self):
        self.save()
        text = context.build_catalyst_review("MSFT")
        self.assertIn("2026-10-22", text)
        self.assertIn("Nasdaq date estimate; company confirmation pending", text)
        self.assertEqual(context.build_catalyst_review("NVDA"), "")

    def test_tradeplan_and_active_scorecard_use_the_same_calendar_evidence(self):
        self.save()
        from scripts.check_report_consistency import STOCKS
        from src.reports import tradeplan_report, scorecard
        stock = deepcopy(next(item for item in STOCKS if item.get("ticker") == "MSFT")); before = deepcopy(stock)
        with patch.object(tradeplan_report, "find_stock", return_value=stock), patch.object(scorecard, "build_headline_impact_summary", return_value="Offline headlines"):
            reports = [tradeplan_report.build_tradeplan_report("MSFT"), scorecard.build_scorecard(stock)]
        for report in reports:
            self.assertIn("Calendar Catalyst", report)
            self.assertIn("company confirmation pending", report)
            self.assertIn("Score Risk:", report)
        self.assertEqual(stock, before)

    def test_daily_intelligence_label_requires_a_current_snapshot(self):
        from src.reports.daily_intelligence_sources import build_daily_intelligence_stack_line
        self.assertNotIn("Calendar Evidence: active", build_daily_intelligence_stack_line())
        self.save()
        self.assertIn("Calendar Evidence: active", build_daily_intelligence_stack_line())

    def test_delivered_daily_report_preserves_calendar_confidence_within_quality_budget(self):
        self.save()
        from scripts.check_report_consistency import BuilderConsistencyChecks
        from src.reports import daily_report
        from src.reports.report_quality import validate_daily_report_quality, MAX_DAILY_REPORT_CHARS
        report = BuilderConsistencyChecks.build_daily_fixture(SimpleNamespace(daily=daily_report), NOW, self.render())
        quality = validate_daily_report_quality(report)
        self.assertTrue(quality["passes"], quality)
        self.assertLessEqual(len(report), MAX_DAILY_REPORT_CHARS)
        self.assertIn("08:30 EDT [DOL]", report)
        self.assertIn("company confirmation pending", report)
        self.assertIn("Calendar Evidence: active", report)

    def test_unavailable_calendars_cannot_report_a_successful_source_review(self):
        self.save(self.snapshot({}, schedules=[]))
        with patch.object(context, "get_snapshot", return_value=self.snapshot({}, schedules=[])):
            with self.assertRaisesRegex(RuntimeError, "Calendar sources unavailable"): context.refresh_calendar_review()


def main():
    with offline_network_guard() as traffic:
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed = result.wasSuccessful() and not traffic["blocked"]
    print(f"Calendar Evidence Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    if traffic["blocked"]: print(f"FAIL: {len(traffic['blocked'])} unexpected provider connections blocked")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
