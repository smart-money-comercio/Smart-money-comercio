"""Offline official publisher, peer-move narration and editorial-audit checks."""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_daily_news_brief import IsolatedChecks, NOW
from scripts.check_news_editor import candidate
from scripts.check_event_news import quote
from scripts.check_special_alerts import offline_network_guard, portable_tcp_socketpair
from src.intelligence import news_live_sources as feeds, news_original_sources as originals, news_editor as editor
from src.intelligence import news_editor_store as store, market_event_desk as events, company_focus as focus
from src.intelligence.special_alert_sources import company_url
from src.reports import daily_news_brief as news, daily_voiceover as voice
from src.utils.speech_text import normalize

INTEL = next(row for row in feeds.NEWS_SOURCES if row.get('company_symbol')=='INTC')
ASML = next(row for row in feeds.NEWS_SOURCES if row.get('company_symbol')=='ASML')
TITLE = 'Intel Reports Third-Quarter 2026 Financial Results'
URL = 'https://www.intc.com/news-events/press-releases/detail/123/fixture-results'
ASML_URL = 'https://investor.asml.com/news-releases/news-release-details/fixture-results'
AT = (NOW-timedelta(hours=1)).isoformat()


def payload(url,body,**changes):
    return {'url':url,'final_url':url,'body':body,'status':'ok','fetched_at_epoch':NOW.timestamp(),**changes}


def rss(title=TITLE,url=URL,published=AT):
    return '<rss><channel><item><title>'+title+'</title><link>'+url+'</link><pubDate>'+published+'</pubDate></item></channel></rss>'


def release(title=TITLE,clock=AT,date_only=False):
    metadata='' if date_only else '<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','headline':title,'datePublished':clock})+'</script>'
    return metadata+'<article><h1>'+title+'</h1><p>October 25, 2026</p><p>Company reports quarterly financial results. This is synthetic source text for offline verification of original issuer disclosures and publication identity.</p></article>'


