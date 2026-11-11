"""Offline weekly evidence, horizon, immutable edition and command regressions."""

import argparse
import asyncio
from contextlib import ExitStack, closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_market_resilience import raw as chart_raw, OPEN
from scripts.check_disclosure_details import maintenance, sanctions, MAINTENANCE, TITLE, URL
from scripts.check_news_editor import candidate
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from scripts.check_daily_news_brief import assert_fixture_connections_closed
from src.intelligence import weekend_inputs as inputs, weekend_store as store, weekend_theme as themes
from src.intelligence import news_editor as editor, calendar_sources
from src.reports import weekend_outlook as report, daily_voiceover
from src.commands import weekend_commands as commands
from scripts import export_weekend_outlook as cli

NOW=datetime(2026,11,8,14,20,tzinfo=timezone.utc)
PUBLISHED="2026-11-06T16:00:00+00:00"


def chart(symbol="^GSPC"):
    value=chart_raw(symbol,106,index=True)
    value["timestamp"][0]=(OPEN-timedelta(days=7)).timestamp()
    value["indicators"]["quote"][0]["close"][0]=110
    return value


def market_fetch(url):
    symbol=unquote(url.split("/chart/")[1].split("?")[0])
    return {"status":"ok","url":url,"body":json.dumps({"chart":{"result":[chart(symbol)],"error":None}}),
            "fetched_at_epoch":NOW.timestamp()}


def story(**changes):
    return maintenance(**{"published":PUBLISHED,"source_checked_at":NOW.isoformat(),"evidence_checked_at":NOW.isoformat(),**changes})


def notice(day=17):
    return candidate("NVDA",title="NVIDIA Sets Conference Call for Third-Quarter Financial Results",
        url="https://nvidianews.nvidia.com/news/synthetic-quarterly-conference-call",
        published="2026-11-03T16:00:00+00:00",source="NVIDIA Newsroom",source_checked_at=NOW.isoformat(),
        excerpt_scope="publisher feed excerpt",source_excerpt=f"NVIDIA will host its earnings conference call on November {day}, 2026 at 5:00 p.m. Eastern Time.")


def calendar():
    return {"checked_at":NOW.isoformat(),"days":[{"date":f"2026-11-{day}"} for day in range(9,14)],"issues":[],
        "economic":[{"eventName":"Weekly jobless claims","event_at":"2026-11-12T08:30:00-05:00",
            "time_status":"verified","source_date":"2026-11-12","publisher":"DOL", "timing_url":calendar_sources.SOURCE_URLS["DOL"]}]}


def edition(**changes):
    return report.build(**{"now":NOW,"raw":[story(),notice()],"market_fetch":market_fetch,
        "calendar_snapshot":calendar(),"persist":False,**changes})


def original_page(text=MAINTENANCE,*,title=TITLE,url=URL,published=PUBLISHED):
    return (f'<meta property="og:title" content="{escape(title)}"><meta property="og:url" content="{url}">'
        f'<meta property="og:publishDate" content="{published}"><h1>{escape(title)}</h1>'
        f'<div class="NewsroomArticleBody_BodyCopy__synthetic"><p>{escape(text)}</p></div>')


class WindowChecks(unittest.TestCase):
    def test_sunday_selects_completed_week_and_coming_week(self):
        row=inputs.window(NOW)
        self.assertEqual((row["baseline_date"],row["week_end"],row["next_start"],row["next_end"]),
            ("2026-10-30","2026-11-06","2026-11-09","2026-11-13"))

    def test_utc_saturday_can_still_be_friday_in_new_york(self):
        with self.assertRaises(ValueError):inputs.window(datetime(2026,11,7,2,tzinfo=timezone.utc))

    def test_utc_monday_can_still_be_sunday_in_new_york(self):
        self.assertEqual(inputs.window(datetime(2026,11,9,2,tzinfo=timezone.utc))["week_end"],"2026-11-06")

    def test_weekday_build_is_held(self):
        with self.assertRaises(ValueError):inputs.window(NOW+timedelta(days=1))

    def test_naive_build_clock_is_held(self):
        with self.assertRaises(ValueError):inputs.window(NOW.replace(tzinfo=None))

    def test_new_year_window_is_unambiguous(self):
        row=inputs.window(datetime(2027,1,2,14,tzinfo=timezone.utc))
        self.assertEqual((row["week_start"],row["next_end"]),("2026-12-28","2027-01-08"))

    def test_dst_weekend_retains_the_monday_zone(self):
        row=inputs.window(datetime(2026,11,1,14,tzinfo=timezone.utc))
        self.assertEqual(row["evidence_start"],"2026-10-26T00:00:00-04:00")


