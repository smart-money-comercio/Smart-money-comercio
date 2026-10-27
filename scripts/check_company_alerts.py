"""Offline checks for company publisher evidence, cached coverage and event reviews."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.config.special_alerts import settings
from src.intelligence import special_alert_company_sources as publishers
from src.intelligence import special_alert_engine as engine
from src.intelligence import special_alert_sources as sources
from src.intelligence import special_alert_universe as universe
from src.jobs import special_alert_scheduler as scheduler

NOW = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
CORE = ['TSLA', 'NVDA', 'MSFT', 'AVGO', 'PLTR', 'AVAV', 'KTOS', 'CRWD']


def config():
    return {**settings(), 'symbols': CORE.copy(), 'top_count': 10, 'ipo_enabled': False}


def feed(symbol='MSFT', title='Introducing a new cloud platform', link=None, published='Tue, 20 Oct 2026 17:00:00 GMT'):
    link = link or {'MSFT':'https://blogs.microsoft.com/blog/platform', 'NVDA':'https://nvidianews.nvidia.com/news/chip'}[symbol]
    return ('<rss><channel><item><title>' + title + '</title><link>' + link + '</link><pubDate>' + published + '</pubDate></item></channel></rss>').encode()


def item(symbol='PLTR', title='Palantir wins a $250 million Army contract', **overrides):
    return {'symbol':symbol, 'title':title, 'published':(NOW-timedelta(minutes=5)).isoformat(),
            'url':'https://finance.yahoo.com/news/company-event', 'source':'finance.yahoo.com',
            'official':False, **overrides}


def pltr_row(date='10/20/2026 13:00:00', **overrides):
    return {'Headline':'Palantir wins new Army contract', 'PressReleaseDate':date,
            'LinkToDetailPage':'/news-details/2026/Palantir-wins-new-Army-contract/default.aspx',
            'Body':'<a href="https://cts.businesswire.com/ct/CT?newsitemid=20261020123456&amp;id=link">Source</a>', **overrides}


def release_page(title='Palantir wins new Army contract', date='2026-10-20T13:00:00-04:00', **extra):
    data={'@type':'NewsArticle', 'headline':title, 'datePublished':date, **extra}
    return ('<script type="application/ld+json">'+json.dumps(data)+'</script>').encode()


class UniverseChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'rankings.json'

    def select(self, entries=None, day='2026-10-20', cfg=None):
        value={'current_date':day,'current':entries if entries is not None else {
            'MSFT':{'opportunity_score':90,'structural_score':87},
            'TSM':{'opportunity_score':85,'structural_score':86},
            'AMD':{'opportunity_score':80,'structural_score':78}}}
        self.path.write_text(json.dumps(value));before=self.path.read_bytes()
        result=universe.company_universe(cfg or config(),NOW,self.path)
        self.assertEqual(before,self.path.read_bytes())
        return result

    def test_core_is_preserved_and_ranked_companies_are_deduplicated(self):
        result=self.select()
        self.assertEqual(result['symbols'],CORE+['TSM','AMD'])
        self.assertEqual(result['ranked'],['MSFT','TSM','AMD'])

    def test_order_uses_cached_opportunity_then_structural_score(self):
        result=self.select({'AAA':{'opportunity_score':80,'structural_score':70},'BBB':{'opportunity_score':80,'structural_score':90}})
        self.assertEqual(result['ranked'],['BBB','AAA'])

    def test_top_ten_is_bounded_and_can_be_disabled(self):
        entries={f'T{i}':{'opportunity_score':100-i,'structural_score':80} for i in range(20)}
        self.assertEqual(len(self.select(entries)['ranked']),10)
        cfg=config();cfg['top_count']=0
        self.assertEqual(self.select(entries,cfg=cfg)['symbols'],CORE)

    def test_invalid_scores_and_ticker_paths_cannot_enter_the_universe(self):
        entries={name:{'opportunity_score':value,'structural_score':80} for name,value in [
            ('NAN',float('nan')),('INF',float('inf')),('BOOL',True),('BIG',10**500),('STR','99'),('NEG',-1),('OVER',101),('../BAD',99),('GOOD',80)]}
        self.assertEqual(self.select(entries)['ranked'],['GOOD'])

    def test_missing_malformed_stale_and_future_rankings_keep_core(self):
        self.assertEqual(universe.company_universe(config(),NOW,self.path)['symbols'],CORE)
        self.path.write_text('{')
        self.assertEqual(universe.company_universe(config(),NOW,self.path)['symbols'],CORE)
        for day in ('2026-10-15','2026-10-21'):
            with self.subTest(day=day):self.assertEqual(self.select(day=day)['symbols'],CORE)

    def test_weekend_snapshot_is_allowed_and_date_is_disclosed(self):
        self.assertIn('2026-10-16',self.select(day='2026-10-16')['ranking_status'])

    def test_historical_uppercase_data_is_not_used_as_live_rankings(self):
        nested=Path(self.temp.name)/'Data';nested.mkdir()
        (nested/self.path.name).write_text('{"current_date":"2026-10-20","current":{}}')
        self.assertEqual(universe.company_universe(config(),NOW,self.path)['ranked'],[])

    def test_selector_has_no_network_rescore_or_write_side_effect(self):
        from src.scoring import scoring_engine
        with patch.object(scoring_engine,'get_stock_scores',side_effect=AssertionError('Rescore forbidden')):
            self.select()


class PublisherChecks(unittest.TestCase):
    def test_official_publisher_can_supply_a_headline_without_its_company_name(self):
        result=sources.parse_feed(feed(),['MSFT'],'MSFT official',publisher_symbol='MSFT')
        self.assertEqual(result[0]['publisher_symbol'],'MSFT')
        self.assertTrue(result[0]['official'])
        self.assertEqual(result[0]['published'],'2026-10-20T17:00:00+00:00')
        self.assertEqual(sources.parse_feed(feed(),['MSFT'],'headlines'),[])

    def test_official_feed_does_not_promote_external_links(self):
        for link in ('https://microsoft.com.example.com/news','https://finance.yahoo.com/news/story','http://blogs.microsoft.com/news'):
            with self.subTest(link=link):self.assertEqual(sources.parse_feed(feed(link=link),['MSFT'],'official',publisher_symbol='MSFT'),[])

    def test_missing_naive_future_and_old_publications_are_withheld(self):
        for date in ('','2026-10-20T17:00:00','2026-10-21T17:00:00Z','Mon, 19 Oct 2026 17:00:00 GMT'):
            with patch.object(sources,'request_bytes',return_value=feed(published=date)):
                self.assertEqual(publishers.official_company_news('MSFT',NOW,config())[0],[])

    def test_updated_time_does_not_replace_original_publication(self):
        raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Introducing new cloud platform</title><link href="https://blogs.microsoft.com/platform"/><updated>2026-10-20T17:00:00Z</updated></entry></feed>'
        self.assertEqual(sources.parse_feed(raw,['MSFT'],'MSFT official',publisher_symbol='MSFT'),[])

    def test_nvidia_and_microsoft_feeds_are_independent(self):
        def fetch(url):
            if url==publishers.OFFICIAL_FEEDS['NVDA']:raise HTTPError(url,503,'Unavailable',{},None)
            return feed()
        with patch.object(sources,'request_bytes',side_effect=fetch):
            self.assertEqual(len(publishers.official_company_news('MSFT',NOW,config())[0]),1)
            self.assertTrue(publishers.official_company_news('NVDA',NOW,config())[2])

    def test_html_response_is_not_reported_as_a_valid_feed(self):
        with patch.object(sources,'request_bytes',return_value=b'<html><body>blocked</body></html>'):
            items,detail,issues=publishers.official_company_news('MSFT',NOW,config())
        self.assertEqual(items,[]);self.assertIn('unavailable',detail);self.assertTrue(issues)

    def test_short_ticker_does_not_match_common_headline_words(self):
        self.assertFalse(sources.mentions_company('New cloud platform now available on Microsoft Azure','ON'))
        self.assertTrue(sources.mentions_company('onsemi unveils new chip','ON'))

    def test_official_feed_redirect_outside_company_is_rejected(self):
        from unittest.mock import MagicMock
        response=MagicMock();response.__enter__.return_value=response
        response.geturl.return_value='https://example.com/fake-feed'
        with patch.object(sources,'urlopen',return_value=response),self.assertRaisesRegex(ValueError,'redirected'):
            sources.request_bytes(publishers.OFFICIAL_FEEDS['MSFT'])

    def test_original_metadata_requires_matching_title_and_an_explicit_timezone(self):
        self.assertEqual(publishers.publication_time(release_page(),'Palantir wins new Army contract').isoformat(),'2026-10-20T17:00:00+00:00')
        for page in (release_page(title='Different release'),release_page(date='2026-10-20T13:00:00'),release_page(date=None,dateModified=NOW.isoformat())):
            with self.assertRaises(ValueError):publishers.publication_time(page,'Palantir wins new Army contract')

    def test_conflicting_publication_dates_are_not_guessed(self):
        page=release_page()+release_page(date='2026-10-20T12:00:00-04:00')
        with self.assertRaises(ValueError):publishers.publication_time(page,'Palantir wins new Army contract')

    def pltr(self, rows, page=None, now=NOW):
        seen=[]
        def fetch(url):
            seen.append(url)
            if url.startswith(publishers.OFFICIAL_FEEDS['PLTR']):return json.dumps({'GetPressReleaseListResult':rows}).encode()
            if page is None:raise HTTPError(url,403,'Blocked',{},None)
            return page
        with patch.object(sources,'request_bytes',side_effect=fetch):
            result=publishers.official_company_news('PLTR',now,config())
        return result,seen

    def test_palantir_explicitly_zoned_source_date_can_be_used_directly(self):
        result,seen=self.pltr([pltr_row(date='2026-10-20T13:00:00-04:00')])
        self.assertEqual(len(result[0]),1);self.assertEqual(len(seen),1)
        self.assertEqual(result[0][0]['publisher_symbol'],'PLTR')

    def test_palantir_naive_date_needs_original_same_release_wire_time(self):
        result,seen=self.pltr([pltr_row()],release_page())
        self.assertEqual(result[0][0]['published'],'2026-10-20T17:00:00+00:00')
        self.assertIn('20261020123456',result[0][0]['publication_url'])
        self.assertEqual(len(seen),2)

    def test_palantir_blocks_ambiguous_dates_even_when_the_index_is_reachable(self):
        result,_=self.pltr([pltr_row()])
        self.assertEqual(result[0],[]);self.assertTrue(result[2]);self.assertIn('publication times unavailable',result[1])

    def test_changed_palantir_index_date_format_is_explicitly_unavailable(self):
        result,_=self.pltr([pltr_row(date='unknown')])
        self.assertEqual(result[0],[]);self.assertTrue(result[2])
        self.assertIn('unavailable',result[1])

    def test_palantir_old_release_is_not_freshened_by_index_refresh(self):
        result,seen=self.pltr([pltr_row(date='10/01/2026 13:00:00')])
        self.assertEqual(result[0],[]);self.assertEqual(len(seen),1)

    def test_palantir_future_untrusted_and_conflicting_metadata_are_withheld(self):
        for row,page in ((pltr_row(LinkToDetailPage='https://example.com/fake'),release_page()),
                         (pltr_row(),release_page(date='2026-10-21T17:00:00Z')),
                         (pltr_row(),release_page(title='Other company wins contract'))):
            result,_=self.pltr([row],page)
            self.assertEqual(result[0],[])

    def test_palantir_release_followups_are_bounded(self):
        _,seen=self.pltr([pltr_row() for _ in range(20)],release_page())
        self.assertLessEqual(len(seen),4)

    def test_palantir_new_year_reads_both_source_years(self):
        _,seen=self.pltr([],now=datetime(2027,1,1,6,tzinfo=timezone.utc))
        self.assertEqual(len(seen),2)


class EventChecks(unittest.TestCase):
    def event(self,symbol,title,**values):
        return engine.company_alert(item(symbol,title,**values),NOW,config())

    def test_all_core_companies_can_supply_product_evidence(self):
        for symbol,name in [('PLTR','Palantir'),('NVDA','NVIDIA'),('MSFT','Microsoft'),('AVGO','Broadcom'),('AVAV','AeroVironment'),('KTOS','Kratos'),('CRWD','CrowdStrike'),('TSLA','Tesla')]:
            with self.subTest(symbol=symbol):self.assertIsNotNone(self.event(symbol,name+' unveils a new software platform'))

    def test_official_publisher_attribution_is_not_available_to_a_headline_feed(self):
        values={'official':True,'publisher_symbol':'MSFT','url':'https://blogs.microsoft.com/platform'}
        self.assertIsNotNone(self.event('MSFT','Introducing a new cloud platform',**values))
        self.assertIsNone(self.event('MSFT','Introducing a new cloud platform'))
        self.assertIsNone(self.event('MSFT','Introducing a new cloud platform',**{**values,'url':'https://example.com/fake'}))

    def test_official_source_does_not_make_another_company_the_publisher_actor(self):
        self.assertIsNone(self.event('MSFT','NVIDIA unveils a new chip',official=True,publisher_symbol='MSFT',url='https://blogs.microsoft.com/story'))

    def test_contract_guidance_earnings_risk_and_acquisition_are_distinct(self):
        examples=[('PLTR','Palantir wins $250 million Army contract','contract'),
                  ('MSFT','Microsoft raises full-year revenue guidance','guidance'),
                  ('NVDA','NVIDIA reports third-quarter financial results','earnings'),
                  ('MSFT','Microsoft confirms Azure data breach','risk'),
                  ('NVDA','NVIDIA agrees to acquire a robotics company','acquisition')]
        for symbol,title,kind in examples:
            with self.subTest(kind=kind):self.assertEqual(self.event(symbol,title)['event_type'],kind)

    def test_named_joint_partnership_actors_are_both_eligible(self):
        title='NVIDIA and Palantir announce strategic partnership'
        self.assertIsNotNone(self.event('NVDA',title));self.assertIsNotNone(self.event('PLTR',title))

    def test_routine_scheduling_speculation_and_price_chatter_are_not_material_events(self):
        titles=['Palantir announces date of third quarter earnings release','Palantir announces earnings date',
                'Palantir may win a new Army contract','Palantir shares surge on contract hopes',
                'Palantir will report earnings next week','Palantir earnings preview: what to expect']
        for title in titles:
            with self.subTest(title=title):self.assertIsNone(self.event('PLTR',title))

    def test_competitor_or_incidental_ticker_mention_is_not_an_announcement(self):
        self.assertIsNone(self.event('TSLA','Tesla shares fall as NVIDIA unveils new chip'))
        self.assertIsNone(self.event('PLTR','NVIDIA wins new Army contract while Palantir stock falls'))

    def test_missed_confirmation_does_not_upgrade_a_third_party_story(self):
        event=self.event('PLTR','Palantir wins new Army contract')
        self.assertEqual(event['level'],1);self.assertIn('company confirmation pending',event['text'])

    def test_results_schedule_is_not_reported_as_completed_earnings(self):
        for title in ('Palantir will release financial results next week','Palantir to report quarterly results'):
            self.assertIsNone(self.event('PLTR',title))

    def test_palantir_revenue_results_and_strategic_alliances_are_material(self):
        event=self.event('PLTR','Palantir Reports Q2 2026 U.S. Comm Revenue Growth of 149% Y/Y')
        self.assertEqual(event['event_type'],'earnings')
        self.assertEqual(self.event('PLTR','Palantir forms strategic partnership with Microsoft')['event_type'],'contract')

    def test_named_contract_counterparty_can_be_monitored_without_stock_chatter(self):
        title='Palantir announces strategic partnership with Microsoft'
        self.assertIsNotNone(self.event('PLTR',title));self.assertIsNotNone(self.event('MSFT',title))
        self.assertIsNone(self.event('TSLA',title+' while Tesla stock falls'))

    def test_official_publisher_does_not_claim_another_companys_verb_first_reveal(self):
        self.assertIsNone(self.event('MSFT','Introducing NVIDIA Rubin chip',official=True,publisher_symbol='MSFT',url='https://blogs.microsoft.com/story'))

    def test_company_price_clause_does_not_claim_an_unknown_competitors_product(self):
        self.assertIsNone(self.event('TSLA','Tesla shares fall, Acme unveils a new vehicle'))

    def test_palantir_partner_to_deliver_software_is_a_contract_event(self):
        event=self.event('PLTR','Knox and Palantir Partner to Further Accelerate Delivery of Software through Largest Federal Cloud')
        self.assertEqual(event['event_type'],'contract')

    def test_original_product_receipt_key_is_unchanged(self):
        import hashlib
        event=self.event('TSLA','Tesla unveils new Roadster prototype')
        digest=hashlib.sha256(b'TSLA:roadster:Concept / product reveal').hexdigest()[:24]
        self.assertEqual(event['key'],'company:'+digest)

    def test_agent_review_matches_each_event_without_changing_scores(self):
        from src.agents.analyst_agent import review_special_event
        stocks=[{'ticker':'PLTR','final_score':87,'category':'Growth / AI'}];before=deepcopy(stocks)
        event=self.event('PLTR','Palantir wins new Army contract')
        review=review_special_event(event,stocks)
        self.assertIn('contract',review['interpretation']);self.assertIn('funding',review['checks'])
        self.assertFalse(review['score_changes']);self.assertEqual(stocks,before)
        for title,word in [('Palantir raises full-year revenue guidance','guidance'),('Palantir confirms data breach','severity')]:
            review=review_special_event(self.event('PLTR',title),stocks)
            self.assertIn(word,review['checks'])

    def test_official_confirmation_updates_same_company_event(self):
        a=self.event('PLTR','Palantir wins new Army contract')
        b=self.event('PLTR','Palantir wins new Army contract',official=True)
        self.assertEqual(a['key'],b['key']);self.assertGreater(b['level'],a['level'])


class WorkflowChecks(unittest.TestCase):
    def test_cached_extra_company_reaches_collection_and_the_existing_agent(self):
        from src.agents import analyst_agent
        from src.scoring import scoring_engine
        cfg=config();coverage={'symbols':CORE+['TSM'],'core':CORE,'ranked':['TSM'],'ranking_status':'fixture'}
        article=item('TSM','TSMC unveils new processor')
        with patch.object(scheduler,'datetime') as clock,patch.object(scheduler,'settings',return_value=cfg),patch.object(scheduler,'company_universe',return_value=coverage),patch.object(scheduler,'collect_inputs',return_value=({},[article],[])) as collect,patch.object(scoring_engine,'get_stock_scores',return_value=[]),patch.object(analyst_agent,'run_analyst_agent',wraps=analyst_agent.run_analyst_agent) as agent:
            clock.now.return_value=NOW
            snapshot=scheduler.collect_snapshot()
        self.assertIn('TSM',collect.call_args.args[1]['symbols'])
        self.assertEqual(agent.call_count,1);self.assertIn('Agent review',snapshot['alerts'][0]['text'])
        self.assertEqual(snapshot['coverage'],coverage)

    def test_official_fetches_do_not_replace_the_separate_headline_feeds(self):
        seen=[]
        def fetch(url):
            seen.append(url)
            if url==publishers.OFFICIAL_FEEDS['MSFT']:return feed()
            if url==publishers.OFFICIAL_FEEDS['NVDA']:return feed('NVDA',title='NVIDIA unveils Rubin chip')
            raise OSError('Fixture source unavailable')
        details={}
        with patch.object(sources,'request_bytes',side_effect=fetch):
            _,news,issues=sources.collect_inputs(NOW,{**config(),'symbols':['MSFT','NVDA']},details)
        self.assertEqual({row['symbol'] for row in news},{'MSFT','NVDA'})
        self.assertIn('MSFT news',details);self.assertIn('MSFT official',details)
        self.assertTrue(any('headline?s=MSFT' in url for url in seen))

    def test_status_lists_company_health_and_ranking_scope_without_networking(self):
        from src.commands import special_alert_commands as commands
        coverage={'symbols':['NVDA','MSFT','PLTR','TSM'],'core':['NVDA','MSFT','PLTR'],'ranked':['TSM'],'ranking_status':'Top 1 from rankings dated 2026-10-20 (cache only)'}
        state={'last_source_status':{'MSFT official':'official feed read','NVDA news':'headline feed read','PLTR official':'publication times unavailable'}}
        with patch.object(commands,'company_universe',return_value=coverage),patch.object(commands.store,'get_settings',return_value=state),patch.object(commands,'destinations',return_value=[1]):
            text=commands.status_report()
        for symbol in coverage['symbols']:self.assertIn(symbol+':',text)
        self.assertIn('2026-10-20',text);self.assertIn('headline coverage only',text)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-socketpair',action='store_true')
    args=parser.parse_args(argv)
    with ExitStack() as stack:
        if args.windows_socketpair:
            stack.enter_context(patch.object(socket,'socketpair',portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    success=result.wasSuccessful() and not traffic['blocked']
    print(f"Company Alerts Check: {'PASS' if success else 'FAIL'} ({result.testsRun} tests)")
    if traffic['blocked']:print(f"FAIL: {len(traffic['blocked'])} unexpected provider connections blocked")
    return 0 if success else 1


if __name__=='__main__':
    raise SystemExit(main())
