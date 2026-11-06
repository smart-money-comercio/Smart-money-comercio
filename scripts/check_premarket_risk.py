"""Offline synthetic price, original-disclosure and frozen-evidence regressions."""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.check_special_alerts import offline_network_guard,portable_tcp_socketpair
from src.config.premarket import settings,SYMBOLS,CHIPS
from src.intelligence import premarket_sources as sources,premarket_risk as risk,premarket_disclosures as docs
from src.reports import daily_voiceover as voice

NOW=datetime(2026,11,5,13,45,tzinfo=timezone.utc)


def chart(symbol="SPY",move=0,now=NOW,previous=None,end_hour=16):
    local=now.astimezone(sources.NY);opened=local.replace(hour=9,minute=30,second=0,microsecond=0);pre=opened.replace(hour=4,minute=0)
    day=previous or local.date()-timedelta(days=1)
    while day.weekday()>4:day-=timedelta(days=1)
    a=datetime.combine(day,opened.timetz());b=a.replace(hour=end_hour,minute=0)
    period=lambda x,y:{"start":int(x.timestamp()),"end":int(y.timestamp())}
    future=symbol in {"NQ=F","ES=F"};kind="FUTURE" if future else "ETF" if symbol in {"SPY","QQQ","SMH"} else "EQUITY"
    meta={"symbol":symbol,"currency":"USD","instrumentType":kind,"dataGranularity":"5m","shortName":symbol+" synthetic",
          "currentTradingPeriod":{"pre":period(pre,opened),"regular":period(opened,opened.replace(hour=16,minute=0))},
          "tradingPeriods":{"regular":[[period(a,b)],[period(opened,opened.replace(hour=16,minute=0))]]},
          "regularMarketPrice":12345,"regularMarketTime":int((now+timedelta(hours=8)).timestamp())}
    if future:meta["currentTradingPeriod"]["regular"]=period(local.replace(hour=0,minute=0),local.replace(hour=23,minute=59))
    return {"meta":meta,"timestamp":[int((b-timedelta(minutes=5)).timestamp()),int((now-timedelta(minutes=10)).timestamp()),int((now-timedelta(minutes=5)).timestamp())],
            "indicators":{"quote":[{"close":[100,100+move,100+move],"volume":[1000,0,0]}]}}


def quotes(moves=None,now=NOW):
    moves=moves or {};config=settings();anchor=sources.packet("SPY",chart("SPY",moves.get("SPY",0),now),now,config)
    result={"SPY":anchor}
    for symbol in SYMBOLS[1:]:result[symbol]=sources.packet(symbol,chart(symbol,moves.get(symbol,0),now),now,config,anchor["session"])
    return result


PRESSURE={"NQ=F":-.7,"ES=F":.1,"QQQ":-.6,"SMH":-1.6,"QCOM":-8,"ARM":-5,"NVDA":-3.5}
SEVERE={"SPY":-1.7,"QQQ":-2.3,"SMH":-3.5,"QCOM":-7,"ARM":-6,"NVDA":-5.5}
COST="The semiconductor industry is experiencing a broad-based increase in input costs across wafer fabrication and packaging."


def document(text=COST):
    from hashlib import sha256
    body="Qualcomm Announces Fourth Quarter and Fiscal 2026 Results. "+text
    return {"symbol":"QCOM","title":"Qualcomm Announces Fourth Quarter and Fiscal 2026 Results","text":body,
            "published":(NOW-timedelta(hours=16)).isoformat(),"observed":NOW.isoformat(),"source":"SEC EDGAR original earnings exhibit",
            "url":"https://www.sec.gov/Archives/edgar/data/804328/000080432826000127/ex99.htm",
            "filing_url":"https://www.sec.gov/Archives/edgar/data/804328/000080432826000127/qcom8k.htm",
            "accession":"0000804328-26-000127","sha256":sha256(body.encode()).hexdigest()}


def snapshot(moves=None,now=NOW,slot="08:45",documents=None):
    return risk.snapshot(quotes(moves,now),documents or [],[],now,settings(),slot)