class PriceChecks(unittest.TestCase):
    def proof(self,value=None):
        return inputs.price_packet("^GSPC",value or chart(),NOW.timestamp(),inputs.window(NOW),NOW)

    def test_weekly_basis_uses_previous_friday_and_keeps_friday_change_separate(self):
        row=self.proof();self.assertAlmostEqual(row["weekly_percent"],-3.63636363636)
        self.assertAlmostEqual(row["friday_percent"],6.0)

    def test_range_previous_close_and_adjusted_close_are_ignored(self):
        value=chart();value["meta"].update(previousClose=1,chartPreviousClose=2)
        value["indicators"]["adjclose"][0]["adjclose"]=[1,2,3]
        self.assertEqual(self.proof(value)["weekly_percent"],self.proof()["weekly_percent"])

    def test_monday_is_not_a_substitute_for_previous_friday(self):
        value=chart();value["timestamp"][0]+=3*86400
        with self.assertRaises(ValueError):self.proof(value)

    def test_missing_holiday_friday_is_held(self):
        value=chart();value["timestamp"][-1]-=86400
        with self.assertRaises(ValueError):self.proof(value)

    def test_null_baseline_close_is_held(self):
        value=chart();value["indicators"]["quote"][0]["close"][0]=None
        with self.assertRaises(ValueError):self.proof(value)

    def test_duplicate_sessions_are_held(self):
        value=chart();value["timestamp"][0]=value["timestamp"][1]
        with self.assertRaises(ValueError):self.proof(value)

    def test_history_is_bounded(self):
        value=chart();value["timestamp"]*=15;value["indicators"]["quote"][0]["close"]*=15
        with self.assertRaises(ValueError):self.proof(value)

    def test_wrong_instrument_is_held(self):
        value=chart();value["meta"]["symbol"]="TSM"
        with self.assertRaises(ValueError):self.proof(value)

    def test_wrong_currency_is_held(self):
        value=chart();value["meta"]["currency"]="EUR"
        with self.assertRaises(ValueError):self.proof(value)

    def test_future_native_clock_is_held(self):
        value=chart();value["meta"]["regularMarketTime"]=(NOW+timedelta(hours=1)).timestamp()
        with self.assertRaises(ValueError):self.proof(value)

    def test_stale_observation_is_held(self):
        with self.assertRaises(ValueError):inputs.price_packet("^GSPC",chart(),(NOW-timedelta(hours=7)).timestamp(),inputs.window(NOW),NOW)

    def test_altered_weekly_return_does_not_pass_revalidation(self):
        row=self.proof();row["weekly_percent"]=9
        with self.assertRaises(ValueError):inputs.checked_price(row,inputs.window(NOW),NOW)

    def test_market_response_redirect_is_held(self):
        rows=inputs.collect_prices(inputs.window(NOW),NOW,lambda url:{**market_fetch(url),"final_url":"https://example.org"})
        self.assertTrue(all(row["status"]=="limited" for row in rows))

    def test_weekly_reads_are_exactly_three(self):
        fetch=Mock(side_effect=market_fetch)
        rows=inputs.collect_prices(inputs.window(NOW),NOW,fetch)
        self.assertEqual(fetch.call_count,3);self.assertTrue(all(row["status"]=="available" for row in rows))