class SourceChecks(IsolatedChecks):
    def intel(self,detail=None):
        return originals.enrich_feed(INTEL,payload(INTEL['url'],rss()),feeds.parse_rss_items,
                                     lambda url: detail or payload(url,release(date_only=True)),NOW)

    def asml(self,body=None,detail=None):
        body=body or '<a href="'+ASML_URL+'">ASML reports quarterly financial results</a>'
        return originals.retrieve(ASML,lambda url: payload(url,body) if url==ASML['url'] else
                                  detail or payload(url,release('ASML reports quarterly financial results')),NOW)

    def test_sources_use_observed_official_endpoints_and_require_original_bodies(self):
        self.assertEqual(INTEL['url'],'https://www.intc.com/news-events/press-releases/rss')
        self.assertEqual(ASML['url'],'https://investor.asml.com/news/press-releases-and-announcements')
        self.assertTrue(INTEL['requires_original_body'] and ASML['requires_original_body'])

    def test_intel_domains_are_allowed_without_admitting_lookalike_hosts(self):
        for url in (URL,'https://www.intel.com/newsroom/fixture'):
            self.assertTrue(company_url('INTC',url))
        for url in ('https://intc.com.attacker.test/fixture','https://www.intel.com@attacker.test/fixture','http://www.intc.com/fixture'):
            self.assertFalse(company_url('INTC',url))

    def test_intel_native_rss_clock_binds_an_exact_title_and_visible_release_date(self):
        value=self.intel();rows=feeds.parse_article_items(value,INTEL,full_titles=True,full_text=True)
        self.assertEqual(rows[0]['published'],AT)
        self.assertEqual(rows[0]['evidence_scope'],'original release excerpt')
        self.assertTrue(rows[0]['requires_original_body'])

    def test_intel_enrichment_reads_only_one_fresh_original_article(self):
        calls=[]
        value=originals.enrich_feed(INTEL,payload(INTEL['url'],rss()),feeds.parse_rss_items,
            lambda url:(calls.append(url) or payload(url,release(date_only=True))),NOW)
        self.assertEqual(calls,[URL]);self.assertEqual(len(value['release_evidence']),1)

    def test_newer_calendar_notice_does_not_consume_the_material_release_read(self):
        notice=rss(title='Intel to report quarterly financial results',url=URL+'-schedule',published=NOW.isoformat())
        body=rss().replace('</channel>',notice.split('<channel>')[1].split('</channel>')[0]+'</channel>')
        calls=[]
        value=originals.enrich_feed(INTEL,payload(INTEL['url'],body),feeds.parse_rss_items,
            lambda url:(calls.append(url) or payload(url,release(date_only=True))),NOW)
        self.assertEqual(calls,[URL]);self.assertEqual(value['release_evidence'][0]['title'],TITLE)

    def test_stale_material_release_is_not_reintroduced_by_body_prioritization(self):
        old=(NOW-timedelta(hours=25)).isoformat();calls=[]
        originals.enrich_feed(INTEL,payload(INTEL['url'],rss(published=old)),feeds.parse_rss_items,
            lambda url:calls.append(url),NOW)
        self.assertFalse(calls)

    def test_intel_wrong_title_or_day_withholds_body_evidence(self):
        for body in (release('Unrelated company announcement',date_only=True),release(date_only=True).replace('October 25','October 24')):
            value=self.intel(payload(URL,body))
            self.assertFalse(value['release_evidence'])

    def test_original_metadata_clock_conflict_is_not_replaced_by_the_feed_clock(self):
        value=self.intel(payload(URL,release(clock=(NOW-timedelta(hours=2)).isoformat())))
        self.assertFalse(value['release_evidence'])

    def test_intel_offsite_redirect_cannot_supply_a_release(self):
        value=self.intel(payload(URL,release(),final_url='https://attacker.test/news'))
        self.assertFalse(value['release_evidence'])

    def test_unread_intel_feed_can_supply_candidates_but_cannot_publish(self):
        cache={INTEL['url']:payload(INTEL['url'],rss())}
        candidates,_=editor.cache_candidates(NOW,['INTC'],cache=cache)
        brief={'rows':[{'symbol':'INTC','events':[]}],'issues':[],'ranking_date':'2026-10-23'}
        plan=editor.build_editorial_plan(brief,NOW,extra_candidates=candidates)
        self.assertEqual(plan['candidates'][0]['source_check'],'hold')
        self.assertIn('release body',plan['candidates'][0]['reason'])

    def test_verified_intel_release_enters_the_original_source_editor(self):
        candidates,_=editor.cache_candidates(NOW,['INTC'],cache={INTEL['url']:self.intel()})
        plan=editor.build_editorial_plan({'rows':[{'symbol':'INTC','events':[]}],'issues':[],'ranking_date':'2026-10-23'},NOW,extra_candidates=candidates)
        self.assertEqual(plan['candidates'][0]['decision'],'selected')
        self.assertEqual(plan['candidates'][0]['materiality'],'earnings')

    def test_asml_index_preserves_an_explicit_original_metadata_clock(self):
        value=self.asml();rows=originals.cached_items(value,ASML)
        self.assertEqual(rows[0]['published'],AT)
        self.assertEqual(rows[0]['evidence_scope'],'original release excerpt')
        self.assertTrue(rows[0]['requires_original_body'])

    def test_asml_naive_original_clock_remains_unverified(self):
        value=self.asml(detail=payload(ASML_URL,release('ASML reports quarterly financial results',clock='2026-10-25')))
        self.assertEqual(value['articles'][0]['published'],'')
        self.assertTrue(value['publication_problems'])

    def test_asml_update_time_does_not_replace_original_publication(self):
        body=release('ASML reports quarterly financial results').replace('"datePublished"','"dateModified"')
        self.assertEqual(self.asml(detail=payload(ASML_URL,body))['articles'][0]['published'],'')

    def test_asml_index_and_article_reads_remain_bounded(self):
        links=''.join('<a href="'+ASML_URL+str(i)+'">ASML fixture '+str(i)+'</a>' for i in range(8))
        calls=[]
        def fetch(url):
            calls.append(url)
            return payload(url,links if url==ASML['url'] else release('ASML fixture '+url[-1]))
        value=originals.retrieve(ASML,fetch,NOW)
        self.assertEqual(len(calls),4);self.assertEqual(len(value['articles']),3)

    def test_asml_redirect_does_not_cross_publisher_authority(self):
        value=self.asml(detail=payload(ASML_URL,release('ASML reports quarterly financial results'),final_url='https://attacker.test/news'))
        self.assertEqual(value['articles'][0]['published'],'')

    def test_fresh_missing_body_is_limited_even_when_the_feed_clock_is_known(self):
        health=feeds.describe_source(INTEL,payload(INTEL['url'],rss()),NOW)
        self.assertEqual(health['status'],'limited')
        self.assertIn('body verification',health['reason'])

    def test_verified_intel_body_is_reflected_in_source_health(self):
        health=feeds.describe_source(INTEL,self.intel(),NOW)
        self.assertEqual(health['status'],'available')
        self.assertEqual(health['fresh'],1)

    def test_eia_solar_and_storage_reports_are_recognized_without_inventing_a_price_effect(self):
        value=candidate(title='The share of solar generation with co-located battery storage is increasing')
        value.update(kind='macro',source='EIA',url='https://www.eia.gov/todayinenergy/detail.php?id=1',symbols=[],publisher_symbol='')
        self.assertEqual(editor.materiality(value),'energy')
        self.assertNotIn('prices rose',editor.render_story({**value,'materiality':'energy'},__import__('zoneinfo').ZoneInfo('America/New_York'),{}).lower())

    def test_community_features_remain_skipped_with_an_accurate_original_source_reason(self):
        value=candidate('CACI',title="CACI's Good Dogs for Great Americans Reaches $50K Milestone to Fund First Veteran-Service Dog Team")
        plan=editor.build_editorial_plan({'rows':[{'symbol':'CACI','events':[]}],'issues':[],'ranking_date':'2026-10-23'},NOW,extra_candidates=[value])
        story=plan['candidates'][0]
        self.assertEqual(story['decision'],'skip')
        self.assertIn('Original publisher item',story['reason'])
        self.assertNotIn('Opinion',story['reason'])

    def test_euro_and_pound_amounts_keep_their_currency_in_speech(self):
        self.assertEqual(normalize('€11.7 billion'),'eleven point seven billion euros')
        self.assertEqual(normalize('€5B'),'five billion euros')
        self.assertEqual(normalize('£1.25'),'one pound and twenty five pence')
        self.assertNotIn('dollars',normalize('€11.7 billion'))