class SourceChecks(unittest.TestCase):
    def test_original_three_bars_define_a_dated_premarket_gap(self):
        row=sources.packet("SPY",chart(move=-1),NOW,settings())
        self.assertEqual(row["change"],-1);self.assertEqual(row["price"],99)
        self.assertEqual(row["asof"],NOW.isoformat());self.assertEqual(row["baseline_at"],"2026-11-04T21:00:00+00:00")

    def test_regular_market_metadata_prices_cannot_supply_premarket_prices(self):
        row=sources.packet("SPY",chart(move=-1),NOW,settings());self.assertNotEqual(row["price"],12345)

    def test_wrong_identity_type_currency_or_granularity_is_withheld(self):
        for key,value in (("symbol","QQQ"),("instrumentType","INDEX"),("currency","EUR"),("dataGranularity","1d")):
            raw=chart();raw["meta"][key]=value
            with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_before_window_after_open_and_weekends_make_no_requests(self):
        for now in (NOW.replace(hour=12),NOW.replace(hour=14,minute=30),NOW+timedelta(days=2)):
            values,issues=sources.collect(now,settings(),lambda _:self.fail("No request outside the check window"))
            self.assertEqual(values,{});self.assertTrue(issues)

    def test_a_naive_research_clock_is_rejected(self):
        with self.assertRaises(ValueError):sources.window(NOW.replace(tzinfo=None))

    def test_regular_session_hours_must_match_today(self):
        raw=chart();raw["meta"]["currentTradingPeriod"]["regular"]["start"]-=86400
        with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_prior_close_is_bound_to_the_latest_dated_session(self):
        raw=chart();raw["timestamp"][0]-=86400
        with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_an_early_close_uses_its_own_last_bar(self):
        row=sources.packet("SPY",chart(end_hour=13),NOW,settings())
        self.assertEqual(row["baseline_at"],"2026-11-04T18:00:00+00:00")

    def test_after_hours_bars_do_not_replace_the_regular_close(self):
        raw=chart();raw["timestamp"].insert(1,raw["timestamp"][0]+300)
        raw["indicators"]["quote"][0]["close"].insert(1,110);raw["indicators"]["quote"][0]["volume"].insert(1,100)
        self.assertEqual(sources.packet("SPY",raw,NOW,settings())["baseline_price"],100)

    def test_future_or_unfinished_bars_do_not_supply_current_prices(self):
        raw=chart(move=-1)
        for key,number in (("timestamp",int(NOW.timestamp())),):raw[key].append(number)
        raw["indicators"]["quote"][0]["close"].append(1);raw["indicators"]["quote"][0]["volume"].append(100)
        self.assertEqual(sources.packet("SPY",raw,NOW,settings())["price"],99)

    def test_one_bar_nonconsecutive_bars_and_stale_bars_are_withheld(self):
        for minutes in (20,30):
            raw=chart();raw["timestamp"][-1]-=minutes*60;raw["timestamp"][-2]-=minutes*60
            with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())
        raw=chart();raw["timestamp"][-2]-=300
        with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_null_or_nonfinite_prices_cannot_create_a_gap(self):
        for value in (None,float("nan"),False,-1):
            raw=chart();raw["indicators"]["quote"][0]["close"][-1]=value
            with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_a_large_or_inconsistent_gap_remains_under_review(self):
        for first,last in ((-50,-50),(-8,-2)):
            raw=chart();raw["indicators"]["quote"][0]["close"][-2:]=[100+first,100+last]
            with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_split_or_dividend_exdate_at_the_upcoming_open_is_withheld(self):
        for kind in ("splits","dividends"):
            raw=chart();raw["events"]={kind:{"event":{"date":raw["meta"]["currentTradingPeriod"]["regular"]["start"]}}}
            with self.assertRaises(ValueError):sources.packet("SPY",raw,NOW,settings())

    def test_futures_need_the_cash_session_anchor(self):
        with self.assertRaises(ValueError):sources.packet("NQ=F",chart("NQ=F"),NOW,settings())

    def test_futures_use_cash_close_bars_instead_of_an_undated_settlement_field(self):
        anchor=sources.packet("SPY",chart(),NOW,settings())["session"]
        raw=chart("NQ=F",-.7);raw["meta"]["previousClose"]=50
        row=sources.packet("NQ=F",raw,NOW,settings(),anchor)
        self.assertEqual(row["change"],-.7);self.assertIn("not settlement",row["basis"])

    def test_continuous_contract_roll_window_is_withheld(self):
        now=NOW.replace(month=12,day=10);anchor=sources.packet("SPY",chart(now=now),now,settings())["session"]
        with self.assertRaises(ValueError):sources.packet("NQ=F",chart("NQ=F",now=now),now,settings(),anchor)

    def test_dst_changes_utc_clock_without_changing_local_check_time(self):
        summer=datetime(2026,7,8,12,45,tzinfo=timezone.utc)
        row=sources.packet("SPY",chart(now=summer),summer,settings())
        self.assertEqual(datetime.fromisoformat(row["session"]["open"]).astimezone(sources.NY).utcoffset(),timedelta(hours=-4))
        self.assertEqual(sources.NY.utcoffset(NOW.astimezone(sources.NY)),timedelta(hours=-5))

    def test_frozen_price_proof_is_small_and_drops_later_bars(self):
        row=sources.packet("SPY",chart(),NOW,settings());proof=row["evidence"]
        self.assertEqual(len(proof["timestamp"]),3);self.assertLess(len(json.dumps(proof)),5000)
        self.assertNotIn("regularMarketPrice",proof["meta"])

    def test_zero_premarket_volume_is_explicitly_unverified(self):
        row=sources.packet("SPY",chart(),NOW,settings())
        self.assertIn("volume unverified",row["source"])

    def test_collector_makes_at_most_the_fixed_thirteen_requests(self):
        calls=[]
        rows,issues=sources.collect(NOW,settings(),lambda symbol:(calls.append(symbol) or chart(symbol)))
        self.assertEqual(set(calls),set(SYMBOLS));self.assertEqual(len(calls),13);self.assertEqual(len(rows),13);self.assertFalse(issues)

    def test_a_missing_spy_anchor_never_falls_back_to_yesterday(self):
        def read(symbol):
            if symbol=="SPY":raise ValueError("Missing")
            return chart(symbol)
        rows,issues=sources.collect(NOW,settings(),read);self.assertFalse(rows);self.assertTrue(issues)