class StoryChecks(unittest.TestCase):
    def admit(self,row=None,text=MAINTENANCE,observed=None):
        return inputs.admit_story(row or story(),text,observed or NOW.isoformat(),inputs.window(NOW),NOW)

    def test_completed_week_disclosure_older_than_24_hours_is_eligible(self):
        row=self.admit();self.assertEqual(row["event_evidence"]["schema"],12)
        self.assertEqual(len(row["event_evidence"]["facts"]),4);inputs.checked_story(row,inputs.window(NOW),NOW)

    def test_daily_24_hour_gate_still_holds_the_same_disclosure(self):
        plan=editor.build_editorial_plan({"rows":[]},NOW,[story()])
        self.assertEqual(plan["candidates"][0]["source_check"],"hold");self.assertIn("24 hours",plan["candidates"][0]["reason"])

    def test_previous_week_story_is_held(self):
        with self.assertRaises(ValueError):self.admit(story(published="2026-10-30T16:00:00+00:00"))

    def test_future_publication_is_held(self):
        with self.assertRaises(ValueError):self.admit(story(published=(NOW+timedelta(hours=1)).isoformat()))

    def test_observation_before_publication_is_held(self):
        with self.assertRaises(ValueError):self.admit(story(published=NOW.isoformat()),observed=(NOW-timedelta(minutes=5)).isoformat())

    def test_publication_without_timezone_is_held(self):
        with self.assertRaises(ValueError):self.admit(story(published="2026-11-06T16:00:00"))

    def test_weekend_updates_keep_their_original_date(self):
        row=self.admit(story(published="2026-11-07T16:00:00+00:00"))
        self.assertEqual(row["publication_label"],"weekend update");self.assertTrue(row["published"].startswith("2026-11-07"))

    def test_wrong_publisher_url_is_held_even_with_a_forged_canonical_url(self):
        with self.assertRaises(ValueError):self.admit(story(url="https://example.org/story",canonical_url=URL))

    def test_non_https_source_is_held(self):
        with self.assertRaises(ValueError):self.admit(story(url=URL.replace("https:","http:")))

    def test_empty_original_facts_are_held(self):
        with self.assertRaises(ValueError):self.admit(text="The company describes its long history and general corporate ambitions. "*3)

    def test_pending_certification_is_not_a_completed_designation(self):
        with self.assertRaises(ValueError):self.admit(text=MAINTENANCE.replace("has been selected","could be selected"))

    def test_cached_dateline_must_match_original_publication(self):
        with self.assertRaises(ValueError):self.admit(text="EXAMPLE BAY, La. – October 1, 2026 – "+MAINTENANCE)

    def test_body_is_bounded(self):
        with self.assertRaises(ValueError):self.admit(text=MAINTENANCE*100)

    def test_observation_is_not_renewed_by_revalidation(self):
        at=(NOW-timedelta(hours=2)).isoformat();row=self.admit(observed=at)
        inputs.checked_story(row,inputs.window(NOW),NOW);self.assertEqual(row["event_evidence"]["observed_at"],at)

    def test_derived_daily_proof_is_rebuilt_without_rewriting_original_text(self):
        row=story(event_evidence={"schema":12,"observed_at":"old"})
        self.assertEqual(self.admit(row)["event_evidence"]["observed_at"],NOW.isoformat())

    def test_stage_tamper_is_rejected(self):
        row=self.admit();row["event_evidence"]["stage"]="new funded order"
        with self.assertRaises(ValueError):inputs.checked_story(row,inputs.window(NOW),NOW)

    def test_uncached_original_page_is_read_and_bound(self):
        row=story(excerpt_scope="publisher feed excerpt",source_excerpt="")
        fetch=Mock(return_value={"status":"ok","url":URL,"body":original_page(),"fetched_at_epoch":NOW.timestamp()})
        rows,logs=inputs.collect_stories([row],inputs.window(NOW),NOW,fetch)
        self.assertEqual(len(rows),1);self.assertEqual(fetch.call_count,1);self.assertEqual(logs[0]["status"],"admitted")

    def test_stale_body_requires_a_new_original_read(self):
        row=story(evidence_checked_at=(NOW-timedelta(hours=7)).isoformat())
        fetch=Mock(return_value={"status":"ok","url":URL,"body":original_page(),"fetched_at_epoch":NOW.timestamp()})
        rows,_=inputs.collect_stories([row],inputs.window(NOW),NOW,fetch)
        self.assertEqual(len(rows),1);self.assertEqual(fetch.call_count,1)

    def test_body_title_and_date_mismatch_are_held(self):
        for body in (original_page(title="Different original release"),original_page(published="2026-11-05T16:00:00+00:00")):
            rows,logs=inputs.collect_stories([story(excerpt_scope="headline only")],inputs.window(NOW),NOW,
                lambda url:{"status":"ok","url":url,"body":body,"fetched_at_epoch":NOW.timestamp()})
            self.assertFalse(rows);self.assertEqual(logs[0]["status"],"held")

    def test_original_reads_are_bounded_to_six(self):
        rows=[story(url=URL+str(i),excerpt_scope="headline only") for i in range(20)]
        fetch=Mock(return_value={"status":"error","error":"HTTPError 403"})
        found,logs=inputs.collect_stories(rows,inputs.window(NOW),NOW,fetch)
        self.assertFalse(found);self.assertEqual(fetch.call_count,6);self.assertEqual(len(logs),6)

    def test_cached_verified_body_needs_no_new_fetch(self):
        fetch=Mock(side_effect=AssertionError("No network expected"))
        rows,_=inputs.collect_stories([story()],inputs.window(NOW),NOW,fetch)
        self.assertEqual(len(rows),1);fetch.assert_not_called()

    def test_duplicate_url_is_reviewed_once(self):
        rows,logs=inputs.collect_stories([story(),story()],inputs.window(NOW),NOW)
        self.assertEqual(len(rows),1);self.assertEqual(len(logs),1)