class PresentationChecks(IsolatedChecks):
    def research_moves(self,pending=False):
        values={'INTC':-28.65,'AMD':-9.8,'ASML':-5.7}
        if not pending: events.review_quotes({symbol:quote(symbol,value) for symbol,value in values.items()},lambda symbol:quote(symbol,values[symbol]),NOW)
        return self.research(replacements={'Watchlist Movers':'Largest regular-session movers:\n'+'\n'.join('• '+symbol+': $88.00 ('+str(value)+'%)' for symbol,value in values.items())})

    def render(self,values=None,research=None,legacy=False):
        research=research or self.research_moves()
        context=focus.history_context(NOW)
        if legacy: context['schema']=4
        with patch.object(editor,'cache_candidates',return_value=(values or [],[])),patch.object(focus,'history_context',return_value=context):
            report=news.build_daily_news_brief(research)
        return report,store.read_editions(report=report)[0]

    def test_three_checked_peer_moves_share_one_follow_up_in_the_text_brief(self):
        text,record=self.render()
        self.assertEqual(text.count('Semiconductor sell-off —'),1)
        self.assertIn('Intel fell 28.6 percent',text)
        self.assertIn('ASML fell 5.7 percent',text)
        self.assertIn('Advanced Micro Devices fell 9.8 percent',text)
        self.assertEqual(text.count('These moves do not establish a shared cause'),1)
        self.assertNotIn('Event watch —',text)
        self.assertEqual(record['analyst_review']['evidence']['company_focus']['featured_symbols'],['AMD','ASML','INTC'])

    def test_spoken_companion_groups_the_same_verified_companies(self):
        _,record=self.render();profile=voice.checked(record,NOW)
        self.assertEqual(sum(scene['heading']=='Companies in Focus' for scene in profile['segments']),1)
        self.assertIn('Intel fell twenty eight point six percent',profile['script'])
        self.assertIn('shared cause',profile['script'])
        self.assertTrue(profile['quality']['passes'])

    def test_pending_moves_never_enter_the_verified_peer_group(self):
        text,record=self.render(research=self.research_moves(True))
        self.assertNotIn('Semiconductor sell-off',text)
        self.assertNotIn('28.6 percent',text)
        self.assertNotIn('twenty eight point six percent',record['voiceover']['script'])

    def test_a_new_original_earnings_story_is_kept_separate_from_price_comparisons(self):
        story=candidate('INTC',title=TITLE)
        text,record=self.render([story])
        self.assertIn(TITLE,text)
        self.assertIn('Semiconductor sell-off',text)
        passage=next(row['text'] for row in record['analyst_review']['insights'] if row['id']=='company_focus_moves')
        self.assertNotIn('Intel',passage)
        self.assertEqual(len(editor.selected_stories(record)),1)

    def test_old_focus_schemas_retain_their_original_individual_paragraphs(self):
        text,record=self.render(legacy=True)
        self.assertNotIn('Semiconductor sell-off',text)
        self.assertIn('Event watch — Intel',text)
        self.assertEqual(record['analyst_review']['focus_context']['schema'],4)
        self.assertTrue(voice.checked(record,NOW)['quality']['passes'])

    def test_group_retains_all_names_without_changing_rankings_or_scores(self):
        research=self.research_moves();before=self.ranking.read_bytes()
        text,record=self.render(research=research)
        self.assertFalse(record['analyst_review']['score_changes'])
        self.assertEqual(self.ranking.read_bytes(),before)
        self.assertEqual(record['research_text'],research)
        self.assertTrue(news.validate_news_brief(text)['passes'])

    def test_a_mixed_peer_group_is_not_called_a_sell_off(self):
        _,record=self.render();evidence=deepcopy(record['analyst_review']['evidence'])
        evidence['company_focus']['selected'][0]['metric']['price']=12
        group=focus.grouped_price_watch(evidence)
        self.assertEqual(group['label'],'Semiconductor watch')
        self.assertNotIn('sell-off',group['text'])

    def test_market_alert_is_not_repeated_in_defense_or_over_the_newer_snapshot(self):
        from src.intelligence import special_alert_store as alerts
        older={'^GSPC':{'name':'S&P 500','change':-1.49,'asof':(NOW-timedelta(minutes=2)).isoformat()},
               '^IXIC':{'name':'Nasdaq Composite','change':-2.41,'asof':(NOW-timedelta(minutes=2)).isoformat()}}
        self.event({'key':'market','kind':'market','symbols':[],'level':1,'expires':NOW.timestamp()+600,'evidence':older})
        text,_=self.render()
        self.assertNotIn('active market-alert record',text)
        self.assertNotIn('-2.41%',text)
        self.assertTrue(alerts.read_current_events(NOW.timestamp()))

    def test_fresh_original_decisions_explain_skips_without_extra_source_reads(self):
        with patch.dict('os.environ',{'SPECIAL_ALERT_SYMBOLS':'CACI,INTC,MSFT,NVDA'}):
            self.render([candidate('CACI',title="CACI's Good Dogs Reaches a Community Milestone"),candidate('INTC',title=TITLE)])
        text=editor.build_editor_status()
        self.assertIn('Fresh original-report decisions',text)
        self.assertIn('SELECTED — '+TITLE,text)
        self.assertIn('SKIP — CACI',text)
        self.assertIn('headline does not establish',text)

    def test_spoken_export_rejects_an_altered_group(self):
        _,record=self.render()
        group=next(row for row in record['analyst_review']['insights'] if row['id']=='company_focus_moves')
        group['text']+=' Earnings caused the decline.'
        with self.assertRaises(ValueError):voice.episode(record,NOW)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--windows-socketpair',action='store_true');args=parser.parse_args()
    with ExitStack() as stack:
        if args.windows_socketpair:stack.enter_context(patch.object(socket,'socketpair',portable_tcp_socketpair))
        traffic=stack.enter_context(offline_network_guard())
        result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    passed=result.wasSuccessful() and not traffic['blocked']
    print(f"Semiconductor News Check: {'PASS' if passed else 'FAIL'} ({result.testsRun} tests)")
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