class AssessmentChecks(unittest.TestCase):
    def test_chip_futures_divergence_and_group_weakness_support_elevated_sector_risk(self):
        value=snapshot(PRESSURE);a=value["assessment"]
        self.assertEqual(a["level"],"ELEVATED");self.assertIn("semiconductors",a["scope"])
        self.assertNotIn("broad",[s["id"] for s in a["signals"]])

    def test_an_isolated_future_signal_is_watch(self):
        self.assertEqual(snapshot({"NQ=F":-.7,"ES=F":.1})["assessment"]["level"],"WATCH")

    def test_broad_etf_and_semiconductor_pressure_can_be_severe(self):
        self.assertEqual(snapshot(SEVERE)["assessment"]["level"],"SEVERE")

    def test_three_chip_gaps_are_a_scoped_group_signal(self):
        value=snapshot({"QCOM":-8,"ARM":-5,"AMD":-4})
        self.assertEqual(value["assessment"]["level"],"WATCH")
        self.assertIn("3 of 5",value["assessment"]["signals"][0]["text"])

    def test_missing_prices_are_limited_and_never_a_calm_signal(self):
        for values in ({},{"SPY":quotes()["SPY"]}):
            self.assertEqual(risk.assess(values,[],NOW,settings())["level"],"LIMITED")

    def test_missing_sector_coverage_does_not_become_none(self):
        values={s:r for s,r in quotes().items() if s in {"SPY","QQQ"}}
        self.assertEqual(risk.assess(values,[],NOW,settings())["level"],"LIMITED")

    def test_complete_quiet_evidence_has_no_qualifying_signal(self):
        self.assertEqual(snapshot()["assessment"]["level"],"NONE")

    def test_a_recovered_latest_bar_cannot_supply_a_two_bar_decline(self):
        values=quotes();raw=chart("SMH",-2);raw["indicators"]["quote"][0]["close"][-1]=100
        values["SMH"]=sources.packet("SMH",raw,NOW,settings(),values["SPY"]["session"])
        self.assertEqual(risk.assess(values,[],NOW,settings())["level"],"NONE")

    def test_negative_disclosure_requires_matching_price_evidence(self):
        value=snapshot(documents=[document()]);self.assertEqual(value["assessment"]["level"],"NONE")
        value=snapshot({"QCOM":-8,"ARM":-5,"AMD":-4},documents=[document()])
        self.assertEqual(value["assessment"]["level"],"ELEVATED")

    def test_positive_or_speculative_company_text_cannot_vote_for_risk(self):
        for text in ("The company's revenue increased 20% in the latest quarter.","The company could experience a revenue decline.","We have not reduced our revenue guidance."):
            self.assertFalse(docs.risk_sentences(text))

    def test_explicit_reported_decline_and_cut_outlook_keep_distinct_fields(self):
        self.assertEqual(docs.risk_sentences("Revenue fell 12% in the reported quarter.")[0]["field"],"reported_business_decline")
        self.assertEqual(docs.risk_sentences("We have lowered our revenue guidance.")[0]["field"],"disclosed_outlook_reduction")

    def test_post_cutoff_and_pre_close_disclosures_are_rejected(self):
        for key,when in (("published",NOW+timedelta(minutes=1)),("observed",NOW+timedelta(minutes=1)),("published",NOW-timedelta(days=2))):
            row=document();row[key]=when.isoformat()
            with self.assertRaises(ValueError):snapshot(PRESSURE,documents=[row])

    def test_spoofed_document_or_wrong_sec_accession_is_rejected(self):
        for url in ("https://sec.gov.example.com/Archives/edgar/data/804328/000080432826000127/ex99.htm", "https://www.sec.gov/Archives/edgar/data/1/000080432826000127/ex99.htm"):
            row=document();row["url"]=url
            with self.assertRaises(ValueError):snapshot(PRESSURE,documents=[row])

    def test_changed_fact_text_or_displayed_quote_breaks_frozen_validation(self):
        for change in ("text","quote"):
            value=snapshot(PRESSURE,documents=[document()])
            if change=="text":value["documents"][0]["text"]+=" Invented."
            else:value["quotes"]["SPY"]["change"]=-99
            with self.assertRaises(ValueError):risk.checked(value)

    def test_rehashing_a_false_displayed_price_cannot_bypass_source_validation(self):
        value=snapshot(PRESSURE);value["quotes"]["QCOM"]["change"]=-50
        value.pop("id");value["id"]=risk.digest(value)
        with self.assertRaises(ValueError):risk.checked(value)

    def test_render_retains_timestamp_scope_uncertainty_and_volume_limits(self):
        text=risk.render(snapshot(PRESSURE,documents=[document()]))
        for phrase in ("08:45 EST","ELEVATED","volume is unverified","not exchange-settlement","later direction and size","receipts are recorded separately"):
            self.assertIn(phrase,text)
        self.assertLessEqual(len(text),3900)

    def test_saved_thresholds_replay_after_environment_changes(self):
        value=snapshot(PRESSURE)
        with patch.dict(os.environ,{"PREMARKET_CHIP_GAP_PERCENT":"9"}):self.assertEqual(risk.checked(value),value)

    def test_bad_frozen_configuration_cannot_bypass_validation(self):
        value=snapshot(PRESSURE);value["config"]["max_age"]=999999;value.pop("id");value["id"]=risk.digest(value)
        with self.assertRaises(ValueError):risk.checked(value)

    def test_a_slot_cannot_be_backdated_from_a_different_time(self):
        value=snapshot(PRESSURE);value["slot"]="09:15";value.pop("id");value["id"]=risk.digest(value)
        with self.assertRaises(ValueError):risk.checked(value)

    def test_preview_has_a_distinct_identity(self):
        self.assertNotEqual(snapshot(PRESSURE)["id"],snapshot(PRESSURE,slot="preview")["id"])