class CalendarChecks(unittest.TestCase):
    def packet(self,snapshot=None,raw=None):
        return inputs.calendar_packet([notice()] if raw is None else raw,inputs.window(NOW),NOW,calendar() if snapshot is None else snapshot)

    def test_next_week_macro_and_later_issuer_event_are_separate(self):
        row=self.packet();self.assertEqual(len(row["macro"]),1);self.assertFalse(row["company"])
        self.assertEqual(row["later"][0]["event_date"],"2026-11-17");inputs.checked_calendar(row,inputs.window(NOW),NOW)

    def test_issuer_event_inside_next_week_is_admitted(self):
        row=self.packet(raw=[notice(10)])
        self.assertEqual(row["company"][0]["event_date"],"2026-11-10");self.assertFalse(row["later"])

    def test_estimated_earnings_are_not_calendar_evidence(self):
        snap=calendar();snap["earnings"]=[{"symbol":"AMD","date":"2026-11-10","estimated":True}]
        row=self.packet(snap,[]);self.assertFalse(row["company"])

    def test_unverified_macro_time_is_held(self):
        snap=calendar();snap["economic"][0]["time_status"]="unverified"
        self.assertFalse(self.packet(snap)["macro"])

    def test_macro_outside_next_week_is_excluded(self):
        snap=calendar();snap["economic"][0]["event_at"]="2026-11-19T08:30:00-05:00"
        self.assertFalse(self.packet(snap)["macro"])

    def test_wrong_original_schedule_url_is_excluded(self):
        snap=calendar();snap["economic"][0]["timing_url"]="https://example.org/calendar"
        self.assertFalse(self.packet(snap)["macro"])

    def test_naive_macro_clock_is_excluded(self):
        snap=calendar();snap["economic"][0]["event_at"]="2026-11-12T08:30:00"
        self.assertFalse(self.packet(snap)["macro"])

    def test_cached_schedule_needs_its_own_fresh_observation(self):
        snap=calendar();snap["economic"][0].update(time_status="cached",timing_checked_at=(NOW-timedelta(hours=7)).isoformat())
        self.assertFalse(self.packet(snap)["macro"])

    def test_stale_snapshot_is_not_renewed(self):
        snap=calendar();snap["checked_at"]=(NOW-timedelta(hours=7)).isoformat()
        self.assertFalse(self.packet(snap)["macro"])

    def test_calendar_day_absence_is_explicitly_unknown(self):
        text=report.calendar_read(self.packet(),inputs.window(NOW))
        self.assertEqual(text.count("No publisher-verified entry"),4);self.assertIn("missing verified coverage",text)

    def test_calendar_horizon_tamper_is_rejected(self):
        row=self.packet();row["company"]=row.pop("later");row["later"]=[]
        with self.assertRaises(ValueError):inputs.checked_calendar(row,inputs.window(NOW),NOW)

    def test_conflicting_issuer_notices_are_held(self):
        row=self.packet(raw=[notice(10),{**notice(11),"url":notice()["url"]+"-other"}])
        self.assertFalse(row["company"]);self.assertFalse(row["later"])


