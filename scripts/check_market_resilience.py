"""Offline dated-price, recovery, corporate-action and archive regressions."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW as EDITOR_NOW
from scripts.check_disclosure_details import maintenance, sanctions
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.utils import yahoo_quote as parser, market_quote_source as source
from src.intelligence import market_event_desk as events, news_editor as editor, news_editor_store as store, research_context
from src.reports import daily_report, daily_voiceover as voice, morning_brief_intro
from src.reports.daily_news_brief import build_daily_news_brief, validate_news_brief

UTC=timezone.utc
NOW=datetime(2026,11,7,14,20,tzinfo=UTC)
OPEN=datetime(2026,11,6,14,30,tzinfo=UTC)
END=OPEN.replace(hour=21,minute=0)


def raw(symbol="TSM",price=106,*,index=False):
    return {"meta":{"symbol":symbol,"regularMarketPrice":price,
        "regularMarketTime":(END+timedelta(minutes=76) if index else END+timedelta(seconds=2)).timestamp(),
        "exchangeTimezoneName":"America/New_York","currency":"USD","exchangeName":"NIM" if index else "NYQ",
        "instrumentType":"INDEX" if index else "EQUITY","hasPrePostMarketData":not index,"dataGranularity":"1d","priceHint":2,
        "currentTradingPeriod":{"regular":{"start":OPEN.timestamp(),"end":END.timestamp()}},
        "chartPreviousClose":777,"previousClose":888},
        "timestamp":[(OPEN-timedelta(days=i)).timestamp() for i in (2,1,0)],
        "indicators":{"quote":[{"close":[99,100,price],"volume":[1000,1100,1200]}],"adjclose":[{"adjclose":[33,34,35]}]},
        "request":{"events":"splits","range":"5d","interval":"1d"},"events":{}}


def quote(symbol="TSM",price=106,*,value=None):
    value=deepcopy(value) if value is not None else raw(symbol,price)
    result=parser.parse_regular_quote(symbol,value,NOW,profile=2)
    result["quote_evidence"]=source.source_evidence(value)
    if result.get("return_usable") is False:result.update(ok=False,error=result["return_note"])
    return result


def response(value):
    return json.dumps({"chart":{"result":[value],"error":None}})


def split(value,when=OPEN,*,dated=True):
    value=deepcopy(value)
    event={"splitRatio":"2:1","numerator":2,"denominator":1}
    if dated:event["date"]=when.timestamp()
    value["events"]={"splits":{str(int(when.timestamp())) if dated else "undated":event}}
    return value


class PrivateState(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{"MARKET_QUOTE_STATUS_FILE":str(self.root/'health.json'),
                                                       "MARKET_EVENT_STATE_FILE":str(self.root/'events.json')}))


class PriceChecks(unittest.TestCase):
    def test_late_nasdaq_rounding_case_is_recovered_only_in_new_evidence(self):
        value=raw("^IXIC",24579.424,index=True)
        value["indicators"]["quote"][0]["close"]=[25372.009765625,24315.0,24579.4296875]
        before=deepcopy(value)
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("^IXIC",value,NOW)
        result=parser.parse_regular_quote("^IXIC",value,NOW,profile=2)
        self.assertEqual(value,before);self.assertEqual(result["price"],24579.424)
        self.assertEqual(result["asof"],"2026-11-06T22:16:00+00:00")
        self.assertAlmostEqual(result["change_percent"],1.0874933,places=5)
        self.assertEqual(result["previous_session_date"],"2026-11-05")

    def test_more_than_one_display_tick_is_not_reconciled(self):
        value=raw("^IXIC",24579.424,index=True);value["indicators"]["quote"][0]["close"][-1]=24579.435
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("^IXIC",value,NOW,profile=2)

    def test_rounding_allowance_is_capped_relative_to_the_index_price(self):
        value=raw("^IXIC",1,index=True);value["meta"]["priceHint"]=0
        value["indicators"]["quote"][0]["close"][-1]=1.1
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("^IXIC",value,NOW,profile=2)

    def test_late_close_still_needs_native_index_type_precision_and_no_after_hours(self):
        for field,setting in (("instrumentType","EQUITY"),("hasPrePostMarketData",True),("priceHint",None),("priceHint",True),("dataGranularity","5m")):
            value=raw("^IXIC",index=True);value["meta"][field]=setting
            with self.subTest(field=field),self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("^IXIC",value,NOW,profile=2)

    def test_missing_null_or_duplicate_current_index_bar_stays_unavailable(self):
        for close in (None,0,True,float("nan")):
            value=raw("^IXIC",index=True);value["indicators"]["quote"][0]["close"][-1]=close
            with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("^IXIC",value,NOW,profile=2)
        value=raw("^IXIC",index=True);value["timestamp"].append(OPEN.timestamp()+60);value["indicators"]["quote"][0]["close"].append(106)
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("^IXIC",value,NOW,profile=2)

    def test_equity_after_hours_price_cannot_use_the_cash_index_exception(self):
        value=raw();value["meta"]["regularMarketTime"]=(END+timedelta(minutes=76)).timestamp()
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("TSM",value,NOW,profile=2)

    def test_completed_equity_price_and_closing_bar_conflict_is_rejected(self):
        value=raw();value["indicators"]["quote"][0]["close"][-1]=53
        with self.assertRaisesRegex(parser.QuoteDataError,"conflicts"):parser.parse_regular_quote("TSM",value,NOW,profile=2)

    def test_large_move_without_current_closing_bar_cannot_supply_a_return(self):
        value=raw();value["indicators"]["quote"][0]["close"][-1]=None
        result=parser.parse_regular_quote("TSM",value,NOW,profile=2)
        self.assertFalse(result["return_usable"]);self.assertIn("closing bar",result["return_note"])

    def test_dividend_adjusted_values_and_range_baselines_are_not_price_return_inputs(self):
        value=raw();before=deepcopy(value)
        result=parser.parse_regular_quote("TSM",value,NOW,profile=2)
        self.assertAlmostEqual(result["change_percent"],6);self.assertEqual(result["previous_close"],100)
        self.assertEqual(value,before)

    def test_duplicate_prior_session_bars_are_ambiguous(self):
        value=raw();value["timestamp"].insert(1,(OPEN-timedelta(days=1)).timestamp()+60)
        value["indicators"]["quote"][0]["close"].insert(1,90)
        with self.assertRaisesRegex(parser.QuoteDataError,"Duplicate"):parser.parse_regular_quote("TSM",value,NOW,profile=2)

    def test_newer_null_bar_prevents_thursdays_quote_becoming_the_weekend_baseline(self):
        value=raw();value["meta"]["regularMarketTime"]=(END-timedelta(days=1)).timestamp()
        monday=OPEN+timedelta(days=3)
        value["meta"]["currentTradingPeriod"]["regular"]={"start":monday.timestamp(),"end":(monday+timedelta(hours=6,minutes=30)).timestamp()}
        value["indicators"]["quote"][0]["close"][-1]=None
        with self.assertRaisesRegex(parser.QuoteDataError,"older than available dated history"):parser.parse_regular_quote("TSM",value,NOW,profile=2)

    def test_future_and_stale_native_timestamps_remain_unavailable(self):
        value=raw();value["meta"]["regularMarketTime"]=(NOW+timedelta(minutes=2)).timestamp()
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("TSM",value,NOW,profile=2)
        with self.assertRaises(parser.QuoteDataError):parser.parse_regular_quote("TSM",raw(),NOW+timedelta(days=5),profile=2)

    def test_extreme_equity_return_is_held_even_with_matching_daily_prices(self):
        result=parser.parse_regular_quote("TSM",raw(price=150),NOW,profile=2)
        self.assertFalse(result["return_usable"]);self.assertIn("independent",result["return_note"])

    def test_large_vix_change_is_not_treated_as_an_equity_corporate_action(self):
        value=raw("^VIX",150);value["meta"]["instrumentType"]="INDEX"
        result=parser.parse_regular_quote("^VIX",value,NOW,profile=2)
        self.assertTrue(result["return_usable"]);self.assertAlmostEqual(result["change_percent"],50)

    def test_unknown_or_boolean_source_versions_are_rejected(self):
        for version in (True,3,"2"):
            with self.assertRaises(parser.QuoteDataError):parser.evidence_quote("TSM",{**raw(),"schema":version},NOW)

    def test_cached_return_and_native_clock_are_revalidated_without_refetch(self):
        value=quote();row={"symbol":"TSM","move":6,"quote_evidence":value["quote_evidence"]}
        self.assertAlmostEqual(parser.cached_regular_quote(row,NOW)["change_percent"],6)
        row["move"]=7
        with self.assertRaises(parser.QuoteDataError):parser.cached_regular_quote(row,NOW)


class RecoveryChecks(PrivateState):
    def test_one_transient_benchmark_failure_uses_one_same_provider_fallback(self):
        calls=[]
        def read(url):
            calls.append(url)
            if len(calls)==1:raise TimeoutError()
            return response(raw("^IXIC",index=True))
        value,result=source.read_chart("^IXIC",read,NOW)
        self.assertEqual(len(calls),2);self.assertIn("query2.finance.yahoo.com",calls[1])
        self.assertTrue(value["ok"]);self.assertEqual(result["request"]["events"],"splits")
        health=source.cached_health(NOW)[0];self.assertEqual(health["session_date"],"2026-11-06")
        self.assertEqual(len(health["attempts"]),2)

    def test_three_benchmarks_share_only_two_extra_reads(self):
        calls=[];budget=source.RecoveryBudget(2)
        def read(url):
            calls.append(url)
            if "query1." in url:raise URLError("offline fixture")
            symbol=next(s for s in source.BENCHMARKS if s[1:] in url)
            return response(raw(symbol,index=True))
        for symbol in source.BENCHMARKS:
            try:source.read_chart(symbol,read,NOW,budget=budget)
            except parser.QuoteDataError:pass
        self.assertEqual(len(calls),5);self.assertEqual(sum("query2." in c for c in calls),2)

    def test_equity_transport_failure_does_not_start_a_benchmark_fallback(self):
        read=Mock(side_effect=TimeoutError())
        with self.assertRaises(parser.QuoteDataError):source.read_chart("TSM",read,NOW)
        self.assertEqual(read.call_count,1)

    def test_403_and_429_are_held_without_an_alternate_host_or_renewed_clock(self):
        for code in (403,429):
            with self.subTest(code=code):
                source.state_path().unlink(missing_ok=True)
                read=Mock(side_effect=HTTPError("https://query1.finance.yahoo.com",code,"fixture",{"Retry-After":"1800"},None))
                with self.assertRaises(parser.QuoteDataError):source.read_chart("^IXIC",read,NOW)
                first=source.cached_health(NOW)[0]
                with self.assertRaisesRegex(parser.QuoteDataError,"cooldown"):source.read_chart("^IXIC",read,NOW+timedelta(minutes=1))
                self.assertEqual(read.call_count,1);self.assertEqual(source.cached_health(NOW+timedelta(minutes=1))[0]["checked_at"],first["checked_at"])

    def test_expired_cooldown_allows_a_new_normal_read(self):
        source.record_health("^IXIC",NOW,[],error="HTTPError 429",retry_at=NOW.timestamp()+900)
        read=Mock(return_value=response(raw("^IXIC",index=True)))
        value,_=source.read_chart("^IXIC",read,NOW+timedelta(minutes=16))
        self.assertTrue(value["ok"]);self.assertEqual(read.call_count,1)

    def test_http_503_can_recover_but_404_cannot(self):
        for code,count in ((503,2),(404,1)):
            source.state_path().unlink(missing_ok=True)
            read=Mock(side_effect=[HTTPError("https://query1.finance.yahoo.com",code,"fixture",{},None),response(raw("^IXIC",index=True))])
            try:source.read_chart("^IXIC",read,NOW)
            except parser.QuoteDataError:pass
            self.assertEqual(read.call_count,count)

    def test_source_identity_or_dated_price_failure_is_not_masked_by_a_retry(self):
        for value in (raw("WRONG",index=True),raw("^IXIC",index=True)):
            if value["meta"]["symbol"]=="^IXIC":value["meta"].pop("regularMarketTime")
            read=Mock(return_value=response(value))
            with self.assertRaises(parser.QuoteDataError):source.read_chart("^IXIC",read,NOW)
            self.assertEqual(read.call_count,1)

    def test_ambiguous_or_oversized_chart_response_is_rejected(self):
        for data in ("bad json", "x"*2_000_001, json.dumps({"chart":{"result":[raw(),raw()],"error":None}})):
            read=Mock(return_value=data)
            with self.assertRaises(parser.QuoteDataError):source.read_chart("TSM",read,NOW)
            self.assertEqual(read.call_count,1)

    def test_health_write_failure_does_not_reject_a_valid_quote(self):
        with patch.object(source.os,"replace",side_effect=OSError("fixture")):
            value,_=source.read_chart("TSM",lambda _:response(raw()),NOW)
        self.assertTrue(value["return_usable"])

    def test_corrupt_health_row_cannot_break_an_independent_valid_quote(self):
        source.state_path().write_text(json.dumps({"schema":1,"symbols":{"TSM":42}}))
        value,_=source.read_chart("TSM",lambda _:response(raw()),NOW)
        self.assertTrue(value["ok"])

    def test_health_observation_expires_without_becoming_current_by_reading_it(self):
        source.read_chart("TSM",lambda _:response(raw()),NOW)
        self.assertEqual(source.cached_health(NOW+timedelta(hours=7)),[])

    def test_adapter_evidence_preserves_original_clocks_values_and_requested_actions(self):
        value,result=source.read_chart("TSM",lambda _:response(raw()),NOW)
        evidence=source.source_evidence(result)
        self.assertEqual(evidence["schema"],2);self.assertEqual(evidence["request"]["events"],"splits")
        self.assertEqual(evidence["meta"]["regularMarketTime"],raw()["meta"]["regularMarketTime"])
        self.assertEqual(parser.evidence_quote("TSM",evidence,NOW)["asof"],value["asof"])


class ActionChecks(PrivateState):
    def review(self,first=None,second=None):
        first=first if first is not None else quote()
        second=second if second is not None else quote()
        return events.review_quotes({"TSM":first},lambda _:second,NOW)[0]

    def test_dated_repeat_with_explicit_action_query_can_be_rechecked(self):
        row=self.review();self.assertEqual(row["verification_version"],2);self.assertEqual(row["status"],"rechecked")
        events.checked_row(row,NOW)

    def test_split_in_first_or_second_read_is_held(self):
        for first,second in ((quote(value=split(raw())),quote()),(quote(),quote(value=split(raw())))):
            events.state_path().unlink(missing_ok=True)
            self.assertEqual(self.review(first,second)["status"],"corporate action check")

    def test_historical_split_before_the_return_interval_does_not_block_current_move(self):
        value=quote(value=split(raw(),OPEN-timedelta(days=3)))
        self.assertTrue(value["return_usable"]);self.assertEqual(self.review(value,value)["status"],"rechecked")

    def test_split_on_previous_closing_day_does_not_get_applied_again(self):
        value=quote(value=split(raw(),OPEN-timedelta(days=1)))
        self.assertEqual(value["previous_close"],100);self.assertAlmostEqual(value["change_percent"],6)
        self.assertEqual(self.review(value,value)["status"],"rechecked")

    def test_future_action_does_not_rewrite_fridays_return(self):
        value=quote(value=split(raw(),OPEN+timedelta(days=3)))
        self.assertEqual(self.review(value,value)["status"],"rechecked")

    def test_utc_midnight_action_does_not_silently_shift_to_the_prior_closing_day(self):
        value=quote(value=split(raw(),OPEN.replace(hour=0,minute=0)))
        self.assertFalse(value["return_usable"])
        self.assertEqual(self.review(value,value)["status"],"corporate action check")

    def test_undated_or_conflicting_action_dates_remain_unverified(self):
        for value in (split(raw(),dated=False),split(raw())):
            if value["events"]["splits"].get(str(int(OPEN.timestamp()))):
                value["events"]["splits"][str(int(OPEN.timestamp()))]["date"]=(OPEN-timedelta(days=2)).timestamp()
            result=quote(value=value)
            self.assertFalse(result["return_usable"])

    def test_missing_action_query_cannot_attest_to_split_coverage(self):
        value=raw();value.pop("request")
        result=parser.parse_regular_quote("TSM",value,NOW,profile=2)
        self.assertFalse(result["return_usable"]);self.assertEqual(result["action_check"],"split query not recorded")

    def test_two_matching_extreme_prices_are_not_an_independent_price_basis_review(self):
        value=quote(price=150)
        self.assertEqual(self.review(value,value)["status"],"price basis review")

    def test_daily_returns_that_changed_materially_do_not_count_as_agreement(self):
        self.assertEqual(self.review(quote(price=106),quote(price=107))["status"],"quote changed; check pending")

    def test_cached_legacy_repeat_is_not_used_as_a_new_version_check(self):
        legacy=quote();legacy["quote_evidence"].pop("schema")
        for key in ("return_usable","return_note","action_check","quote_schema"):legacy.pop(key,None)
        events.review_quotes({"TSM":legacy},lambda _:legacy,NOW)
        fetch=Mock(return_value=quote())
        row=events.review_quotes({"TSM":quote()},fetch,NOW+timedelta(minutes=1))[0]
        self.assertEqual(fetch.call_count,1);self.assertEqual(row["verification_version"],2)

    def test_new_first_quote_does_not_renew_the_repeat_read_clock(self):
        first=self.review();second=events.review_quotes({"TSM":quote()},Mock(side_effect=AssertionError("Unexpected extra read")),NOW+timedelta(minutes=5))[0]
        self.assertEqual(first["recheck_at"],second["recheck_at"])

    def test_tampering_with_return_qualifications_is_rejected(self):
        value=quote(value=split(raw()));value["return_usable"]=True
        with self.assertRaises(ValueError):events.packet(value,"TSM",NOW)

    def test_quarantined_returns_do_not_enter_breadth_or_the_price_report(self):
        bad=quote(price=150);good=quote("AMD",103)
        rows=daily_report.collect_watchlist_movers(["TSM","AMD"],{"TSM":bad,"AMD":good})
        self.assertEqual([row["symbol"] for row in rows],["AMD"])
        self.assertIsNone(daily_report.get_quote_change_percent(bad))


class EditionChecks(IsolatedChecks):
    def test_new_context_qualification_is_source_bound_and_legacy_context_still_checks(self):
        report=self.research(replacements={"Watchlist Movers":"• TSM: $106.00 (+6.00%)"})
        context=events.context_for_report(report,EDITOR_NOW)
        self.assertEqual(context["schema"],2);events.checked_context(context,report,EDITOR_NOW)
        changed=deepcopy(context);changed["events"][0]["verification_note"]="Confirmed by an independent exchange"
        with self.assertRaises(ValueError):events.checked_context(changed,report,EDITOR_NOW)
        legacy=deepcopy(context);legacy["schema"]=1;legacy["events"][0].pop("verification_note")
        events.checked_context(legacy,report,EDITOR_NOW)

    def test_frozen_rules28_report_script_and_schema2_export_are_unchanged(self):
        record=json.loads((ROOT/'scripts/fixtures/market_rules28_edition.json').read_text())
        self.assertEqual(record["report_sha256"],"2b5cc4b540fc5b5216f5163e7e0ef97e65acbcb15d067a709cbe1398e0a2da47")
        self.assertEqual(voice.checked(record,EDITOR_NOW)["script_sha256"],"450057ccdd4ddee42262d7febd1956273346596c06a07b58ec4819f3769c6190")
        self.assertEqual(voice.episode(record,EDITOR_NOW)["voiceover_sha256"],record["voiceover"]["script_sha256"])

    def test_new_edition_keeps_original_disclosure_facts_and_passes_quality(self):
        with patch.object(editor,"cache_candidates",return_value=([maintenance(),sanctions()],[])):
            report=build_daily_news_brief(self.research())
        record=store.read_editions(report=report)[0]
        self.assertEqual(record["rules_version"],32);self.assertTrue(validate_news_brief(report)["passes"])
        self.assertEqual(sum(len(s["event_evidence"]["facts"]) for s in editor.selected_stories(record)),8)
        self.assertTrue(voice.checked(record,EDITOR_NOW)["quality"]["passes"])

    def test_new_market_backdrop_does_not_mix_friday_and_thursday_sessions(self):
        first=quote("^GSPC",value=raw("^GSPC",index=True))
        earlier=raw("^IXIC",index=True)
        earlier["meta"]["regularMarketTime"]-=86400
        earlier["meta"]["currentTradingPeriod"]["regular"]={k:v-86400 for k,v in earlier["meta"]["currentTradingPeriod"]["regular"].items()}
        earlier["timestamp"]=[x-86400 for x in earlier["timestamp"]]
        second=quote("^IXIC",value=earlier)
        payload={"cached_at":NOW.timestamp(),"market_moves":[{"symbol":q["symbol"],"move":round(q["change_percent"],2),"quote_evidence":q["quote_evidence"]} for q in (first,second)]}
        result=research_context.market_quotes(payload,NOW)
        self.assertEqual(set(result),{"^GSPC"})

    def test_friday_macro_snapshot_does_not_relabel_thursday_watchlist_breadth(self):
        q=quote("^GSPC",value=raw("^GSPC",index=True))
        payload={"cached_at":NOW.timestamp(),"market_moves":[{"symbol":"^GSPC","move":round(q["change_percent"],2),"quote_evidence":q["quote_evidence"]}]}
        context,rows=research_context.align_report_sessions({"_market_payload":payload},[{"symbol":"AMD","session_date":"2026-11-05","change_percent":3}],NOW)
        self.assertFalse(rows);self.assertIn("^GSPC",research_context.market_quotes(context["_market_payload"],NOW))

    def test_a_newer_watchlist_session_withholds_older_macro_prices(self):
        earlier=raw("^GSPC",index=True)
        earlier["meta"]["regularMarketTime"]-=86400
        earlier["meta"]["currentTradingPeriod"]["regular"]={k:v-86400 for k,v in earlier["meta"]["currentTradingPeriod"]["regular"].items()}
        earlier["timestamp"]=[x-86400 for x in earlier["timestamp"]]
        q=quote("^GSPC",value=earlier)
        payload={"cached_at":NOW.timestamp(),"market_moves":[{"symbol":"^GSPC","move":round(q["change_percent"],2),"quote_evidence":q["quote_evidence"]}]}
        movers=[{"symbol":"AMD","session_date":"2026-11-06","change_percent":3}]
        context,rows=research_context.align_report_sessions({"_market_payload":payload},movers,NOW)
        self.assertEqual(rows,movers);self.assertEqual(context["_market_payload"]["market_moves"],[])
        self.assertEqual(len(payload["market_moves"]),1)

    def test_valid_benchmark_session_remains_visible_without_a_watchlist(self):
        q=quote("^GSPC",value=raw("^GSPC",index=True))
        payload={"cached_at":NOW.timestamp(),"market_moves":[{"symbol":"^GSPC","move":round(q["change_percent"],2),"quote_evidence":q["quote_evidence"]}]}
        context,rows=research_context.align_report_sessions({"_market_payload":payload},[],NOW)
        snapshot=daily_report.build_market_snapshot([],rows,market_context=context)
        self.assertIn("Quote session: 2026-11-06",snapshot)
        self.assertIn("watchlist breadth unavailable",snapshot);self.assertNotIn("Breadth: 0",snapshot)

    def test_news_brief_keeps_benchmark_moves_when_watchlist_breadth_is_unavailable(self):
        snapshot=daily_report.build_market_snapshot([],[],market_context={"_benchmark_session":"2026-11-06"})
        research=self.research(now=NOW,replacements={"Market Snapshot":snapshot,"Executive Summary":"- Main theme: dated benchmark context.\n- Market moves: S&P +0.31%, Nasdaq +1.09%, Russell +0.89%, VIX -9.01%, Oil +0.13%, TLT -0.01%."})
        with patch.object(editor,"cache_candidates",return_value=([],[])):
            report=build_daily_news_brief(research)
        self.assertIn("completed regular session 2026-11-06",report)
        self.assertIn("Nasdaq Composite rose 1.09 percent",report)
        self.assertNotIn("0 finished higher",report);self.assertTrue(validate_news_brief(report)["passes"])

    def test_editorstatus_reports_benchmark_source_health_without_relabeling_a_missing_quote(self):
        rows=[{"symbol":"^IXIC","status":"limited","reason":"HTTPError 429","checked_at":EDITOR_NOW.isoformat(),"attempts":[{"host":"query1.finance.yahoo.com","status":"HTTPError 429"}]}]
        with patch('src.utils.market_quote_source.cached_health',return_value=rows),patch.object(editor,"cache_candidates",return_value=([maintenance()],[])):
            build_daily_news_brief(self.research())
        status=editor.build_editor_status()
        self.assertIn("Quote check: Nasdaq — limited",status);self.assertIn("HTTPError 429",status)


def main():
    parser_arg=argparse.ArgumentParser();parser_arg.add_argument("--windows-socketpair",action="store_true");args=parser_arg.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        temporary=stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ,{"MARKET_QUOTE_STATUS_FILE":str(Path(temporary)/'health.json')}))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in (PriceChecks,RecoveryChecks,ActionChecks,EditionChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Market Resilience Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=='__main__':raise SystemExit(main())