class SecChecks(unittest.TestCase):
    def fixture(self,change=None):
        row=document();base=row["filing_url"];exhibit=row["url"]
        metadata={"cik":804328,"name":"QUALCOMM Incorporated","tickers":["QCOM"],"filings":{"recent":{
            "accessionNumber":[row["accession"]],"form":["8-K"],"acceptanceDateTime":[row["published"]],"primaryDocument":["qcom8k.htm"],"items":["2.02,9.01"]}}}
        primary="".join(f'<ix:nonnumeric name="dei:{key}">{value}</ix:nonnumeric>' for key,value in
            (("EntityCentralIndexKey","804328"),("EntityRegistrantName","QUALCOMM Incorporated"),("TradingSymbol","QCOM"),("DocumentType","8-K")))
        primary+='<p>Item 2.02 Results. A press release is furnished as Exhibit 99.1.</p><a href="ex99.htm">99.1</a>'
        body='<h1>Qualcomm Announces Fourth Quarter and Fiscal 2026 Results</h1><p>SAN DIEGO - November 4, 2026 - Qualcomm Incorporated today reported its results.</p><p>'+COST+'</p>'
        if change:metadata,primary,body=change(metadata,primary,body)
        payloads={docs.QCOM_SUBMISSIONS:json.dumps(metadata),base:primary,exhibit:body};calls=[]
        def read(url):
            calls.append(url);return {"url":url,"final_url":url,"status":"ok","body":payloads[url],"fetched_at_epoch":NOW.timestamp()}
        return read,calls

    def test_original_sec_read_binds_issuer_filing_clock_and_unique_exhibit(self):
        fetch,calls=self.fixture();row=docs.qualcomm(NOW,fetch)
        self.assertEqual(len(calls),3);self.assertEqual(row["symbol"],"QCOM")
        self.assertTrue(docs.risk_sentences(row["text"]));docs.checked_document(row)

    def test_a_wrong_issuer_is_rejected_before_following_documents(self):
        def change(m,p,b):m["cik"]=1;return m,p,b
        fetch,calls=self.fixture(change)
        with self.assertRaises(ValueError):docs.qualcomm(NOW,fetch)
        self.assertEqual(len(calls),1)

    def test_the_sec_legal_name_alias_still_requires_the_exact_cik_and_ticker(self):
        def change(m,p,b):m["name"]="QUALCOMM INC/DE";return m,p,b
        fetch,calls=self.fixture(change);self.assertEqual(docs.qualcomm(NOW,fetch)["symbol"],"QCOM");self.assertEqual(len(calls),3)

    def test_a_known_amendment_blocks_older_results(self):
        def change(m,p,b):m["filings"]["recent"]["form"]=["8-K/A"];return m,p,b
        fetch,calls=self.fixture(change)
        with self.assertRaises(ValueError):docs.qualcomm(NOW,fetch)
        self.assertEqual(len(calls),1)

    def test_an_old_release_does_not_consume_detail_requests(self):
        def change(m,p,b):m["filings"]["recent"]["acceptanceDateTime"]=[(NOW-timedelta(hours=25)).isoformat()];return m,p,b
        fetch,calls=self.fixture(change);self.assertIsNone(docs.qualcomm(NOW,fetch));self.assertEqual(len(calls),1)

    def test_external_exhibit_links_and_mismatched_release_dates_are_withheld(self):
        for change in (lambda m,p,b:(m,p.replace('href="ex99.htm"','href="https://example.com/ex99.htm"'),b),
                       lambda m,p,b:(m,p,b.replace("November 4","November 3"))):
            fetch,_=self.fixture(change)
            with self.assertRaises(ValueError):docs.qualcomm(NOW,fetch)

    def test_missing_sec_configuration_makes_no_sec_requests(self):
        from src.intelligence import news_editor as editor
        with patch.dict(os.environ,{"SEC_USER_AGENT":""}),patch.object(editor,"cache_candidates",return_value=([],[])):
            rows,issues=docs.collect(NOW,NOW-timedelta(hours=17),lambda _:self.fail("No SEC call without configured identity"))
        self.assertFalse(rows);self.assertIn("SEC_USER_AGENT",issues[0])


class CompatibilityChecks(unittest.TestCase):
    def test_saved_rules25_report_script_and_schema2_export_are_unchanged(self):
        row=json.loads((ROOT/"scripts/fixtures/premarket_rules25_edition.json").read_text())
        old=datetime.fromisoformat(row["generated_at"])
        self.assertEqual(row["report_sha256"],"b6b21ab9140f7aa2ae4c70d9d256f0b9dd2597e10a3210be3bfeb9c2ae0115ba")
        self.assertEqual(voice.checked(row,old)["script_sha256"],"e3cec385ba544b36c69e0fed581203f471768995ebd7abbd04231077b8bcb2b1")
        self.assertEqual(voice.episode(row,old)["voiceover_schema"],2)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--windows-socketpair",action="store_true");args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,"socketpair",portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (SourceChecks,AssessmentChecks,SecChecks,CompatibilityChecks))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    good=result.wasSuccessful() and not traffic["blocked"]
    print(f"Premarket Risk Check: {'PASS' if good else 'FAIL'} ({result.testsRun} tests)")
    return 0 if good else 1


if __name__=="__main__":raise SystemExit(main())