class EditionChecks(unittest.TestCase):
    def test_complete_edition_has_checked_business_theme_and_conditions(self):
        row=edition();self.assertEqual(row["quality"]["status"],"PASS")
        self.assertEqual(row["theme"]["id"],"defense");text=row["report_text"]
        for term in ("Business interpretation", "Conditions to watch", "For now", "would make", "would weaken"):
            self.assertIn(term,text)

    def test_weekly_recap_distinguishes_rebound_from_weekly_loss(self):
        text=edition()["report_text"]
        self.assertIn("Friday's rebound",text);self.assertIn("October 30, 2026 close",text)

    def test_business_analysis_is_stage_specific(self):
        text=edition()["report_text"]
        self.assertIn("maintenance workload",text);self.assertIn("Sales depend on service orders",text)

    def test_later_event_is_not_called_a_coming_week_catalyst(self):
        row=edition();segment=next(s for s in row["voiceover"]["segments"] if s["heading"].startswith("Coming week"))
        self.assertNotIn("seventeenth",segment["narration"])
        later=next(s for s in row["voiceover"]["segments"] if s["heading"]=="Beyond the coming week")
        self.assertIn("seventeenth",later["narration"])

    def test_narration_summarizes_original_instead_of_reading_headline(self):
        text=edition()["voiceover"]["script"]
        self.assertNotIn(TITLE,text);self.assertNotIn("NVIDIA",text);self.assertNotIn("https://",text)

    def test_source_links_and_original_publication_dates_remain_in_report(self):
        text=edition()["report_text"]
        self.assertIn(URL,text);self.assertIn(PUBLISHED,text)

    def test_source_bound_export_contains_no_original_article_body(self):
        row=edition();packet=report.episode(row,NOW);text=json.dumps(packet)
        self.assertEqual(packet["edition_type"],"weekend_outlook");self.assertEqual(packet["voiceover_schema"],2)
        self.assertEqual(packet["mode"],"draft_review_required");self.assertNotIn("source_excerpt",text);self.assertNotIn("source_text",text)
        for segment in packet["segments"]:
            self.assertTrue(all(key in packet["sources"] for key in segment["source_ids"]))

    def test_no_theme_is_check_and_cannot_export(self):
        row=edition(raw=[]);self.assertEqual(row["quality"]["status"],"CHECK")
        self.assertIn("No weekly investment theme qualified",row["report_text"])
        with self.assertRaises(ValueError):report.episode(row,NOW)

    def test_issuer_identity_alone_does_not_establish_an_ai_theme(self):
        row=edition()["inputs"]["stories"][0]
        with patch.object(themes,"checked_evidence",return_value={"schema":8,"source_text":"The company reported its retail sales and operating costs."}):
            self.assertEqual(themes.group({**row,"publisher_symbol":"AMZN"}),"business")

    def test_ai_frame_needs_relevant_original_business_text(self):
        row=edition()["inputs"]["stories"][0]
        with patch.object(themes,"checked_evidence",return_value={"schema":8,"source_text":"The company disclosed data center capacity commitments."}):
            self.assertEqual(themes.group({**row,"publisher_symbol":"AMZN"}),"ai")

    def test_theme_limits_one_selected_story_per_issuer(self):
        row=edition()["inputs"]["stories"][0];other={**row,"id":"other"}
        self.assertEqual(len(themes.choose([row,other])["story_ids"]),1)

    def test_theme_does_not_assign_probabilities_or_price_targets(self):
        theme=edition()["theme"];cases=" ".join(theme[key] for key in ("base","stronger","weaker"))
        self.assertNotIn("%",cases);self.assertNotIn("price target",cases.lower())

    def test_non_utc_build_clock_is_stored_as_utc(self):
        row=edition(now=NOW.astimezone(inputs.NY));self.assertEqual(row["generated_at"],NOW.isoformat())

    def test_one_benchmark_is_check(self):
        def fetch(url):return market_fetch(url) if "%5EGSPC" in url else {"status":"error","error":"HTTPError 429"}
        row=edition(market_fetch=fetch);self.assertEqual(row["quality"]["status"],"CHECK")
        self.assertIn("1 of three",row["report_text"])

    def test_two_benchmarks_pass_with_incomplete_coverage_qualification(self):
        def fetch(url):return {"status":"error","error":"HTTPError 429"} if "%5ERUT" in url else market_fetch(url)
        row=edition(market_fetch=fetch);self.assertEqual(row["quality"]["status"],"PASS");self.assertIn("2 of three",row["report_text"])

    def test_all_missing_prices_do_not_invent_market_direction(self):
        row=edition(market_fetch=lambda url:{"status":"error","error":"Unavailable"})
        self.assertNotIn("Friday's rebound",row["report_text"]);self.assertEqual(row["quality"]["status"],"CHECK")

    def test_changed_fact_with_recomputed_identity_still_fails(self):
        row=edition();row["inputs"]["stories"][0]["event_evidence"]["facts"][0]["value"]="new funded award"
        row["id"]=store.identity(row)
        with self.assertRaises(ValueError):report.checked(row)

    def test_changed_narration_with_recomputed_hashes_still_fails(self):
        row=edition();row["voiceover"]["script"]="Unsupported forecast."
        row["voiceover"]["script_sha256"]=report.text_hash(row["voiceover"]["script"]);row["id"]=store.identity(row)
        with self.assertRaises(ValueError):report.checked(row)

    def test_changed_weekly_basis_cannot_be_resealed(self):
        row=edition();row["inputs"]["window"]["baseline_date"]="2026-11-02";row["id"]=store.identity(row)
        with self.assertRaises(ValueError):report.checked(row)

    def test_repeated_prices_cannot_satisfy_two_benchmark_requirement(self):
        row=edition();row["inputs"]["prices"][1]=deepcopy(row["inputs"]["prices"][0]);row["id"]=store.identity(row)
        with self.assertRaises(ValueError):report.checked(row)

    def test_current_edition_exports_without_network(self):
        with patch.object(inputs.feeds,"fetch_url",side_effect=AssertionError("No export network")):
            self.assertTrue(report.episode(edition(),NOW)["review_required"])

    def test_six_hour_source_freshness_limits_eight_hour_edition_window(self):
        with self.assertRaises(ValueError):report.episode(edition(),NOW+timedelta(hours=6,minutes=1))

    def test_monday_export_is_held(self):
        with self.assertRaises(ValueError):report.episode(edition(),NOW+timedelta(days=1))

    def test_archive_still_reads_after_export_window_closes(self):
        row=edition();self.assertEqual(report.checked(row),row)
        self.assertIn("stale",report.status(row,NOW+timedelta(days=7)))

    def test_status_includes_basis_facts_and_horizons(self):
        text=report.status(edition(),NOW)
        for value in ("Editorial rules: 31","2026-10-30 close","Concrete fact fields: 4","later-horizon notices","ready for review-only export"):
            self.assertIn(value,text)

    def test_frozen_rules29_daily_hashes_and_schema2_export_remain_exact(self):
        row=json.loads((ROOT/'scripts/fixtures/weekend_rules29_edition.json').read_text())
        self.assertEqual(row["report_sha256"],"2b5cc4b540fc5b5216f5163e7e0ef97e65acbcb15d067a709cbe1398e0a2da47")
        self.assertEqual(sha256(row["report_text"].encode()).hexdigest(),row["report_sha256"])
        self.assertEqual(row["voiceover"]["script_sha256"],"450057ccdd4ddee42262d7febd1956273346596c06a07b58ec4819f3769c6190")
        at=inputs.clock(row["generated_at"]);self.assertEqual(daily_voiceover.episode(row,at)["voiceover_schema"],2)


class StorageCommandChecks(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ,{"WEEKEND_STATE_FILE":str(self.root/'weekend.sqlite3'),
            "NEWS_EDITOR_STATE_FILE":str(self.root/'daily.sqlite3')}))

    def test_store_is_separate_and_latest_read_is_readonly(self):
        row=edition();store.save(row);path=store.state_path();before=path.read_bytes()
        self.assertEqual(store.latest(),row);self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'daily.sqlite3').exists())

    def test_corrupt_store_record_is_not_trusted(self):
        import sqlite3
        row=edition();store.save(row)
        with closing(sqlite3.connect(store.state_path())) as db,db:
            db.execute("UPDATE weekend_editions SET record='{}'")
        self.assertIsNone(store.latest())

    def test_missing_store_read_creates_no_state(self):
        self.assertIsNone(store.latest());self.assertFalse(store.state_path().exists())

    def test_current_edition_is_reused_without_fetching(self):
        row=edition();store.save(row)
        with patch.object(inputs,"raw_candidates",side_effect=AssertionError("No new leads")):
            self.assertEqual(report.build(NOW+timedelta(minutes=10)),row)

    def test_explicit_refresh_rebuilds(self):
        with patch.object(inputs,"raw_candidates",return_value=([story()],[])) as leads,patch.object(inputs.feeds,"fetch_url",side_effect=market_fetch),patch.object(inputs.calendar_context,"read_snapshot",return_value=calendar()):
            report.build(NOW,force=True,persist=False)
        self.assertEqual(leads.call_count,1)

    def message(self):return SimpleNamespace(reply_text=AsyncMock(),reply_document=AsyncMock())

    def test_weekend_command_sends_only_requested_review_with_safe_chunks(self):
        message=self.message();row=edition()
        with patch.object(report,"build",return_value=row) as build:
            asyncio.run(commands.weekend_command(SimpleNamespace(message=message),SimpleNamespace(args=["refresh"])))
        self.assertTrue(build.call_args.kwargs["force"]);self.assertTrue(all(len(call.args[0])<=3200 for call in message.reply_text.call_args_list))
        message.reply_document.assert_not_called()

    def test_command_rejects_unknown_arguments_before_build(self):
        message=self.message()
        with patch.object(report,"build") as build:
            asyncio.run(commands.weekend_command(SimpleNamespace(message=message),SimpleNamespace(args=["publish"])))
        build.assert_not_called()

    def test_status_command_does_not_build_or_fetch(self):
        message=self.message()
        with patch.object(commands,"latest",return_value=edition()),patch.object(report,"build",side_effect=AssertionError("Read only")):
            asyncio.run(commands.weekendstatus_command(SimpleNamespace(message=message),SimpleNamespace(args=[])))
        self.assertIn("Weekend Outlook Quality",message.reply_text.call_args_list[0].args[0])

    def test_voiceover_command_returns_plain_text_document(self):
        message=self.message();row=edition()
        with patch.object(commands,"latest",return_value=row):
            asyncio.run(commands.weekendvoiceover_command(SimpleNamespace(message=message),SimpleNamespace(args=[])))
        sent=message.reply_document.call_args.kwargs
        self.assertEqual(sent["filename"],"weekend_voiceover.txt");self.assertEqual(sent["document"].getvalue().decode().strip(),row["voiceover"]["script"])

    def test_export_command_returns_review_only_json(self):
        message=self.message();row=edition()
        with patch.object(commands,"latest",return_value=row),patch.object(commands,"datetime") as clock:
            clock.now.return_value=NOW
            asyncio.run(commands.weekendexport_command(SimpleNamespace(message=message),SimpleNamespace(args=[])))
        packet=json.loads(message.reply_document.call_args.kwargs["document"].getvalue())
        self.assertEqual(packet["edition_type"],"weekend_outlook");self.assertTrue(packet["review_required"])

    def test_unavailable_export_sends_no_document(self):
        message=self.message()
        with patch.object(commands,"latest",side_effect=ValueError("Stale source")):
            asyncio.run(commands.weekendexport_command(SimpleNamespace(message=message),SimpleNamespace(args=[])))
        message.reply_document.assert_not_called()

    def test_four_handlers_are_registered(self):
        with patch.dict(os.environ,{"OPENAI_API_KEY":"offline-command-import"}):
            from src.commands import register_commands
        app=Mock();register_commands.register_commands(app)
        handlers={command for call in app.add_handler.call_args_list for command in getattr(call.args[0],"commands",[])}
        self.assertTrue({"weekend","weekendstatus","weekendvoiceover","weekendexport"}<=handlers)

    def test_cli_writes_source_bound_json_and_narration(self):
        row=edition();store.save(row);target=self.root/'weekend.json'
        with patch.object(cli,"datetime") as clock:
            clock.now.return_value=NOW;self.assertEqual(cli.main(["--output",str(target)]),0)
        self.assertEqual(json.loads(target.read_text())["edition_type"],"weekend_outlook")
        self.assertEqual(target.with_suffix('.txt').read_text().strip(),row["voiceover"]["script"])

    def test_cli_does_not_overwrite_existing_output(self):
        store.save(edition());target=self.root/'weekend.json';target.write_text("keep")
        with patch.object(cli,"datetime") as clock:
            clock.now.return_value=NOW;self.assertEqual(cli.main(["--output",str(target)]),1)
        self.assertEqual(target.read_text(),"keep");self.assertFalse(target.with_suffix('.txt').exists())


class WeeklyDiscoveryChecks(unittest.TestCase):
    def archived(self):
        at=inputs.clock(PUBLISHED)+timedelta(hours=1)
        row=inputs.admit_story(story(),MAINTENANCE,at.isoformat(),inputs.window(NOW),at)
        return {**row,"decision":"selected"}

    def leads(self,archived,live=None):
        from src.intelligence import news_editor_store
        with patch.object(editor,"cache_candidates",return_value=(live or [],[])),patch.object(news_editor_store,"read_editions",return_value=[{"candidates":archived}]) as read:
            rows,issues=inputs.raw_candidates(NOW)
        self.assertEqual(read.call_args.kwargs["limit"],50)
        return rows,issues

    def cold(self,count=6):
        sources=(("MSFT","https://blogs.microsoft.com/blog/synthetic-platform/"),
            ("NVDA","https://nvidianews.nvidia.com/news/synthetic-platform"),
            ("AMD","https://ir.amd.com/news-events/press-releases/detail/999/synthetic-platform"),
            ("CRWD","https://www.crowdstrike.com/en-us/press-releases/synthetic-platform/"),
            ("AMZN","https://www.aboutamazon.com/news/aws/synthetic-platform"),
            ("INTC","https://newsroom.intel.com/artificial-intelligence/synthetic-platform"))
        return [candidate(symbol,title=symbol+" introduces a synthetic cloud platform",url=url,
            published=(NOW-timedelta(minutes=15)).isoformat(),source_checked_at=NOW.isoformat(),excerpt_scope="headline only") for symbol,url in sources[:count]]

    def test_weekly_archive_supplies_dated_original_leads(self):
        rows,issues=self.leads([self.archived()])
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]["weekend_archive_lead"])
        self.assertEqual(rows[0]["published"],PUBLISHED);self.assertIn("1 reviewed original",issues[0])

    def test_selected_headline_without_concrete_original_proof_is_not_a_lead(self):
        row=story(decision="selected");row.pop("event_evidence",None)
        rows,_=self.leads([row]);self.assertFalse(rows)

    def test_unselected_or_old_week_disclosures_are_not_weekly_leads(self):
        a=self.archived();b={**a,"published":"2026-10-30T16:00:00+00:00"};a["decision"]="skip"
        rows,_=self.leads([a,b]);self.assertFalse(rows)

    def test_duplicate_archived_urls_are_added_once(self):
        rows,_=self.leads([self.archived(),self.archived()]);self.assertEqual(len(rows),1)

    def test_invalid_archived_fact_proof_is_not_used_for_discovery(self):
        row=self.archived();row["event_evidence"]["facts"][0]["value"]="unsupported new order"
        rows,_=self.leads([row]);self.assertFalse(rows)

    def test_old_archive_observation_requires_a_new_original_read(self):
        rows,_=self.leads([self.archived()]);fetch=Mock(return_value={"status":"ok","url":URL,"body":original_page(),"fetched_at_epoch":NOW.timestamp()})
        found,_=inputs.collect_stories(rows,inputs.window(NOW),NOW,fetch)
        self.assertEqual(fetch.call_count,1);self.assertEqual(found[0]["evidence_checked_at"],NOW.isoformat())
        self.assertEqual(found[0]["published"],PUBLISHED)

    def test_blocked_archive_read_does_not_renew_old_facts(self):
        rows,_=self.leads([self.archived()]);fetch=Mock(return_value={"status":"error","error":"HTTPError 403; cooldown active"})
        found,ledger=inputs.collect_stories(rows,inputs.window(NOW),NOW,fetch)
        self.assertFalse(found);self.assertIn("cooldown",ledger[0]["reason"])

    def test_archive_date_conflict_is_still_held(self):
        rows,_=self.leads([self.archived()]);fetch=Mock(return_value={"status":"ok","url":URL,
            "body":original_page(published="2026-11-05T16:00:00+00:00"),"fetched_at_epoch":NOW.timestamp()})
        found,_=inputs.collect_stories(rows,inputs.window(NOW),NOW,fetch);self.assertFalse(found)

    def test_archived_disclosure_is_reviewed_before_six_newer_headline_leads(self):
        rows,_=self.leads([self.archived()],self.cold())
        def fetch(url):
            return {"status":"ok","url":url,"body":original_page(),"fetched_at_epoch":NOW.timestamp()} if url==URL else {"status":"error","error":"Synthetic unavailable body"}
        read=Mock(side_effect=fetch);found,ledger=inputs.collect_stories(rows,inputs.window(NOW),NOW,read)
        self.assertEqual(len(found),1);self.assertEqual(found[0]["publisher_symbol"],"NOC")
        self.assertEqual(ledger[0]["status"],"admitted");self.assertEqual(read.call_count,6)
        self.assertEqual(len(ledger),6)

    def test_verified_cached_facts_outrank_newer_factless_bodies(self):
        bad=[{**row,"excerpt_scope":"original release excerpt","source_excerpt":"This company describes general ambitions and research. "*3,
              "evidence_checked_at":NOW.isoformat()} for row in self.cold()]
        read=Mock(side_effect=AssertionError("Fresh body should be reused"))
        found,ledger=inputs.collect_stories(bad+[story()],inputs.window(NOW),NOW,read)
        self.assertEqual(found[0]["publisher_symbol"],"NOC");self.assertEqual(ledger[0]["status"],"admitted");read.assert_not_called()

    def test_supported_original_reader_is_not_downgraded_by_missing_headline_facts(self):
        rows=self.cold()+[story(excerpt_scope="headline only",source_excerpt="")]
        def fetch(url):
            return {"status":"ok","url":url,"body":original_page(),"fetched_at_epoch":NOW.timestamp()} if url==URL else {"status":"error","error":"Synthetic unavailable body"}
        read=Mock(side_effect=fetch);found,_=inputs.collect_stories(rows,inputs.window(NOW),NOW,read)
        self.assertEqual(found[0]["publisher_symbol"],"NOC");self.assertLessEqual(read.call_count,6)

    def test_new_current_feed_proof_wins_over_a_duplicate_old_archive_lead(self):
        rows,_=self.leads([self.archived()],[story()]);read=Mock(side_effect=AssertionError("Fresh original is already available"))
        found,ledger=inputs.collect_stories(rows,inputs.window(NOW),NOW,read)
        self.assertEqual(len(found),1);self.assertEqual(len(ledger),1);read.assert_not_called()

    def test_stale_unreviewed_feed_lead_is_not_freshened_as_an_archive(self):
        read=Mock(side_effect=AssertionError("Unverified stale feed should be excluded"))
        found,_=inputs.collect_stories([story(source_checked_at=(NOW-timedelta(hours=7)).isoformat())],inputs.window(NOW),NOW,read)
        self.assertFalse(found);read.assert_not_called()

    def test_one_claims_release_is_not_three_independent_calendar_events(self):
        snapshot=calendar();base=snapshot["economic"][0]
        snapshot["economic"]=[{**base,"eventName":label} for label in ("Initial Jobless Claims","Continuing Jobless Claims","Jobless Claims 4-Week Avg.")]
        packet=inputs.calendar_packet([],inputs.window(NOW),NOW,snapshot)
        self.assertEqual(len(packet["macro"]),1);self.assertEqual(packet["macro"][0]["event"],"Weekly jobless claims")

    def test_previously_recorded_separate_claims_entries_remain_readable(self):
        value=edition();old_inputs=deepcopy(value["inputs"]);base=old_inputs["calendar"]["macro"][0]
        old_inputs["calendar"]["macro"]=[{**base,"event":label} for label in ("Initial Jobless Claims","Continuing Jobless Claims","Jobless Claims 4-Week Avg.")]
        old=report.assemble(old_inputs);self.assertEqual(report.checked(old),old)
        self.assertIn("Continuing Jobless Claims",old["report_text"])


class SQLiteCleanupChecks(unittest.TestCase):
    def test_weekend_database_handles_close_before_fixture_cleanup(self):
        # Retain every connection so garbage collection cannot hide a leak on Linux.
        for name in ("test_store_is_separate_and_latest_read_is_readonly",
                     "test_corrupt_store_record_is_not_trusted",
                     "test_current_edition_is_reused_without_fetching"):
            with self.subTest(fixture=name):
                assert_fixture_connections_closed(self,StorageCommandChecks(name))


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in
            (WindowChecks,PriceChecks,StoryChecks,CalendarChecks,EditionChecks,StorageCommandChecks,WeeklyDiscoveryChecks,SQLiteCleanupChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Weekend Outlook Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=="__main__":raise SystemExit(main())
